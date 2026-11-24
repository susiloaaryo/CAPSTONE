# FLISR Simulator — One Laptop + Saitel HUe + Two Schneider M221 PLCs

This package runs the seven virtual RTUs, the FLISR Controller, System Behavior/testbench and Streamlit HMI on one Windows laptop. The Controller exposes a shared Modbus TCP status/test endpoint for HMI and diagnostics. In the current physical topology, PLC1 and PLC2 connect through HUe LAN1/LAN2; use the live HUe mapping rather than assuming the PLCs can route directly to the laptop endpoint.

## 1. Network map

### Laptop: physical Ethernet connected to S1

| IP address | Service | Port |
|---|---|---:|
| `192.168.250.2` | Controller Modbus TCP server | `502` |
| `192.168.250.2` | System Behavior/testbench | `503` |
| `192.168.250.2` | Streamlit HMI | `8501` |
| `192.168.250.3` | GI SATU RTU simulator | `502` |
| `192.168.250.4` | GI DUA RTU simulator | `502` |
| `192.168.250.5` | GD02 RTU simulator | `502` |
| `192.168.250.6` | GD03 RTU simulator | `502` |
| `192.168.250.7` | GD04 RTU simulator | `502` |
| `192.168.250.8` | GD05 RTU simulator | `502` |
| `192.168.250.9` | GD01 RTU simulator | `502` |

### Physical devices on switch S1

| Device | Proposed IP | Role |
|---|---|---|
| Schneider Saitel DR HUe MNT | `192.168.250.1/24` | CHFLISR Modbus TCP server for controller mode Y; HUe master polls GI/GD RTUs |
| PLC1 Schneider TM221CE40R | `192.168.251.11/24` | Connected on HUe LAN1 (`192.168.251.10`) |
| PLC2 Schneider TM221CE16T | `192.168.252.11/24` | Connected on HUe LAN2 (`192.168.252.10`) |

HUe MNT `.250.1` reflects the current network value discussed in the setup; confirm it against the live Easergy Builder project before using mode Y. Laptop aliases `.2..9` must be assigned to the physical Ethernet adapter connected to S1, not the Microsoft loopback adapter. PLC1 and PLC2 are on HUe LAN1/LAN2 in the current installation, so their IPs are not assumed to be `.250.11` and `.250.12`. Do not remove existing maintenance IPs until access to HUe is understood.

## 2. System architecture and controller mode

`START_SIMULATOR.bat` asks whether the Controller should read GI/GD state from RTU endpoints over Modbus TCP.

- **N — direct Modbus mode:** the launcher starts seven separate GI/GD RTU processes and runs `controller.py`. The controller reads/writes the seven endpoint IPs `.3`–`.9` directly over Modbus TCP.
- **Y — HUe gateway mode:** the launcher starts the same seven GI/GD RTU processes, then runs `controller_rtu.py`. The controller connects to the HUe `CHFLISR` server at `192.168.250.1:502` and uses logical Unit IDs 1..7. HUe polls the RTUs using the downstream MDBM Unit IDs `1,2,2,3,4,2,3` in node order GIA, GD01..GD05, GIB. Both modes keep GI/GD as separate Modbus TCP processes.

In both modes, the Controller serves its local aggregated status map at `192.168.250.2:502`, the testbench is at `192.168.250.2:503`, and the Streamlit HMI is at `http://192.168.250.2:8501`. The physical PLCs in the current installation are on HUe LAN1/LAN2 (`192.168.251.10` / `192.168.252.10` server side); their live Modbus target and point map must match the active HUe configuration. This package does not download or program physical PLC projects.

## 3. Data path and command ownership

All seven GI/GD RTUs remain separate Python processes, each with its own IP and Modbus TCP port 502. Both Controller modes use Modbus TCP:

- **Mode N:** `controller.py` is a direct Modbus TCP client to `.3`–`.9`, Unit ID 1. It reads field status with FC01 and writes simulator-only command registers CO10/CO11/CO12.
- **Mode Y:** `controller_rtu.py` is a Modbus TCP client to the HUe CHFLISR server at `.250.1:502` with logical Unit IDs 1–7. HUe polls the seven field RTUs using downstream Unit IDs `1,2,2,3,4,2,3`. The supplied CoreDb already contains momentary source/destination mappings for switch commands: GI CS1/2, GD LBS1 CS1/2, GD LBS2 CS6/7. See `EBC_CS_MAPPING.md` for the reset limitation.
- **Testbench:** writes fault-injection holding registers directly to the seven simulator RTUs. Its local service endpoint is `.250.2:503`; it does not own switching coils.
- **HMI and test tools:** use the controller's aggregated server at `.250.2:502`. Physical PLCs use the configured HUe LAN1/LAN2 Modbus Server if that is the active deployment architecture; do not assume the PLC networks can route directly to `.250.2`.

