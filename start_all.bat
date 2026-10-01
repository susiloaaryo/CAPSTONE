@echo off
rem Menjalankan seluruh simulator FLISR + dashboard HMI.
rem Tiap program dibuka di jendela cmd sendiri. Tutup jendela = hentikan program itu.

cd /d "%~dp0"

echo [1/4] Menjalankan 7 RTU...
start "RTU GI SATU (8020)" cmd /k python rtu_gi.py 1
start "RTU GD01 (8021)"    cmd /k python rtu_gd.py 1
start "RTU GD02 (8022)"    cmd /k python rtu_gd.py 2
start "RTU GD03 (8023)"    cmd /k python rtu_gd.py 3
start "RTU GD04 (8024)"    cmd /k python rtu_gd.py 4
start "RTU GD05 (8025)"    cmd /k python rtu_gd.py 5
start "RTU GI DUA (8026)"  cmd /k python rtu_gi.py 2

echo [2/4] Menjalankan System Behavior (8027)...
start "System Behavior (8027)" cmd /k python system_behavior.py

echo Menunggu RTU siap...
timeout /t 5 /nobreak >nul

echo [3/4] Menjalankan Controller (503)...
start "Controller (503)" cmd /k python controller.py

timeout /t 3 /nobreak >nul

echo [4/4] Menjalankan Dashboard HMI...
start "Dashboard HMI" cmd /k python -m streamlit run web_hmi.py

echo.
echo Semua program sudah dijalankan. Dashboard: http://localhost:8501
echo Untuk berhenti, tutup jendela-jendela tersebut (atau jalankan stop_all.bat).
timeout /t 5 >nul
