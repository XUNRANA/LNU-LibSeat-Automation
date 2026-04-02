@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ===================================================
    echo [ERROR] Python not found!
    echo Please install Python 3.8+ from https://www.python.org/
    echo Make sure to check "Add python.exe to PATH"
    echo ===================================================
    pause
    exit /b
)

:: Setup venv if not exists
if not exist ".venv\Scripts\activate.bat" (
    echo ===================================================
    echo [INFO] First run - setting up virtual environment...
    echo ===================================================
    python -m venv .venv

    call .\.venv\Scripts\activate.bat

    echo.
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

    echo.
    echo ===================================================
    echo [OK] Environment ready!
    echo ===================================================
    timeout /t 2 >nul
) else (
    call .\.venv\Scripts\activate.bat
)

echo.
echo ===================================================
echo   LNU-LibSeat-Automation Starting (GUI)...
echo ===================================================
python gui.py

echo.
pause
