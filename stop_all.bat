@echo off
rem Menghentikan semua program yang dijalankan start_all.bat.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1"
timeout /t 3 >nul
