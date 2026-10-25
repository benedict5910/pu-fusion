@echo off
REM Runs the full test suite (incl. dashboard AppTest UI tests) and records versions.
REM Output: results\ui_tests\test_log.txt and results\ui_tests\env.txt
cd /d "%~dp0..\.."
if not exist results\ui_tests mkdir results\ui_tests
python --version > results\ui_tests\env.txt 2>&1
python -m pip show streamlit altair pandas numpy scikit-learn scipy >> results\ui_tests\env.txt 2>&1
python -m unittest discover -s tests -v > results\ui_tests\test_log.txt 2>&1
echo exit code %errorlevel% >> results\ui_tests\test_log.txt
