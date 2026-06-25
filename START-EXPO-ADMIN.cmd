@echo off
:: Firewall + QR + Metro (Administrator required for firewall)
cd /d "%~dp0frontend"
powershell -ExecutionPolicy Bypass -File .\scripts\elevate-expo-connect.ps1
