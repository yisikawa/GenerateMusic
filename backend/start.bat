@echo off
cd /d %~dp0..
backend\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8001
