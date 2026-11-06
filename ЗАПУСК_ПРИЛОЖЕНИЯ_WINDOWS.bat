@echo off
chcp 65001 >nul
title Trading Journal Pro — Нативное приложение Windows
cd /d "%~dp0"

echo ===================================================================
echo   Запуск Trading Journal Pro (Нативное окно Windows)...
echo   (0 секунд задержки, открывается мгновенно без браузера)
echo ===================================================================

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" main.py
) else (
    python main.py
)

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Приложение завершило работу с ошибкой.
    pause
)
