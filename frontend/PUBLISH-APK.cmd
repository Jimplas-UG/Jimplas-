@echo off
REM Full APK publish: EAS build with VPS keys, upload, verify download.
setlocal
cd /d "%~dp0"

set VPS=157.245.33.42
set DESK_URL=http://%VPS%:8791

set /p DESK_KEY=Paste DESK_API_KEY from VPS /etc/bilshenz.env: 
if "%DESK_KEY%"=="" exit /b 1

echo.
echo [1/4] Building APK (EAS cloud)...
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\build-android-release.ps1" ^
  -DeskApiUrl "%DESK_URL%" ^
  -DeskApiKey "%DESK_KEY%" ^
  -UseEasCloud
if errorlevel 1 exit /b 1

set APK=
if exist "dist\bilshenz-release-signed.apk" set APK=dist\bilshenz-release-signed.apk
if exist "dist\bilshenz-release.apk" if "%APK%"=="" set APK=dist\bilshenz-release.apk
if "%APK%"=="" (
  echo ERROR: No APK in dist\
  exit /b 1
)

echo.
echo [2/4] Upload APK to VPS...
scp "%APK%" root@%VPS%:/opt/bilshenz/frontend/dist/bilshenz-release.apk
if errorlevel 1 exit /b 1

echo.
echo [3/4] Enable download route on VPS...
ssh root@%VPS% "bash /opt/bilshenz/deploy/ubuntu/serve-apk.sh"
if errorlevel 1 exit /b 1

echo.
echo [4/4] Verify from PC...
powershell -ExecutionPolicy Bypass -File "%~dp0..\deploy\scripts\verify-apk-download.ps1" -Host %VPS%
if errorlevel 1 exit /b 1

echo.
echo INSTALL ON PHONE: %DESK_URL%/download/bilshenz.apk
pause