Mode Y field status uses the CS image (GI 0..5, GD 0..9) from HUe Unit IDs 1–7. The supplied CoreDb workbook maps these points as `CS` coordinates; the Easergy Modbus Slave STD profile reads CS with FC01 (FC02 is for IS coordinates), so Mode Y uses FC01 only. The TCP client is recreated after a no-response timeout so one failed Unit ID does not poison later reads. Switch writes are FC05 pulses to the CoreDb source points above. Reset is incomplete in the supplied EBC: GD HFD reset entries have destination-only coordinates and GI trip reset has no Command row. Add and download reset source mappings in Easergy Builder before expecting full FLISR recovery. The ZIP defaults `HUE_RESET_SOURCE_MAP_AVAILABLE = False` and will not write to proposed/unconfigured reset addresses; set it to `True` only after those mappings are present and verified. Preserve selector checks, local interlocks, and feedback verification. The HUe's MNT address `.250.1` is on the lab subnet; the HUe's LAN1/LAN2 addresses for PLCs may be different subnets.

Run `py validate_multi_master.py` after the seven RTUs are started to check FC01 reads using Unit ID 1 and each exact downstream MDBM Unit ID. This does not emulate the live HUe.

## 4. Cable-fault HFD patterns

The testbench cases 1–6 follow the requested cable table. For a station marked `1 & 2`, both HFD1 (GD HR0) and HFD2 (GD HR1) are injected and latched.

| Cable case | GD01 | GD02 | GD03 | GD04 | GD05 | Trip source | Expected localization |
|---:|---|---|---|---|---|---|---|
| 1 | — | — | — | — | — | GI SATU | Cable 1 |
| 2 | 1 & 2 | — | — | — | — | GI SATU | Cable 2 |
| 3 | 1 & 2 | 1 & 2 | — | — | — | GI SATU | Cable 3 |
| 4 | — | — | — | 1 & 2 | 1 & 2 | GI DUA | Cable 4 |
| 5 | — | — | — | — | 1 & 2 | GI DUA | Cable 5 |
| 6 | — | — | — | — | — | GI DUA | Cable 6 |

Run `py validate_hfd_cases.py` to check that the case injection definition and localization result agree with this table.

## 5. Status allocation

| PLC | Model | Output assignment |
|---|---|---|
| PLC1 | TM221CE40R, 16 relay outputs | 12 CB/LBS + 4 HFD |
| PLC2 | TM221CE16T, 7 PNP transistor outputs | 6 HFD + 1 spare |
| **Total** | | **22 status outputs used** |

### PLC1 output summary

- `%Q0.0..%Q0.9`: 10 LBS indicators, GD01..GD05 LBS1/LBS2.
- `%Q0.10`: GI SATU CB indicator.
- `%Q0.11`: GI DUA CB indicator.
- `%Q0.12..%Q0.15`: GD01 HFD1/HFD2 and GD02 HFD1/HFD2.

### PLC2 output summary

- `%Q0.0..%Q0.5`: GD03 HFD1/HFD2, GD04 HFD1/HFD2, GD05 HFD1/HFD2.
- `%Q0.6`: spare.

Use `PLC1_TM221CE40R_Ladder_Mapping.csv` and `PLC2_TM221CE16T_Ladder_Mapping.csv` for the separate maps, or `PLC_M221_Ladder_Mapping.csv` for the combined 22-point map. The formatted reference is `FLISR_Modbus_Mapping_Dual_PLC.docx`.

## 6. Controller Modbus map

- Controller endpoint: `192.168.250.2:502`, Unit ID 1.
- Function Code 02: Read Discrete Inputs.
- Controller data block contains `DI0..DI99` (100 bits).
- `DI0..DI87` retain the existing meanings.
- `DI26..DI35`: HFD1/HFD2 for GD01..GD05, in order.
- `DI88..DI99`: 12 PLC-order switch-closed aliases in order GD01..GD05 LBS1/LBS2, then GI SATU CB and GI DUA CB.
- ModScan display address = zero-based DI offset + 10001; examples: DI26 = 10027, DI30 = 10031, DI88 = 10089, DI99 = 10100.

### Suggested read ranges

| PLC | FC02 offset | Quantity | Signals |
|---|---:|---:|---|
| PLC1 | 88 | 12 | CB/LBS closed aliases |
| PLC1 | 26 | 4 | GD01 and GD02 HFD |
| PLC2 | 30 | 6 | GD03–GD05 HFD |

M221 client configuration must map the returned buffer bits into local memory bits `%M` using the correct packing for the installed EcoStruxure Machine Expert - Basic version. Validate one known point before assigning all outputs. Schneider documents M221 `READ_VAR` for `%I` objects with quantity 0..127; verify this against the installed version and configuration: https://www.se.com/us/en/faqs/FA241658/

See `HUe_Controller_DI_Mapping.csv` for the full Controller map and `PLC_M221_Integration_Guide.md` for combined setup guidance.

## 7. Electrical and state interpretation

- CB/LBS output ON = CLOSE confirmed while the owning RTU is online. OFF may mean OPEN, unknown/transit, or RTU offline; use validity and online status points for diagnosis.
- HFD output ON = the existing Controller HFD bit is 1 (active/true in this simulator map). Confirm polarity before physical wiring.
- TM221CE40R has 16 relay outputs. TM221CE16T has 7 24 VDC PNP/source transistor outputs rated 0.5 A per point; transistor outputs are not dry relay contacts. Check output/common limits, load and input compatibility before wiring.
- These are indication outputs only; do not wire directly to live CB/LBS operating coils. A real control circuit requires reviewed interlocks, Local/Remote logic, feedback verification, protective interface and approved electrical design.

