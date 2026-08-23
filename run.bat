@echo off
rem 鸭鸭日记本 一键启动（Windows）
cd /d %~dp0
call .venv\Scripts\activate.bat
uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
