@echo off
echo Установка зависимостей для Nexora...
echo.

REM Проверяем, установлен ли Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Ошибка: Python не найден. Убедитесь, что Python установлен и добавлен в PATH.
    echo Скачать Python: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Устанавливаем зависимости из requirements.txt
echo Установка зависимостей из requirements.txt...
pip install -r requirements.txt

if %errorlevel% equ 0 (
    echo.
    echo Зависимости успешно установлены!
    echo Теперь вы можете запустить Nexora командой: python nexora.py
) else (
    echo.
    echo Ошибка при установке зависимостей.
    echo Убедитесь, что pip обновлён: pip install --upgrade pip
)

echo.
pause