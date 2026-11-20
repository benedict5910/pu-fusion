@echo off
REM Double-click: commit the verified hi-fi upgrade on ob4-cad-testbed (nothing pushed)
title OB4 hi-fi commit
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ob4_hifi_commit.ps1"
timeout /t 10
