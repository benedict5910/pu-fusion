@echo off
REM Integrated IVHM dashboard (bearings + gearbox) on http://localhost:8520
REM Uses the Python environment already on this PC (no installs). data\mcc5 must hold the 12 MCC5-THU files;
REM setup_integration.bat links it to the existing verified copy (directory junction: nothing is copied or changed).
title IVHM integrated dashboard - leave this window open
cd /d "%~dp0..\.."
python -c "import streamlit, altair" 1>NUL 2>NUL
if errorlevel 1 (echo Streamlit/Altair not found in this Python. Run scripts\windows\run_dashboard.bat once. & pause & exit /b 1)
if not exist data\mcc5 echo WARNING: data\mcc5 missing - the gearbox view will show "unavailable".
python -m streamlit run app\dashboard.py --server.headless true --server.port 8520
pause
