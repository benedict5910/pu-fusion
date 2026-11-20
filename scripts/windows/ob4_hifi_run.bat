@echo off
REM Double-click: OB4 high-fidelity CAD/3D upgrade - rebuild, export, verify, test, start dashboard (ob4_hifi_run.ps1)
title OB4 hi-fi run - leave this window open
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ob4_hifi_run.ps1"
timeout /t 15
