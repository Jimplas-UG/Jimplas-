@echo off
title Bilshenz Expo Go 52
cd /d "%~dp0frontend"

echo.
echo === Bilshenz Expo Go SDK 52 ===
echo.
echo 1) Right-click START-EXPO-ADMIN.cmd and Run as administrator (firewall + QR)
echo    OR in Admin PowerShell: npm run connect:phone
echo.
echo 2) Keep this window open — Metro must stay running.
echo.

set CI=false
set EXPO_FORCE_TUNNEL=
set EXPO_OFFLINE=
node scripts/run-expo-go.js --lan --clear
pause
