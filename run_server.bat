@echo off
chcp 65001 >nul
title Trading Journal Pro — Локальный Сервер
cd /d "%~dp0"

echo ===================================================================
echo   Инициализация сборки локального сервера Trading Journal Pro...
echo ===================================================================

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" run_local_server.py
) else (
    python run_local_server.py
)

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сервер завершил работу с ошибкой.
    pause
)

