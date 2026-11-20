@echo off
REM OB4 acceptance: regression replay vs Nov 15 evidence, session equivalence, fallback/abstention, CAD checks,
REM then the full unit-test suite (incl. real-Streamlit AppTests). Writes a NEW folder under results\ob4_cad\.
cd /d "%~dp0..\.."
if not exist results\ob4_cad mkdir results\ob4_cad
python scripts\verify_ob4.py
set STAMP=%DATE:~-4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%
set STAMP=%STAMP: =0%
python --version > results\ob4_cad\unittest_%STAMP%.log 2>&1
python -m pip show streamlit altair pandas numpy scikit-learn >> results\ob4_cad\unittest_%STAMP%.log 2>&1
python -m unittest discover -s tests -v >> results\ob4_cad\unittest_%STAMP%.log 2>&1
echo exit code %errorlevel% >> results\ob4_cad\unittest_%STAMP%.log
findstr /C:"Ran " /C:"OK" /C:"FAILED" results\ob4_cad\unittest_%STAMP%.log
pause
