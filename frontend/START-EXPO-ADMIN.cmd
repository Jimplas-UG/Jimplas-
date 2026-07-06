@echo off
title Bilshenz Expo Go - Admin setup
cd /d "%~dp0"
echo.
echo Opening firewall + Metro + fresh QR (Administrator required)...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\elevate-expo-connect.ps1"
pause
