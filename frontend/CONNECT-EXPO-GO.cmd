@echo off
title Bilshenz - Connect Expo Go 52
cd /d "%~dp0"

:: Must run as Administrator (opens Windows firewall for Metro port 8081)
fltmc >nul 2>&1
if errorlevel 1 (
  echo.
  echo ============================================================
  echo   Administrator required - fixes IOException on phone
  echo ============================================================
  echo.
  echo   Click YES on the UAC prompt that appears next...
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)

echo.
echo ============================================================
echo   Bilshenz Expo Go 52 - firewall + Metro
echo ============================================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0scripts\allow-expo-metro-firewall.ps1"
if errorlevel 1 (
  echo Firewall setup failed.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*' -and $_.PrefixOrigin -eq 'Dhcp' } | Select-Object -First 1).IPAddress"`) do set "LAN_IP=%%i"
if not defined LAN_IP set "LAN_IP=192.168.1.154"

set "EXPO_LAN_IP=%LAN_IP%"
set "EXPO_PACKAGER_PINNED=%LAN_IP%"
set "CI=false"

node scripts\make-expo-qr.js
start "" "%~dp0expo-go-qr.html"

echo.
echo ============================================================
echo   ON YOUR PHONE in Expo Go SDK 52:
echo   exp://%LAN_IP%:8081
echo ============================================================
echo   - Wait for "[metro-warm] OK" in this window BEFORE scanning
echo   - Same Wi-Fi as this PC
echo   - Mobile data OFF
echo   - Scan the QR page that opened in your browser
echo   - Do NOT use an old QR from a previous session
echo ============================================================
echo.

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8081" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1

node scripts\run-expo-go.js --lan --clear
pause
