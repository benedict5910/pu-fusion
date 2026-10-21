# Paderborn bearing archives from the Zenodo mirror (record 15845309, DOI 10.5281/zenodo.15845309),
# used because groups.uni-paderborn.de is unreachable from our network (curl error 7, 21 Oct 2026).
# Mirror check (21 Oct 2026): all 31 Zenodo archives match the official directory listing size to
# the MiB; KA08 is not on Zenodo. The official site publishes no checksums, so each archive is
# verified against Zenodo's MD5 here, and its contents (file names, 80 .mat files, channel layout)
# are checked after extraction.
#   powershell -ExecutionPolicy Bypass -File pu_download_zenodo.ps1            # 12-bearing starter subset
#   powershell -ExecutionPolicy Bypass -File pu_download_zenodo.ps1 -All       # all 31 archives on Zenodo
param([switch]$All, [string]$Dest = "$env:USERPROFILE\Downloads\paderborn")
$ErrorActionPreference = "Stop"
$starter = "K001 K002 K003 K004 KA04 KA15 KA16 KA22 KI04 KI14 KI16 KI18".Split(" ")
$md5 = @{}
Get-Content (Join-Path $PSScriptRoot "zenodo_15845309_md5.txt") | ForEach-Object {
    $p = $_.Trim().Split(" "); if ($p.Count -eq 3) { $md5[$p[0]] = @{ size = [int64]$p[1]; md5 = $p[2] } }
}
$codes = if ($All) { $md5.Keys | Sort-Object } else { $starter }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$log = Join-Path $Dest "_zenodo_verify.txt"
"started $(Get-Date -Format s)  codes=$($codes -join ',')" | Out-File $log
foreach ($c in $codes) {
    $f = Join-Path $Dest "$c.rar"
    $exp = $md5[$c]
    for ($try = 1; $try -le 3; $try++) {
        if ((Test-Path $f) -and ((Get-Item $f).Length -eq $exp.size)) {
            $h = (Get-FileHash $f -Algorithm MD5).Hash.ToLower()
            if ($h -eq $exp.md5) { break }
            Write-Host "$c MD5 mismatch ($h) - re-downloading"; Remove-Item $f
        }
        Write-Host "[$c] download attempt $try ($([math]::Round($exp.size/1MB)) MiB)"
        & curl.exe --fail --location --retry 5 --retry-delay 5 --continue-at - --progress-bar `
            -o $f "https://zenodo.org/records/15845309/files/$c.rar?download=1"
    }
    $ok = (Test-Path $f) -and ((Get-Item $f).Length -eq $exp.size) -and `
          ((Get-FileHash $f -Algorithm MD5).Hash.ToLower() -eq $exp.md5)
    $line = "$c size=$((Get-Item $f -ErrorAction SilentlyContinue).Length) expected=$($exp.size) md5_ok=$ok"
    Write-Host $line; $line | Out-File $log -Append
}
"finished $(Get-Date -Format s)" | Out-File $log -Append
"DONE" | Out-File (Join-Path $Dest "_done.txt")
Write-Host "`nFinished - results in $log"
