@echo off
title Sentinel - Gujarat Police Surveillance System Launcher
cls
echo ==============================================================================
echo        SENTINEL - GUJARAT POLICE SURVEILLANCE COMMAND CENTER
echo ==============================================================================
echo.
echo Select an execution mode:
echo.
echo   [1] Launch Complete System (Backend API + Command Center Web UI + Edge AI)
echo   [2] Launch Backend API and Open Web Dashboard only
echo   [3] Launch Edge AI Vision Pipeline only
echo   [4] Run Full Test Suite (210 Tests)
echo   [5] Exit
echo.
set /p opt="Enter choice [1-5] (default is 1): "
if "%opt%"=="" set opt=1

if "%opt%"=="1" goto launch_all
if "%opt%"=="2" goto launch_backend
if "%opt%"=="3" goto launch_edge
if "%opt%"=="4" goto launch_tests
if "%opt%"=="5" exit /b 0

:launch_all
echo.
echo [+] Starting Sentinel Backend Server in background window...
start "Sentinel Backend API" cmd /k "cd /d %~dp0 && myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul
echo [+] Opening Command Center in your default web browser...
start http://localhost:8000/dashboard/
echo [+] Starting Edge AI Perception Engine in separate window...
start "Sentinel Edge AI" cmd /k "cd /d %~dp0edge && ..\myenv\Scripts\python.exe sentinel_edge/main.py"
echo.
echo System started successfully!
pause
exit /b 0

:launch_backend
echo.
echo [+] Starting Sentinel Backend Server...
start "Sentinel Backend API" cmd /k "cd /d %~dp0 && myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul
start http://localhost:8000/dashboard/
exit /b 0

:launch_edge
echo.
echo [+] Starting Sentinel Edge AI Perception Engine...
cd /d "%~dp0edge"
..\myenv\Scripts\python.exe sentinel_edge/main.py
pause
exit /b 0

:launch_tests
echo.
echo [+] Running 210-test automated verification suite...
cd /d "%~dp0"
myenv\Scripts\python.exe -m pytest edge/tests
pause
exit /b 0
