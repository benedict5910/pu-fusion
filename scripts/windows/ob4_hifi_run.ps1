# OB4 high-fidelity CAD / 3D viewer upgrade - full verification on the project PC. Non-interactive; commits nothing.
#   1. ob4_pc_run.ps1: preflight, verified gearbox recordings, FreeCAD build (FCStd + STEP + self-check), FreeCAD GUI
#      renders + TechDraw, STEP -> GLB export, drawings, verify_ob4 (15 scenarios / 148 checks), full unit-test suite
#   2. frozen models and historical results unchanged (git diff against the ob4-cad-testbed commit)
#   3. starts the integrated dashboard on http://localhost:8520 in its own window (if not already running)
# Result: results\ob4_cad\hifi_<timestamp>.txt (+ the pc_run_<timestamp> evidence folder written by step 1)
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log = Join-Path $Root "results\ob4_cad\hifi_$Stamp.txt"
function Say($m) { Write-Host $m; Add-Content -Path $Log -Value $m -Encoding UTF8 }
Say "OB4 hi-fi run $Stamp"

Say '=== 1. ob4_pc_run.ps1 ==='
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'ob4_pc_run.ps1')
$runExit = $LASTEXITCODE
$run = Get-ChildItem (Join-Path $Root 'results\ob4_cad') -Directory -Filter 'pc_run_*' | Sort-Object Name | Select-Object -Last 1
Say "pc_run exit: $runExit; evidence: $($run.FullName)"
if (Test-Path (Join-Path $run.FullName 'summary.json')) {
    $S = Get-Content (Join-Path $run.FullName 'summary.json') -Raw | ConvertFrom-Json
    Say "result: $($S.result)"
    foreach ($p in $S.checks.PSObject.Properties) { Say ("  {0,-5} {1}" -f $(if ($p.Value) { 'PASS' } else { 'FAIL' }), $p.Name) }
    Say "unittest: $($S.unittest_tail)"
}

Say '=== 2. frozen models / historical results ==='
$frozen = @(git status --porcelain -- models results data docs/FINAL_OB1_OB2_OB4_2026-11-15.md 2>&1 | Where-Object { $_ -notmatch 'results/ob4_cad/' })
Say "changed frozen paths: $($frozen.Count)"
$frozen | ForEach-Object { Say "  $_" }
Get-ChildItem "$Root\models\*.pkl" | ForEach-Object { Say ("  {0} {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name) }

Say '=== 3. dashboard ==='
$up = $false
try { $up = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://localhost:8520/_stcore/health').StatusCode -eq 200 } catch {}
if ($up) { Say 'dashboard already running on :8520 (restart it to load the new viewer code if it was started before this run)' }
else {
    Start-Process cmd.exe -ArgumentList '/c', "`"$Root\scripts\windows\run_integrated_dashboard.bat`""
    Say 'dashboard started in its own window on http://localhost:8520'
}
Say "DONE exit=$runExit"
exit $runExit
