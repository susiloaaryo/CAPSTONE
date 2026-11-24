@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo FLISR - 7 RTU TERPISAH / MODBUS TCP
echo ============================================================
echo Y = Controller memakai jalur melalui Saitel HUe.
echo     Controller membaca/menulis ke HUe .250.1:502, Unit ID 1..7.
echo     CHFLISR Unit ID 1..7; downstream RTU Unit ID: 1,2,2,3,4,2,3.
echo     Status FC01 untuk koordinat CoreDb CS; switch command: GI/GD LBS1 CS1=CLOSE, CS2=OPEN,
echo     GD LBS2 CS6=CLOSE, CS7=OPEN. Periksa reset sebelum tes FLISR penuh.
echo N = Controller bicara langsung ke tujuh RTU GI/GD .250.3-.9.
echo     Tetap memakai Modbus TCP; tidak ada model GI/GD in-process.
echo.
echo Dalam KEDUA mode, tujuh proses RTU terpisah tetap dijalankan.
echo.

py -c "import pandas, pymodbus, streamlit" >nul 2>&1
if errorlevel 1 (
  echo Dependencies Python belum lengkap.
  echo Jalankan di folder project: py -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo Pastikan alias IP laptop 192.168.250.2 sampai 192.168.250.9 sudah ada
echo pada Ethernet yang terhubung ke jaringan testbench.
echo Tutup semua sesi FLISR sebelumnya sebelum lanjut.
echo.
choice /C YN /N /M "Lewat gateway Saitel HUe? [Y/N] "
if errorlevel 2 goto MODE_DIRECT
if errorlevel 1 goto MODE_HUE
goto END

:START_FIELD_RTU
echo.
echo [FIELD] Menjalankan tujuh proses RTU GI/GD terpisah di TCP/502...
start "RTU GI SATU 192.168.250.3" /D "%~dp0" cmd /k "py rtu_gi.py 1"
timeout /t 1 /nobreak >nul
start "RTU GI DUA 192.168.250.4" /D "%~dp0" cmd /k "py rtu_gi.py 2"
timeout /t 1 /nobreak >nul
start "RTU GD01 192.168.250.9" /D "%~dp0" cmd /k "py rtu_gd.py 1"
timeout /t 1 /nobreak >nul
start "RTU GD02 192.168.250.5" /D "%~dp0" cmd /k "py rtu_gd.py 2"
timeout /t 1 /nobreak >nul
start "RTU GD03 192.168.250.6" /D "%~dp0" cmd /k "py rtu_gd.py 3"
timeout /t 1 /nobreak >nul
start "RTU GD04 192.168.250.7" /D "%~dp0" cmd /k "py rtu_gd.py 4"
timeout /t 1 /nobreak >nul
start "RTU GD05 192.168.250.8" /D "%~dp0" cmd /k "py rtu_gd.py 5"
echo Menunggu tujuh server RTU selesai start...
timeout /t 5 /nobreak >nul

echo Menjalankan Testbench / fault-case handshake di .250.2:503...
start "FLISR Testbench 192.168.250.2 503" /D "%~dp0" cmd /k "py system_behavior.py"
timeout /t 2 /nobreak >nul
goto :eof

:MODE_HUE
set "FLISR_MODE=Y"
call :START_FIELD_RTU
echo.
echo [MODE Y] Controller melalui HUe 192.168.250.1:502.
echo Pastikan HUe CHFLISR online pada MNT .250.1 dan Unit ID logical 1..7 benar.
echo Pastikan status FC01 dan command source CoreDb CS1/2/6/7 terpetakan.
echo RESET: Command sheet belum punya SOURCE_COORD untuk GI trip / GD HFD reset.
echo FLISR dapat melaporkan SELESAI SEBAGIAN sampai reset source ditambahkan di EBC.
start "FLISR Controller via HUe .250.1 502" /D "%~dp0" cmd /k "py controller_rtu.py"
goto START_HMI

:MODE_DIRECT
set "FLISR_MODE=N"
call :START_FIELD_RTU
echo.
echo [MODE N] Controller langsung ke tujuh endpoint Modbus TCP .250.3-.9.
start "FLISR Controller direct Modbus .250.2 502" /D "%~dp0" cmd /k "py controller.py"
goto START_HMI

:START_HMI
timeout /t 2 /nobreak >nul
start "FLISR Web HMI 192.168.250.2 8501" /D "%~dp0" cmd /k "py -m streamlit run web_hmi.py"
echo.
echo Semua proses startup sudah diminta.
echo Controller status / HMI PLC endpoint: 192.168.250.2:502
echo Testbench endpoint: 192.168.250.2:503
echo Web HMI: http://192.168.250.2:8501
echo Mode Y juga memerlukan HUe di 192.168.250.1:502.
echo.
pause
goto END

:END
endlocal
