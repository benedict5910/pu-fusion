# OB4 - everything that remains on the project PC, in one script. Run from any PowerShell window:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Admin\Projects\pu-fusion-ob4-2026-11-15\scripts\windows\ob4_finish.ps1
# 1. runs ob4_pc_run.ps1: preflight (can Python, Git, FreeCAD start?), verified recordings in data\mcc5_demo,
#    CAD build + GUI renders, drawings, OB4 verification, full unit-test suite -> results\ob4_cad\pc_run_<timestamp>\
#    It stops at the first critical failure. Steps 2 and 3 run only if every check passed.
# 2. starts the integrated dashboard (http://localhost:8520) in its own window
# 3. Git: repository data on E: (C: is nearly full); master = unchanged Nov 15 baseline, branch ob4-cad-testbed =
#    OB4 work. Shows what would be committed and asks before each commit. Nothing is pushed.
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root

Write-Host "=== 1. OB4 PC run ===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'ob4_pc_run.ps1')
$runExit = $LASTEXITCODE
if ($runExit -ne 0) {
    Write-Host "`nOB4 PC run did not pass (exit $runExit) - dashboard and Git steps NOT run. See the newest results\ob4_cad\pc_run_* folder (summary.json, transcript.txt)." -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit $runExit
}

Write-Host "=== 2. Dashboard ===" -ForegroundColor Cyan
try {
    Start-Process cmd.exe -ArgumentList '/c', "`"$Root\scripts\windows\run_integrated_dashboard.bat`"" -ErrorAction Stop
    Write-Host 'Dashboard starting in its own window on http://localhost:8520 (leave that window open).'
} catch {
    Write-Host "Dashboard could not be started: $_" -ForegroundColor Red
    Read-Host 'Press Enter to close'; exit 3
}

Write-Host "=== 3. Git (nothing is pushed) ===" -ForegroundColor Cyan
if (Test-Path (Join-Path $Root '.git')) {
    Write-Host '.git already exists here - Git step skipped (no changes made).' -ForegroundColor Yellow
} elseif (-not (git config user.name)) {
    Write-Host 'git user.name is not set - Git step skipped. Set it and re-run only this part.' -ForegroundColor Yellow
} else {
    $gitdir = 'E:\ivhm-data\git\pu-fusion-ob4.git'
    git init -q -b master --separate-git-dir $gitdir $Root
    git config core.autocrlf false
    Add-Content (Join-Path $gitdir 'info\exclude') "verification/`r`nob4-cad-testbed.patch`r`nscripts/windows/_baseline/"
    git add -A
    # baseline index = working tree minus OB4 additions, with the three modified files restored to their Nov 15 bytes
    $drop = @(Get-Content 'scripts\windows\_baseline\ob4_added_files.txt') + @('cad', 'results/ob4_cad', 'scripts/windows/ob4_finish.ps1')
    git rm -r -q --cached --ignore-unmatch -- $drop | Out-Null
    $h1 = git hash-object -w 'scripts\windows\_baseline\dashboard.py'
    $h2 = git hash-object -w 'scripts\windows\_baseline\gitignore'
    git update-index --cacheinfo "100644,$h1,app/dashboard.py"
    git update-index --cacheinfo "100644,$h2,.gitignore"
    $h3 = git hash-object -w 'scripts\windows\_baseline\fake_streamlit.py'
    git update-index --cacheinfo "100644,$h3,tests/fake_streamlit.py"
    $files = @(git diff --cached --name-only)
    Write-Host "Baseline commit (master): $($files.Count) files; top-level folders:"
    $files | ForEach-Object { ($_ -split '/')[0] } | Group-Object | Sort-Object Count -Descending | Format-Table Count, Name -AutoSize | Out-Host
    if ((Read-Host 'Commit this as the Nov 15 baseline on master? (y/n)') -eq 'y') {
        git commit -q -m "Nov 15 2026 IVHM baseline (archive pu-fusion_final_2026-11-15.zip, SHA-256 c81db673...)"
        git checkout -q -b ob4-cad-testbed
        git add -A
        Write-Host 'OB4 commit (branch ob4-cad-testbed):'
        git diff --cached --stat | Out-Host
        $big = git diff --cached --name-only | ForEach-Object { Get-Item $_ -ErrorAction SilentlyContinue } |
            Sort-Object Length -Descending | Select-Object -First 8
        Write-Host 'Largest files in this commit:'; $big | Format-Table @{n='KB';e={[math]::Round($_.Length/1KB)}}, FullName -AutoSize | Out-Host
        if ((Read-Host 'Commit the OB4 work above on ob4-cad-testbed? (y/n)') -eq 'y') {
            git commit -q -F 'scripts\windows\ob4_commit_message.txt'
        } else { Write-Host 'OB4 changes left staged, not committed.' }
        git log --oneline --all --graph | Out-Host
    } else { Write-Host 'Nothing committed. (Repository created; delete .git file and the folder on E: to undo.)' }
}
Write-Host "`nPC run passed its checks; dashboard started; Git step as reported above. Dashboard verification and screenshots are still to be done (tell Claude to continue)." -ForegroundColor Yellow
Read-Host 'Press Enter to close'
