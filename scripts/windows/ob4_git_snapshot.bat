@echo off
REM Double-click: Git snapshot of the verified OB4 state before the high-fidelity upgrade (see ob4_git_snapshot.ps1).
title OB4 git snapshot
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ob4_git_snapshot.ps1"
timeout /t 8
