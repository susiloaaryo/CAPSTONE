# PLC1 integration — Schneider Modicon TM221CE40R

## Network and role
- Proposed IP: `192.168.250.11/24` (verify unused before assigning).
- Controller Modbus TCP server: `192.168.250.2:502`, Unit ID `1`.
- PLC1 is a Modbus TCP client and reads status points; it is not programmed by the Python simulator.

## Required status mapping
PLC1 uses 16 relay outputs: 12 switch-position indicators and 4 HFD indicators.

| PLC memory | Output | Equipment | Controller DI offset | ModScan address |
|---|---|---|---:|---:|
| `%M0` | `%Q0.0` | GD01_LBS1 | 88 | 10089 |
| `%M1` | `%Q0.1` | GD01_LBS2 | 89 | 10090 |
| `%M2` | `%Q0.2` | GD02_LBS1 | 90 | 10091 |
| `%M3` | `%Q0.3` | GD02_LBS2 | 91 | 10092 |
| `%M4` | `%Q0.4` | GD03_LBS1 | 92 | 10093 |
| `%M5` | `%Q0.5` | GD03_LBS2 | 93 | 10094 |
| `%M6` | `%Q0.6` | GD04_LBS1 | 94 | 10095 |
| `%M7` | `%Q0.7` | GD04_LBS2 | 95 | 10096 |
| `%M8` | `%Q0.8` | GD05_LBS1 | 96 | 10097 |
| `%M9` | `%Q0.9` | GD05_LBS2 | 97 | 10098 |
| `%M10` | `%Q0.10` | GI_SATU_CB | 98 | 10099 |
| `%M11` | `%Q0.11` | GI_DUA_CB | 99 | 10100 |
| `%M12` | `%Q0.12` | GD01_HFD1 | 26 | 10027 |
| `%M13` | `%Q0.13` | GD01_HFD2 | 27 | 10028 |
| `%M14` | `%Q0.14` | GD02_HFD1 | 28 | 10029 |
| `%M15` | `%Q0.15` | GD02_HFD2 | 29 | 10030 |

## Modbus read ranges
1. FC02, offset `88`, quantity `12` for the CB/LBS aliases (DI88..DI99).
2. FC02, offset `26`, quantity `4` for GD01/GD02 HFD1/HFD2 (DI26..DI29).
3. Map returned bits to `%M0..%M11` for switches and `%M12..%M15` for HFDs as in `PLC1_TM221CE40R_Ladder_Logic.txt`. Confirm `READ_VAR` receive-buffer bit packing with the installed Machine Expert - Basic version before commissioning.

## Electrical and operating boundary
- CB/LBS outputs are **indication only**. A switch output is ON only when CLOSE is confirmed and the owning RTU is online; OFF can mean OPEN, unknown/transit, or RTU offline.
- HFD outputs show the simulator's existing HFD status bit (1 = active/true).
- Do not wire these outputs directly to live switching coils. Use an approved interface and reviewed protection/interlocking design.
