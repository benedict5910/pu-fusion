@echo off
REM One-click dashboard setup + launch.
REM 1) installs Python packages  2) trains the demo model on bearings disjoint from the demo bearings
REM 3) starts the Streamlit dashboard at http://localhost:8501
title IVHM dashboard - leave this window open
cd /d "%~dp0..\.."
where python 1>NUL 2>NUL
if errorlevel 1 (echo Python not found. Install Python 3.10+ from python.org and tick "Add to PATH". & pause & exit /b 1)
python --version
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (echo pip install failed & pause & exit /b 1)
if not exist models\demo_models.pkl python scripts\train_demo_model.py --features data\features_starter.npz --out models\demo_models.pkl
python -m streamlit run app\dashboard.py --server.headless true --server.port 8501
pause
