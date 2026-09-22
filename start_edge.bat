@echo off
echo Starting Sentinel Edge AI Perception Engine...
cd /d \%~dp0\edge\
..\myenv\Scripts\python.exe sentinel_edge/main.py
pause
