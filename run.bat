@echo off
setlocal

echo ========================================
echo  Nexora Auto-update and Launch
echo ========================================
echo.

REM Check for Git
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/3] Git detected. Checking repository...
    if exist ".git" (
        echo [1/3] Updating project from GitHub...
        git pull origin main 2>nul || git pull origin master 2>nul
        if %errorlevel% equ 0 (
            echo [1/3] Project successfully updated.
        ) else (
            echo [1/3] Failed to update project. Possible causes: no internet connection or local file changes.
        )
    ) else (
        echo [1/3] This folder is not a Git repository. Skipping update.
    )
) else (
    echo [1/3] Git is not installed. Skipping update.
    echo      Please install Git: https://git-scm.com/
)

echo.

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found!
    echo Please install Python 3.7 or newer: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Install dependencies
echo [2/3] Installing dependencies from requirements.txt...
pip install --upgrade -r requirements.txt >nul
if %errorlevel% equ 0 (
    echo [2/3] Dependencies are up to date.
) else (
    echo [2/3] Error installing dependencies.
    pause
    exit /b 1
)

echo.

REM Launch the application
echo [3/3] Launching Nexora...
python app.py
if %errorlevel% neq 0 (
    echo Error launching the application.
    pause
)

endlocal