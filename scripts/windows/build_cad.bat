@echo off
REM OB4 CAD: build the editable FreeCAD model + STEP exports, then the dimensioned drawings.
REM Output: cad\out\ (FCStd, STEP, STL, freecad_report.json, drawings\*.pdf/png, sensor_map.json)
cd /d "%~dp0..\.."
if not exist cad\out mkdir cad\out
set FCCMD=
for %%P in ("C:\Program Files\FreeCAD 1.0\bin\freecadcmd.exe" "C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" "%LOCALAPPDATA%\Programs\FreeCAD 1.0\bin\freecadcmd.exe") do if exist %%P set FCCMD=%%P
if not defined FCCMD (
  echo FreeCAD not found. Install FreeCAD 1.0 or set FCCMD to freecadcmd.exe, then re-run.
  echo Drawings are still generated from the parameter model.
) else (
  echo Using %FCCMD%
  %FCCMD% --version > cad\out\freecad_version.txt 2>&1
  set IVHM_ROOT=%CD%
  %FCCMD% cad\build_freecad.py > cad\out\build_log.txt 2>&1
  type cad\out\build_log.txt
)
python cad\make_drawings.py
pause
