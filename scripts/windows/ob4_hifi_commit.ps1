# Commit the verified high-fidelity upgrade on branch ob4-cad-testbed. Non-interactive; nothing is pushed.
# Refuses unless: on ob4-cad-testbed, the newest hi-fi run log says DONE exit=0 with ALL PASSED, and no frozen
# path (models/, data/, results/ except results/ob4_cad/) changed. Log: results\ob4_cad\hifi_commit_<timestamp>.txt
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Transcript -Path (Join-Path $Root "results\ob4_cad\hifi_commit_$Stamp.txt") | Out-Null
function Done($c, $m) { Write-Host $m; Write-Host "RESULT: $c"; try { Stop-Transcript | Out-Null } catch {}; exit $c }
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'ob4-cad-testbed') { Done 2 "STOP: on branch '$branch', expected ob4-cad-testbed" }
$log = Get-ChildItem (Join-Path $Root 'results\ob4_cad') -Filter 'hifi_2*.txt' | Sort-Object Name | Select-Object -Last 1
$txt = Get-Content $log.FullName -Raw
if ($txt -notmatch 'result: ALL PASSED' -or $txt -notmatch 'DONE exit=0') { Done 3 "STOP: newest run $($log.Name) did not pass" }
Write-Host "verified by: $($log.Name)"
$frozen = @(git status --porcelain -- models data results | Where-Object { $_ -notmatch 'results/ob4_cad/' })
if ($frozen.Count) { $frozen | Out-Host; Done 4 'STOP: frozen paths changed' }
git add -A
git diff --cached --stat | Out-Host
git commit -q -F 'scripts\windows\ob4_hifi_commit_message.txt'
if ($LASTEXITCODE -ne 0) { Done 5 'STOP: commit failed' }
git log --oneline --all --graph | Out-Host
git status --short | Out-Host
Done 0 'OK: committed on ob4-cad-testbed. Nothing pushed.'
