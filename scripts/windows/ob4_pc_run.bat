@echo off
REM Double-click: OB4 PC run (FreeCAD check, gearbox recordings, CAD build + renders, verification, tests).
REM Commits nothing. Evidence: results\ob4_cad\pc_run_<timestamp>\
title OB4 PC run - leave this window open until it says Done
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ob4_pc_run.ps1"
pause
