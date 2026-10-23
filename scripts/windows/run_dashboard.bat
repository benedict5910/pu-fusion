@echo off
REM One-click dashboard setup + launch.
REM 1) installs Python packages  2) trains the demo model on bearings disjoint from the demo bearings
REM 3) creates the SIMULATED rig model (synthetic sessions)  4) starts the Streamlit dashboard at http://localhost:8501
title IVHM dashboard - leave this window open
cd /d "%~dp0..\.."
where python 1>NUL 2>NUL
if errorlevel 1 (echo Python not found. Install Python 3.10+ from python.org and tick "Add to PATH". & pause & exit /b 1)
python --version
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (echo pip install failed & pause & exit /b 1)
if not exist models\demo_models.pkl python scripts\train_demo_model.py --features data\features_starter.npz --out models\demo_models.pkl
if not exist models\rig_models_simulated.pkl (
  echo Creating the SIMULATED rig model for the "Rig - simulated" mode ^(synthetic sessions, not measured data^)...
  for %%S in (SIM_H1 SIM_H2 SIM_H3) do python scripts\rig_record.py --simulate --session %%S --label healthy --minutes 2
  python scripts\rig_record.py --simulate --session SIM_F1 --label outer_race --minutes 2
  python scripts\rig_record.py --simulate --session SIM_F2 --label unbalance --minutes 2
  python scripts\rig_train.py --fit SIM_H1 --cal SIM_H2 --test-healthy SIM_H3 --test-fault SIM_F1 SIM_F2 --out models\rig_models_simulated.pkl --report results\rig_eval_SIMULATED.json
)
python -m streamlit run app\dashboard.py --server.headless true --server.port 8501
pause
