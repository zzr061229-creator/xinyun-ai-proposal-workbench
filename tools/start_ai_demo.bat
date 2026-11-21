@echo off
rem Start the local ATLAS demo with the committee model proxy.
rem Requires: python on PATH, config.local.json with ai.* (gitignored).
cd /d "%~dp0.."
start "ATLAS AI Proxy" python -I tools\brief_proxy.py --port 8791
start "ATLAS Web" python -m http.server 8788
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8788/src/index-atlas.html?ai=1"
