@echo off
setlocal

echo ========================================
echo  Nexora Auto-update and Launch
echo ========================================
echo.

REM Check for Git
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/2] Git detected. Checking repository...
    if exist ".git" (
        echo [1/2] Updating project from GitHub...
        git pull origin main 2>nul || git pull origin master 2>nul
        if %errorlevel% equ 0 (
            echo [1/2] Project successfully updated.
        ) else (
            echo [1/2] Failed to update project. Possible causes: no internet connection or local file changes.
        )
    ) else (
        echo [1/2] This folder is not a Git repository. Skipping update.
    )
) else (
    echo [1/2] Git is not installed. Skipping update.
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

REM Launch the application
echo [2/2] Launching Nexora...
python app.py
if %errorlevel% neq 0 (
    echo Error launching the application.
    pause
)

endlocal