@echo off
REM OB4: convert the verified STEP export (cad\out\ivhm_drivetrain.step) into cad\out\ivhm_drivetrain.glb
REM for the dashboard's 3D viewer. Report: cad\out\glb_export_report.json  Log: cad\out\glb_export_log.txt
cd /d "%~dp0..\.."
set FCCMD=
for %%P in ("E:\freecad\bin\freecadcmd.exe" "C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" "C:\Program Files\FreeCAD 1.0\bin\freecadcmd.exe" "%LOCALAPPDATA%\Programs\FreeCAD 1.1\bin\freecadcmd.exe") do if not defined FCCMD if exist %%P set FCCMD=%%P
if not defined FCCMD (
  echo freecadcmd.exe not found - set FCCMD to its full path and re-run.
  pause
  exit /b 1
)
echo Using %FCCMD%
set IVHM_ROOT=%CD%
%FCCMD% cad\export_glb.py > cad\out\glb_export_log.txt 2>&1
set RC=%ERRORLEVEL%
type cad\out\glb_export_log.txt
echo.
if exist cad\out\glb_export_report.json (echo Report: cad\out\glb_export_report.json) else (echo NO REPORT WRITTEN - see the log above)
echo freecadcmd exit code %RC%
pause
