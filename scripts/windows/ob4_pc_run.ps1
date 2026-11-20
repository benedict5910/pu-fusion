# OB4 on the project PC: locate FreeCAD, recover the verified gearbox recordings, build the CAD model,
# render it in the FreeCAD GUI, run the OB4 verification and the full test suite. Commits nothing.
# Every output goes to a NEW folder results\ob4_cad\pc_run_<timestamp>\ (summary.json + logs); cad\out\ is
# regenerated. Run:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\ob4_pc_run.ps1
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Out = Join-Path $Root "results\ob4_cad\pc_run_$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Start-Transcript -Path (Join-Path $Out 'transcript.txt') | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$S = [ordered]@{ started = (Get-Date).ToString('s'); root = $Root; out = $Out }
function Save-Summary { $S | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Out 'summary.json') }
function Run-Proc($exe, $argList, $logBase, $timeoutSec) {
    try {
        $p = Start-Process -FilePath $exe -ArgumentList $argList -NoNewWindow -PassThru -ErrorAction Stop `
            -RedirectStandardOutput "$logBase.stdout.txt" -RedirectStandardError "$logBase.stderr.txt"
    } catch { Stop-Fatal "could not start $exe ($_)" }
    $null = $p.Handle      # PowerShell 5.1: read the handle now, otherwise ExitCode is $null after exit
    if (-not $p.WaitForExit($timeoutSec * 1000)) { try { $p.Kill() } catch {} ; return 'TIMEOUT' }
    $p.WaitForExit()
    return $p.ExitCode
}

function Stop-Fatal($msg) {
    $S.result = "STOPPED: $msg"; $S.finished = (Get-Date).ToString('s'); Save-Summary
    Write-Host "`nSTOPPED - $msg" -ForegroundColor Red
    Write-Host "Nothing after this point was run. Evidence: $Out" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
function Test-Exec($name, $exe, [string[]]$argv) {
    $r = [ordered]@{ name = $name; exe = $exe; args = ($argv -join ' '); ok = $false }
    try {
        $o = (& $exe @argv 2>&1 | Out-String).Trim()
        $r.exit = $LASTEXITCODE; $r.output = $o.Substring(0, [math]::Min(400, $o.Length)); $r.ok = ($LASTEXITCODE -eq 0)
    } catch { $r.error = $_.Exception.Message }
    $col = 'Red'; if ($r.ok) { $col = 'Green' }
    Write-Host ("  {0,-10} {1}  {2}" -f $name, $(if ($r.ok) { 'OK  ' } else { 'FAIL' }), $(if ($r.ok) { $r.output.Split("`n")[0] } else { "$($r.error) $($r.output)" })) -ForegroundColor $col
    return $r
}

Write-Host "=== Preflight: can this shell start programs? ===" -ForegroundColor Cyan
$P = [ordered]@{}
# who started this shell, and is its token restricted / low-integrity (typical of sandboxed agent terminals)?
$chain = @(); $id = $PID
for ($i = 0; $i -lt 8 -and $id; $i++) {
    $w = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if (-not $w) { break }; $chain += "$($w.Name) [$($w.ProcessId)]"; $id = $w.ParentProcessId
}
$P.parent_chain = $chain
$ident = [Security.Principal.WindowsIdentity]::GetCurrent()
$sids = @($ident.Groups | ForEach-Object { $_.Value })
$P.restricted_token = $sids -contains 'S-1-5-12'
$P.integrity = @($sids | Where-Object { $_ -like 'S-1-16-*' })
$P.cmd = Test-Exec 'cmd.exe' $env:ComSpec @('/c', 'ver')
$P.python = Test-Exec 'python' 'python' @('-c', 'import sys, numpy, sklearn, pandas, streamlit, altair; print(sys.executable, sys.version.split()[0])')
$P.git = Test-Exec 'git' 'git' @('--version')
$fcCands = @(Get-ChildItem 'E:\freecad\bin\freecadcmd.exe', "$env:ProgramFiles\FreeCAD*\bin\freecadcmd.exe", "$env:LOCALAPPDATA\Programs\FreeCAD*\bin\freecadcmd.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName)
if ($fcCands.Count -gt 0) { $P.freecad = Test-Exec 'freecadcmd' $fcCands[0] @('--version') } else { $P.freecad = [ordered]@{ ok = $false; error = 'freecadcmd.exe not found' } }
$S.preflight = $P; Save-Summary
Write-Host ("  started by: {0}" -f ($chain -join ' <- '))
Write-Host ("  restricted token: {0}; integrity SID: {1}" -f $P.restricted_token, ($P.integrity -join ','))
$bad = @('python', 'git', 'freecad') | Where-Object { -not $P[$_].ok }
if ($bad) {
    if (-not $P.cmd.ok) {
        $why = 'this shell may not start ANY program (even cmd.exe) - the launching context is restricted (sandboxed/agent terminal or a security policy), not a path problem. Run from a normal Windows PowerShell window opened from the Start menu, or double-click scripts\windows\ob4_finish.bat in File Explorer.'
    } else {
        $why = "cmd.exe starts but $($bad -join ', ') do not: check those paths/permissions or an application-control policy (see preflight in summary.json)."
    }
    Stop-Fatal "preflight failed for $($bad -join ', '): $why"
}

Write-Host "=== Phase 2: gearbox recordings ===" -ForegroundColor Cyan
$man = Get-Content (Join-Path $Root 'models\gearbox_demo_manifest.json') -Raw | ConvertFrom-Json
$S.free_space_MB = @(Get-PSDrive -PSProvider FileSystem | ForEach-Object { [ordered]@{ drive = $_.Name; free_MB = [math]::Round($_.Free / 1MB) } })
# plain folder inside the project (no junction); verified copies only - the source recordings are never modified
$dest = Join-Path $Root 'data\mcc5_demo'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$S.gearbox_store = $dest
function Test-Rec($path, $want) {
    return (Test-Path $path) -and ((Get-Item $path).Length -eq $want.bytes) -and
           ((Get-FileHash $path -Algorithm SHA256).Hash.ToLower() -eq $want.sha256)
}
$search = @("$env:TEMP\ivhm_mcc5_demo", "$env:LOCALAPPDATA\Temp\ivhm_mcc5_demo", "$Root\data\mcc5",
            "$env:USERPROFILE\Projects\pu-fusion-current\data", "$env:USERPROFILE\Projects\pu-fusion\data",
            "$env:USERPROFILE\Downloads", 'E:\ivhm-data') | Select-Object -Unique
$S.gearbox_search_dirs = $search
$rec = [ordered]@{}
foreach ($prop in $man.recordings.PSObject.Properties) {
    $name = $prop.Name; $want = $prop.Value
    $entry = [ordered]@{ expected_sha256 = $want.sha256; expected_bytes = $want.bytes; candidates = @(); status = 'missing' }
    $target = Join-Path $dest $name
    if (Test-Rec $target $want) {
        $entry.status = 'already present, verified'; $entry.source = $target
    } else {
        foreach ($d in $search) {
            if (-not (Test-Path $d)) { continue }
            Get-ChildItem -Path $d -Filter $name -File -Recurse -Depth 4 -ErrorAction SilentlyContinue | ForEach-Object {
                $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
                $ok = ($_.Length -eq $want.bytes) -and ($h -eq $want.sha256)
                $entry.candidates += [ordered]@{ path = $_.FullName; bytes = $_.Length; sha256 = $h; verified = $ok }
                if ($ok -and $entry.status -eq 'missing') {
                    try { Copy-Item $_.FullName $target -Force -ErrorAction Stop } catch { $entry.copy_error = "$_" }
                    if (Test-Rec $target $want) { $entry.status = 'copied, verified'; $entry.source = $_.FullName }
                    else { $entry.status = 'copy did not verify (left in place, not used)' }
                }
            }
            if ($entry.status -ne 'missing') { break }
        }
        if ($entry.status -eq 'missing') {   # the project's own GitHub release (same files, same hashes)
            $tmp = "$target.download"
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri ($man.release_url + $name) -OutFile $tmp -UseBasicParsing
                $h = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
                if (((Get-Item $tmp).Length -eq $want.bytes) -and ($h -eq $want.sha256)) {
                    Move-Item $tmp $target -Force; $entry.status = 'downloaded from project release, verified'
                    $entry.source = $man.release_url + $name
                } else { Remove-Item $tmp -Force; $entry.status = "download hash mismatch ($h) - discarded" }
            } catch { if (Test-Path $tmp) { Remove-Item $tmp -Force }; $entry.download_error = "$_" }
        }
    }
    if (Test-Path $target) { $entry.final_sha256 = (Get-FileHash $target -Algorithm SHA256).Hash.ToLower() }
    $rec[$name] = $entry
    Write-Host ("{0}: {1}" -f $name, $entry.status)
}
$S.gearbox_recordings = $rec
$missing = @($rec.Keys | Where-Object { $rec[$_].status -notlike '*verified*' })
if ($missing) { Stop-Fatal "gearbox recordings not verified: $($missing -join ', ')" }
Save-Summary

Write-Host "=== Phase 1: FreeCAD ===" -ForegroundColor Cyan
$cands = New-Object System.Collections.Generic.List[string]
foreach ($n in 'freecadcmd.exe') { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c) { $cands.Add($c.Source) } }
$reg = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
       'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
       'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
$regHits = @()
foreach ($rp in $reg) {
    Get-ItemProperty $rp -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'FreeCAD*' } | ForEach-Object {
        $regHits += [ordered]@{ name = $_.DisplayName; version = $_.DisplayVersion; location = $_.InstallLocation; icon = $_.DisplayIcon }
        $locs = @($_.InstallLocation)
        if ($_.DisplayIcon) { $locs += (Split-Path (($_.DisplayIcon -replace '"', '') -replace ',\d+$', '')) }
        if ($_.UninstallString) { $locs += (Split-Path (($_.UninstallString -replace '"', '') -split ' /')[0]) }
        foreach ($loc in $locs) { if ($loc) { foreach ($sub in '', 'bin') {
            $p = Join-Path (Join-Path $loc $sub) 'freecadcmd.exe'; if (Test-Path $p) { $cands.Add((Resolve-Path $p).Path) } } } }
    }
}
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs", 'C:\', 'D:\', 'E:\')) {
    if ($base -and (Test-Path $base)) {
        Get-ChildItem -Path $base -Directory -Filter '*FreeCAD*' -ErrorAction SilentlyContinue | ForEach-Object {
            foreach ($p in (Join-Path $_.FullName 'bin\freecadcmd.exe'), (Join-Path $_.FullName 'freecadcmd.exe')) {
                if (Test-Path $p) { $cands.Add($p) } } }
    }
}
$cands = @($cands | Select-Object -Unique)
$S.freecad_registry = $regHits
$S.freecad_candidates = $cands
$FC = $null
if ($cands.Count -gt 0) {
    # prefer the newest by file version
    $FC = @($cands | Sort-Object { (Get-Item $_).VersionInfo.FileVersionRaw } -Descending)[0]
}
$S.freecadcmd = $FC
if ($FC) {
    $GUI = Join-Path (Split-Path $FC) 'FreeCAD.exe'
    if (Test-Path $GUI) { $S.freecad_gui = $GUI } else { $S.freecad_gui = $null }
}
Save-Summary
if ($FC) {
    Write-Host "freecadcmd: $FC"
    $S.freecad_version_cli = (& $FC --version 2>&1 | Out-String).Trim()
    $env:IVHM_FC_CHECK_OUT = Join-Path $Out 'freecad_env.json'
    $S.freecad_env_exit = Run-Proc $FC "`"$Root\cad\check_freecad_env.py`"" (Join-Path $Out 'freecad_env') 300
    if (Test-Path $env:IVHM_FC_CHECK_OUT) { $S.freecad_env = Get-Content $env:IVHM_FC_CHECK_OUT -Raw | ConvertFrom-Json }
} else { Write-Host 'FreeCAD NOT FOUND' -ForegroundColor Red }
Save-Summary

Write-Host "=== Phase 3: CAD build ===" -ForegroundColor Cyan
$env:IVHM_ROOT = $Root
$env:IVHM_EXIT_AFTER = '1'
if ($FC) {
    if (Test-Path "$Root\cad\out\freecad_report.json") { Remove-Item "$Root\cad\out\freecad_report.json" -Force }
    $S.cad_build_exit = Run-Proc $FC "`"$Root\cad\build_freecad.py`"" (Join-Path $Out 'freecad_build') 1800
    if (Test-Path "$Root\cad\out\freecad_report.json") {
        Copy-Item "$Root\cad\out\freecad_report.json" $Out
        $r = Get-Content "$Root\cad\out\freecad_report.json" -Raw | ConvertFrom-Json
        $S.cad_report = [ordered]@{ passed = $r.passed; version = $r.freecad_version; valid = $r.all_parts_valid;
            bbox_dev = $r.bbox_max_deviation_mm; exports = $r.exports; errors = @($r.errors).Count;
            unexpected_overlaps = @($r.interference.unexpected).Count; edit_test = $r.edit_test; step_reimport = $r.step_reimport }
    } else { $S.cad_report = 'freecad_report.json NOT produced' }
    Save-Summary
    if ($S.freecad_gui) {
        $S.gui_render_exit = Run-Proc $S.freecad_gui "`"$Root\cad\freecad_gui_snapshots.py`"" (Join-Path $Out 'freecad_gui') 600
        if (Test-Path "$Root\cad\out\gui_snapshot_report.json") { Copy-Item "$Root\cad\out\gui_snapshot_report.json" $Out }
    }
    # 3D viewer model: GLB tessellated from the STEP just exported (keeps the GLB in step with the CAD build)
    if (Test-Path "$Root\cad\out\glb_export_report.json") { Remove-Item "$Root\cad\out\glb_export_report.json" -Force }
    $S.glb_export_exit = Run-Proc $FC "`"$Root\cad\export_glb.py`"" (Join-Path $Out 'export_glb') 900
    if (Test-Path "$Root\cad\out\glb_export_report.json") {
        Copy-Item "$Root\cad\out\glb_export_report.json" $Out
        $g = Get-Content "$Root\cad\out\glb_export_report.json" -Raw | ConvertFrom-Json
        $S.glb_report = [ordered]@{ passed = $g.passed; nodes = $g.nodes; triangles = $g.triangles; bytes = $g.glb_bytes;
            max_bbox_dev_mm = $g.max_bbox_dev_mm; max_mesh_vs_brep_dev_mm = $g.max_mesh_vs_brep_dev_mm }
    } else { $S.glb_report = 'glb_export_report.json NOT produced' }
    Save-Summary
}
$PY_DRAW = 'python'
& python -c "import matplotlib" 2>$null
if ($LASTEXITCODE -ne 0 -and $FC) {
    $fcpy = Join-Path (Split-Path $FC) 'python.exe'
    if (Test-Path $fcpy) { $PY_DRAW = $fcpy }
}
$S.drawings_python = $PY_DRAW
$S.drawings_exit = Run-Proc $PY_DRAW "`"$Root\cad\make_drawings.py`"" (Join-Path $Out 'make_drawings') 900
$S.cad_files = @(Get-ChildItem "$Root\cad\out" -Recurse -File | ForEach-Object {
    [ordered]@{ path = $_.FullName.Substring($Root.Length + 1); bytes = $_.Length } })
Save-Summary

Write-Host "=== Phase 4: verification + tests ===" -ForegroundColor Cyan
& python --version *> (Join-Path $Out 'env.txt')
& python -m pip show streamlit altair pandas numpy scikit-learn scipy matplotlib *>> (Join-Path $Out 'env.txt')
$S.verify_exit = Run-Proc 'python' "`"$Root\scripts\verify_ob4.py`" --out `"$Out\verification`"" (Join-Path $Out 'verify_ob4') 3600
if (Test-Path "$Out\verification\verification.json") {
    $v = Get-Content "$Out\verification\verification.json" -Raw | ConvertFrom-Json
    $S.verdict = $v.verdict; $S.regression = $v.regression_replay; $S.fallback_abstention = $v.fallback_abstention
}
Save-Summary
$S.unittest_exit = Run-Proc 'python' '-m unittest discover -s tests -v' (Join-Path $Out 'unittest') 5400
$ulog = Get-Content (Join-Path $Out 'unittest.stderr.txt') -Raw
$S.unittest_tail = ($ulog -split "`n" | Select-Object -Last 6) -join "`n"
$S.unittest_skips = @($ulog -split "`n" | Where-Object { $_ -match '\.\.\. skipped' })
$S.unittest_failures = @($ulog -split "`n" | Where-Object { $_ -match '\.\.\. (FAIL|ERROR)$' })
Save-Summary

Write-Host "=== Git state (nothing committed) ===" -ForegroundColor Cyan
$S.git_version = (& git --version 2>&1 | Out-String).Trim()
$S.git_user = (& git config user.name 2>&1 | Out-String).Trim()
$S.git_repo_present = Test-Path (Join-Path $Root '.git')
$S.models_sha256 = @(Get-ChildItem "$Root\models\*.pkl" | ForEach-Object {
    [ordered]@{ file = $_.Name; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } })
$gui = Get-Content "$Root\cad\out\gui_snapshot_report.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json -ErrorAction SilentlyContinue
$checks = [ordered]@{
    'gearbox recordings verified'           = $true
    'CAD build report passed'               = ($S.cad_report -isnot [string]) -and ($S.cad_report.passed -eq $true)
    'FreeCAD GUI renders + TechDraw PDF'    = ($gui -ne $null) -and (@($gui.errors).Count -eq 0) -and ($gui.techdraw_pdf -eq $true)
    '3D viewer GLB from STEP (93 nodes)'    = ($S.glb_report -isnot [string]) -and ($S.glb_report.passed -eq $true) -and ($S.glb_report.nodes -eq 93)
    'drawings (make_drawings.py) exit 0'    = ($S.drawings_exit -eq 0)
    'verify_ob4: 15 scenarios / 148 checks' = ($S.regression -ne $null) -and ($S.regression.matches_documented_15_148 -eq $true)
    'verify_ob4 exit 0 (no FAIL verdicts)'  = ($S.verify_exit -eq 0)
    'unit tests exit 0'                     = ($S.unittest_exit -eq 0)
}
$S.checks = $checks
$S.result = if (@($checks.Values | Where-Object { -not $_ }).Count -eq 0) { 'ALL PASSED' } else { 'SOME CHECKS FAILED' }
$S.finished = (Get-Date).ToString('s')
Save-Summary
Write-Host "`n=== Result ===" -ForegroundColor Cyan
foreach ($k in $checks.Keys) { if ($checks[$k]) { Write-Host "  PASS  $k" -ForegroundColor Green } else { Write-Host "  FAIL  $k" -ForegroundColor Red } }
Write-Host "Evidence: $Out"
Stop-Transcript | Out-Null
if ($S.result -ne 'ALL PASSED') { exit 2 }
exit 0