## 8. Laptop IP aliases

Run `Setup_IP_aliases.ps1` as Administrator after checking the adapter name. It adds missing addresses `.2..9/24` to the physical `Ethernet` adapter. Confirm with:

```powershell
Get-NetIPAddress -InterfaceAlias "Ethernet" -AddressFamily IPv4 | Format-Table IPAddress, PrefixLength
```

Do not assign the PLCs' `.11` or `.12` addresses to the laptop. Do not expose the testbench port 503 outside the isolated lab network.

## 9. Startup and validation

Install dependencies in this folder with `py -m pip install -r requirements.txt`, configure Ethernet aliases `.2`–`.9` on the physical Ethernet NIC, and run `START_SIMULATOR.bat`.

Choose one mode:

1. **Y (via HUe):** the batch file starts GI SATU, GI DUA, GD01–GD05 as seven separate RTU processes, then `system_behavior.py`, `controller_rtu.py`, and the HMI. `controller_rtu.py` uses HUe .250.1:502 with Unit IDs 1..7.
2. **N (direct Modbus TCP to RTUs):** the same seven separate RTU processes and `system_behavior.py` are started, but the controller is `controller.py`, which communicates directly with .3–.9 over Modbus TCP. The HMI stays at .2:8501.

The two modes use the same HMI, testbench registers and controller status map. Physical PLCs and the HUe can only reach the host aliases if IP addresses, routing, firewall and the actual Ethernet interface are configured correctly.

## 10. Fault-case transaction and HFD verification

The System Behavior testbench uses HR0=case, HR1=mode, HR2=repair, HR3=trigger sequence, HR4=applied sequence acknowledgement, and HR5=status. Each HMI fault-button click increments the trigger sequence so a repeated K button is also processed. The testbench freezes CSV, temporarily pauses the Controller, clears prior injections, waits for RTUs to observe the off-edge, resets old HFD/trip latches, writes the complete pattern, verifies actual RTU FC01 status readback, then re-enables SHG. RTU verification reads FC01 CS status. Status 1 means the pattern was verified; status 2 indicates a partial/failed readback; status 3 means the Controller is not ready; status 4 is a testbench error.

Before each new K1–K6 test, use **RESET SISTEM** and wait until Controller returns to **SIAGA**. After a case completes or locks out, the next case is rejected until the system is returned to a ready baseline; this prevents leftover topology or latches from contaminating the next HFD pattern. The controller will normally clear HFD after isolating the fault, so inspect the testbench acknowledgement/log for the injected pattern, not just the eventual post-isolation HFD display.

## 11. Validation checklist

- Confirm all laptop aliases `.2..9` exist on the physical Ethernet adapter and do not conflict with physical devices.
- Confirm seven RTUs and the Controller start without address-in-use errors.
- Confirm HMI displays 7/7 RTUs online.
- Verify the Controller map in ModScan, including DI26, DI30, DI88 and DI99.
- PLC1: test one CB/LBS point (e.g. DI88 / 10089) and one HFD point (e.g. DI26 / 10027).
- PLC2: test one HFD point (e.g. DI30 / 10031).
- Confirm PNP transistor wiring and HFD polarity before connecting physical loads.
- Live tests with the physical PLCs and HUe have not been executed from this packaging environment; perform them in the lab.


## EBC NEWEST CoreDb integration

The supplied EBC project is `NEWEST(1).ebc` (project C04), and the external workbook is the CoreDB source for this update. The active field status transport is FC01, GI CS0..5 and GD CS0..9. CHFLISR server Unit IDs 1..7 are distinct from the seven downstream MDBM Unit IDs `1,2,2,3,4,2,3`.

The provided CoreDb Command sheet has full GI/GD switch OPEN/CLOSE source mappings. It does **not** have source coordinates for HFD/trip reset commands; see `EBC_CS_MAPPING.md`. The Python adapter explicitly fails active reset requests until those sources are added to Easergy Builder. The old `reference/C05.ebc` and `reference/revisi.xlsx` files are historical snapshots, not authoritative for this update.

Run `py validate_ebc_cs_mapping.py`, `py validate_routing_config.py`, `py validate_command_events.py`, `py validate_hfd_cases.py`, and `py validate_dual_plc_mapping.py`. Start all seven RTUs before running `py validate_multi_master.py`.


### HUe gateway no-response diagnostic

If the client logs `terkoneksi ke HUe` but FC01 returns `No response received`, run `py diagnose_hue_gateway.py`. It performs read-only FC01 probes on Unit IDs 1..7, using a fresh TCP connection for every Unit ID. Confirm that the laptop NIC facing HUe is `192.168.250.2/24` (the configured CHFLISR remote IP), CHFLISR is CALLED on `.250.1:502`, and all seven MDBE STD bins are active on slave IDs 1..7. A successful TCP handshake does not prove the MDBE Modbus service has answered a valid request.
