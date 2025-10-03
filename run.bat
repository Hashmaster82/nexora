@echo off
setlocal

echo ========================================
echo  Nexora — Автообновление и запуск
echo ========================================
echo.

REM Проверяем наличие Git
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/3] Обнаружен Git. Проверяем репозиторий...
    if exist ".git" (
        echo [1/3] Обновление проекта с GitHub...
        git pull origin main 2>nul || git pull origin master 2>nul
        if %errorlevel% equ 0 (
            echo [1/3] Проект успешно обновлён.
        ) else (
            echo [1/3] Не удалось обновить проект. Возможно, нет подключения к интернету или изменения в локальных файлах.
        )
    ) else (
        echo [1/3] Папка не является Git-репозиторием. Пропускаем обновление.
    )
) else (
    echo [1/3] Git не установлен. Пропускаем обновление.
    echo      Установите Git: https://git-scm.com/
)

echo.

REM Проверяем Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Ошибка: Python не найден!
    echo Установите Python 3.7+: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Устанавливаем зависимости
echo [2/3] Установка зависимостей из requirements.txt...
pip install --upgrade -r requirements.txt >nul
if %errorlevel% equ 0 (
    echo [2/3] Зависимости актуальны.
) else (
    echo [2/3] Ошибка при установке зависимостей.
    pause
    exit /b 1
)

echo.

REM Запускаем приложение
echo [3/3] Запуск Nexora...
python app.py
if %errorlevel% neq 0 (
    echo Ошибка при запуске приложения.
    pause
)

endlocal