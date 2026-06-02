@echo off
title Sapienoids Analytics Portal
echo =========================================
echo   Sapienoids Analytics Portal - Starting
echo =========================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python from https://python.org
    pause
    exit /b 1
)

:: Copy .env.example to .env if .env doesn't exist
if not exist .env (
    copy .env.example .env >nul
    echo Created .env from template. Add your Gemini keys to enable AI features.
)

:: Install / update requirements
echo Checking dependencies...
pip install -r requirements.txt --quiet

echo.
echo Launching app — press Ctrl+C to stop.
echo.

streamlit run D1.py --server.runOnSave=true
pause
