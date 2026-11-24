# PLC2 integration — Schneider Modicon TM221CE16T

## Network and role
- Proposed IP: `192.168.250.12/24` (verify unused before assigning).
- Controller Modbus TCP server: `192.168.250.2:502`, Unit ID `1`.
- PLC2 is a Modbus TCP client. It reads the last six HFD points from the Controller; it does not poll the RTUs directly.

## Required status mapping
The TM221CE16T has 7 transistor PNP/source outputs rated 24 VDC, 0.5 A per output. Use six for HFD status indicators and leave one spare. Verify load current, common current, power supply and interface circuit limits before wiring.

| PLC memory | Output | Equipment | Controller DI offset | ModScan address |
|---|---|---|---:|---:|
| `%M0` | `%Q0.0` | GD03_HFD1 | 30 | 10031 |
| `%M1` | `%Q0.1` | GD03_HFD2 | 31 | 10032 |
| `%M2` | `%Q0.2` | GD04_HFD1 | 32 | 10033 |
| `%M3` | `%Q0.3` | GD04_HFD2 | 33 | 10034 |
| `%M4` | `%Q0.4` | GD05_HFD1 | 34 | 10035 |
| `%M5` | `%Q0.5` | GD05_HFD2 | 35 | 10036 |

## Modbus read range
- FC02, offset `30`, quantity `6` (Controller DI30..DI35; ModScan addresses 10031..10036).
- Map returned bits to `%M0..%M5`, then to `%Q0.0..%Q0.5` as in `PLC2_TM221CE16T_Ladder_Logic.txt`.
- Leave `%Q0.6` unused. Confirm `READ_VAR` receive-buffer bit packing with the installed Machine Expert - Basic version before commissioning.

## Electrical and operating boundary
- In the current simulator map, HFD = 1 means active/true, so the respective indicator output turns ON. Confirm this intended polarity before wiring real indicator circuits.
- Outputs are 24 VDC transistor PNP/source outputs, not dry relay contacts. Do not connect them directly to relay-only inputs or external circuits unless voltage, common reference and current are compatible.
- HFD status indications are not safety-rated protection or switching commands.
