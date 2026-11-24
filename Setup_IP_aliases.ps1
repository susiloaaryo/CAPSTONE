# Run from an elevated PowerShell terminal.
# Adds only missing aliases to the physical Ethernet adapter connected to S1.
# It does not remove/change the adapter's existing IP (for example 192.168.2.10).
$AdapterName = "Ethernet"
$PrefixLength = 24
$RequiredIPs = 2..9 | ForEach-Object { "192.168.250.$_" }

$adapter = Get-NetAdapter -Name $AdapterName -ErrorAction Stop
if ($adapter.Status -ne "Up") {
    Write-Warning "Adapter '$AdapterName' is not Up (Status=$($adapter.Status)). Check the S1 cable before continuing."
}

$existing = Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty IPAddress

foreach ($ip in $RequiredIPs) {
    if ($existing -contains $ip) {
        Write-Host "$ip already exists on $AdapterName - skipped" -ForegroundColor DarkGray
        continue
    }
    New-NetIPAddress -InterfaceAlias $AdapterName -IPAddress $ip -PrefixLength $PrefixLength -AddressFamily IPv4 -ErrorAction Stop | Out-Null
    Write-Host "Added $ip/$PrefixLength to $AdapterName" -ForegroundColor Green
}

Write-Host "`nConfigured IPv4 addresses on $AdapterName:" -ForegroundColor Cyan
Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 |
    Format-Table IPAddress, PrefixLength, AddressState -AutoSize
