@echo off
title Bilshenz Binance Bridge API (port 8766)
cd /d "%~dp0\..\backend"
echo.
echo Starting Binance Futures bridge on http://0.0.0.0:8766
echo Phone must use http://YOUR_PC_IP:8766 on same Wi-Fi.
echo.
call npm run binance-api
pause
