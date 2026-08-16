#!/usr/bin/env bash
# 鸭鸭日记本 一键启动（macOS / Linux）
cd "$(dirname "$0")"
source .venv/bin/activate
exec uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
