@echo off
echo Starting Sentinel Backend API & Command Center...
cd /d " %~dp0\
myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
pause
