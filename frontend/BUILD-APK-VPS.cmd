@echo off
REM Build production APK pointing at VPS desk-api (no Expo Go).
REM Run as Administrator. Requires: Node.js, eas-cli login OR Android SDK for local build.
setlocal
cd /d "%~dp0"

set DESK_URL=http://157.245.33.42:8791
set /p DESK_KEY=DESK_API_KEY from VPS /etc/bilshenz.env: 
if "%DESK_KEY%"=="" (
  echo ERROR: DESK_API_KEY required
  exit /b 1
)

echo.
echo Building APK for %DESK_URL%
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0scripts\build-android-release.ps1" ^
  -DeskApiUrl "%DESK_URL%" ^
  -DeskApiKey "%DESK_KEY%" ^
  -UseEasCloud

if errorlevel 1 exit /b 1

echo.
echo Upload to VPS for permanent download link:
echo   scp dist\bilshenz-release-signed.apk root@157.245.33.42:/opt/bilshenz/frontend/dist/bilshenz-release.apk
echo   ssh root@157.245.33.42 "bash /opt/bilshenz/deploy/ubuntu/serve-apk.sh"
echo.
echo Phone install: http://157.245.33.42:8791/download/bilshenz.apk
pause
