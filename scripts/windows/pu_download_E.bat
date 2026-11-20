@echo off
REM Downloads all 31 Paderborn archives from the Zenodo mirror to E:\ivhm-data\paderborn (MD5-verified).
REM Safe to re-run: verified archives are skipped, partial ones resume.
title Paderborn download to E: - leave this window open
if not exist E:\ (echo Drive E: not found & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pu_download_zenodo.ps1" -All -Dest "E:\ivhm-data\paderborn"
pause
