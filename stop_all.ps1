# Menghentikan semua program FLISR berdasarkan port yang dipakai,
# lalu menutup jendela cmd induknya (yang dibuka oleh start_all.bat).

$ports = 503, 8020, 8021, 8022, 8023, 8024, 8025, 8026, 8027, 8501

$pids = Get-NetTCPConnection -State Listen -LocalPort $ports -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

if (-not $pids) {
    Write-Host "Tidak ada program FLISR yang sedang berjalan."
    exit
}

foreach ($procId in $pids) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
    $parent = if ($proc) { Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" } else { $null }

    Write-Host "Stop PID $procId ($($proc.Name))"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue

    # Tutup jendela cmd yang membuka program ini
    if ($parent -and $parent.Name -eq "cmd.exe") {
        Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Semua program FLISR dihentikan."
