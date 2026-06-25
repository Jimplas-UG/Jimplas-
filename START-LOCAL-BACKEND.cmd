@echo off
title Bilshenz Local Backend
cd /d "%~dp0"

echo.
echo === Starting desk-api (8791) + Binance bridge (8766) ===
echo Keep this window open while using the app.
echo.

start "Bilshenz desk-api" cmd /k "cd /d "%~dp0backend" && set DESK_API_KEY=dev&& set AUTH_JWT_SECRET=dev-jwt-secret-min-32-chars-long!!&& set AUTH_DEV_OTP=1&& npm run desk-api"
timeout /t 3 /nobreak >nul
start "Bilshenz Binance bridge" cmd /k "cd /d "%~dp0binance_trading_system\python" && powershell -NoProfile -ExecutionPolicy Bypass -File .\start-api.ps1"

echo.
echo Started two windows. Then run the web app:
echo   cd frontend
echo   npm run web
echo.
pause
