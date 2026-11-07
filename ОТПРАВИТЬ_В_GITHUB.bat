@echo off
chcp 65001 >nul
title Отправка коммитов в GitHub (MASKAS)
cd /d "C:\Users\maksi\OneDrive\Documents\GitHub\MASKAS"

echo ===================================================================
echo   Синхронизация с GitHub: https://github.com/fsagf/MASKAS
echo   Отправка готовых коммитов в ветку main...
echo ===================================================================

git push origin main

if errorlevel 1 (
    echo.
    echo [ВНИМАНИЕ] Если требуется авторизация:
    echo Откройте программу GitHub Desktop и нажмите кнопку "Push origin".
    pause
) else (
    echo.
    echo ===================================================================
    echo   [УСПЕХ] Все коммиты успешно опубликованы на GitHub!
    echo ===================================================================
    pause
)
