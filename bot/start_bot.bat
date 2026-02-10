@echo off
title NunuIRL Trading Bot
cd /d "%~dp0"

echo ============================================================
echo  NunuIRL Bot - Auto-Restart Launcher
echo  Press CTRL+C twice to stop completely
echo ============================================================
echo.

:loop
echo [%date% %time%] Starting bot...
python run.py paper

echo.
echo [%date% %time%] Bot stopped (exit code: %ERRORLEVEL%)
echo Restarting in 10 seconds... Press CTRL+C to stop.
timeout /t 10 /nobreak >nul
goto loop
