@echo off
title Bilshenz Expo Go - REQUIRED for phone connection
cd /d "%~dp0"
echo.
echo ============================================================
echo  FIXES: IOException / Failed to download remote update
echo ============================================================
echo.
echo  1. This window MUST run as Administrator (right-click - Run as admin)
echo  2. Click YES on the UAC prompt
echo  3. Scan the QR that opens in your browser
echo  4. Phone: same Wi-Fi as PC, mobile data OFF, Expo Go SDK 52
echo.
echo ============================================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\elevate-expo-connect.ps1"
pause
