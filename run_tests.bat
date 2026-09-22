@echo off
echo Running Sentinel 210-Test Suite...
cd /d \%~dp0\
myenv\Scripts\python.exe -m pytest edge/tests
pause
