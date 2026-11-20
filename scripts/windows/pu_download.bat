@echo off
REM Paderborn starter subset (12 archives, ~1.9 GB) from the Zenodo mirror with MD5 verification.
REM   pu_download.bat        starter subset
REM   pu_download.bat all    all 31 archives available on Zenodo (KA08 only on the official site)
title Paderborn download (Zenodo) - leave this window open
if /I "%1"=="all" (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pu_download_zenodo.ps1" -All) else (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pu_download_zenodo.ps1")
pause
