@echo off
cd /d "%~dp0"
python demo_seed.py
if errorlevel 1 exit /b 1
start "" "http://127.0.0.1:8765"
python -m uvicorn webapp:app --host 127.0.0.1 --port 8765
