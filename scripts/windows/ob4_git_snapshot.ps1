# OB4 Git snapshot BEFORE the high-fidelity CAD/3D upgrade. Non-interactive. Nothing is pushed.
#   master            = unchanged Nov 15 baseline (OB4 additions removed, three files restored to Nov 15 bytes)
#   ob4-cad-testbed   = the verified OB4 work as it stands now (pc_run_20261120-002515 passed all checks)
# The high-fidelity upgrade is committed later, on top, as its own commit.
# Re-run safe: a repository made by an earlier run of THIS script (marker file in the git dir) is rebuilt; any
# other existing repository is left untouched. Log: results\ob4_cad\git_snapshot_<timestamp>.txt
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log = Join-Path $Root "results\ob4_cad\git_snapshot_$Stamp.txt"
Start-Transcript -Path $Log | Out-Null
function Done($code, $msg) { Write-Host $msg; Write-Host "RESULT: $code"; try { Stop-Transcript | Out-Null } catch {}; exit $code }
function G { $o = (& git @args 2>&1 | Out-String); if ($o.Trim()) { Write-Host $o.TrimEnd() }; return $LASTEXITCODE }

$gitdir = 'E:\ivhm-data\git\pu-fusion-ob4.git'
$marker = Join-Path $gitdir 'ob4_snapshot_script'
$dotgit = Join-Path $Root '.git'
$redo = (Test-Path $gitdir) -and ((Test-Path $marker) -or ((Get-Item $gitdir).CreationTime -gt [datetime]'2026-11-21 03:15'))
if (Test-Path $gitdir) {
    if (-not $redo) { Done 3 "STOP: $gitdir exists and was not made by this script - not touching it." }
    $n = @(git log --all --oneline 2>$null).Count
    if ($n -gt 2) { Done 3 "STOP: repository has $n commits (more than this script makes) - not touching it." }
    Write-Host "Rebuilding the repository made by the earlier snapshot run ($n commits, nothing pushed)."
    Remove-Item $dotgit -Force -ErrorAction SilentlyContinue
    Remove-Item $gitdir -Recurse -Force
} elseif (Test-Path $dotgit) { Done 3 'STOP: .git present without the expected git dir - not touching it.' }
$user = (git config user.name); $mail = (git config user.email)
Write-Host "git user: $user <$mail>"
if (-not $user -or -not $mail) { Done 4 'STOP: git user.name / user.email not set.' }
New-Item -ItemType Directory -Force -Path (Split-Path $gitdir) | Out-Null

$null = G init -q -b master --separate-git-dir $gitdir $Root
Set-Content $marker 'created by scripts/windows/ob4_git_snapshot.ps1'
$null = G config core.autocrlf false
Add-Content (Join-Path $gitdir 'info\exclude') "verification/`r`nob4-cad-testbed.patch`r`nscripts/windows/_baseline/`r`n__pycache__/"
$null = G add -A
Write-Host "Indexed (all): $(@(git ls-files).Count)"
$drop = @(Get-Content 'scripts\windows\_baseline\ob4_added_files.txt' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) +
        @('cad', 'results/ob4_cad', 'scripts/windows/ob4_finish.ps1', 'scripts/windows/ob4_git_snapshot.ps1',
          'scripts/windows/ob4_git_snapshot.bat')
foreach ($p in $drop) { $null = G rm -r -q -f --cached --ignore-unmatch -- $p }
$h1 = (git hash-object -w 'scripts\windows\_baseline\dashboard.py').Trim()
$h2 = (git hash-object -w 'scripts\windows\_baseline\gitignore').Trim()
$h3 = (git hash-object -w 'scripts\windows\_baseline\fake_streamlit.py').Trim()
$null = G update-index --cacheinfo "100644,$h1,app/dashboard.py"
$null = G update-index --cacheinfo "100644,$h2,.gitignore"
$null = G update-index --cacheinfo "100644,$h3,tests/fake_streamlit.py"
$left = @(git ls-files -- cad app/testbed_view.py app/cad3d.py src/pufusion/drivetrain_cad.py results/ob4_cad)
Write-Host "Baseline files: $(@(git ls-files).Count); OB4 paths still indexed: $($left.Count)"
if ($left.Count -gt 0) { $left | Select-Object -First 10 | Out-Host; Done 5 'STOP: OB4 files still in the baseline index.' }
if ((G commit -q -m "Nov 15 2026 IVHM baseline (archive pu-fusion_final_2026-11-15.zip, SHA-256 c81db673...)") -ne 0) { Done 5 'STOP: baseline commit failed.' }
$null = G checkout -q -b ob4-cad-testbed
$null = G add -A
$st = @(git diff --cached --name-only)
Write-Host "OB4 commit: $($st.Count) files"
if ((G commit -q -F 'scripts\windows\ob4_commit_message.txt') -ne 0) { Done 6 'STOP: OB4 commit failed.' }
$null = G log --oneline --all --graph
Write-Host "master files: $(@(git ls-tree -r --name-only master).Count); ob4-cad-testbed files: $(@(git ls-tree -r --name-only ob4-cad-testbed).Count)"
$null = G status --short
Done 0 'OK: master (baseline) and ob4-cad-testbed (OB4 as verified on 2026-11-20) committed. Nothing pushed.'
