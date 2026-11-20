@echo off
REM Double-click in File Explorer: runs ob4_finish.ps1 in a normal (non-sandboxed) PowerShell.
title OB4 finish - leave this window open
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ob4_finish.ps1"
