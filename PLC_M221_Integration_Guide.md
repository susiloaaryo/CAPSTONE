# Dual M221 integration with the FLISR Controller

## Network architecture

- Controller status/test endpoint (Python laptop): `192.168.250.2:502`, Unit ID `1`. Physical PLC connections use the currently configured HUe LAN1/LAN2 server, unless network routing is deliberately set up for the laptop endpoint.
- PLC1: Schneider TM221CE40R, current IP `192.168.251.11/24`, on HUe LAN1 `192.168.251.10`.
- PLC2: Schneider TM221CE16T, current IP `192.168.252.11/24`, on HUe LAN2 `192.168.252.10`.
- Saitel HUe MNT is configured as `192.168.250.1/24` in the current project; verify the live interface IP.
- Both PLCs are Modbus TCP clients reading the same Controller server. The seven virtual RTUs send their data to the laptop Controller; the PLCs do not need to connect to each RTU individually.

## Distribution

| PLC | Outputs used | Assignment |
|---|---:|---|
| PLC1 TM221CE40R | 16/16 | 10 LBS + 2 CB + 4 HFD |
| PLC2 TM221CE16T | 6/7 | 6 HFD + 1 spare |
| **Total** | **22/23** | **12 CB/LBS + 10 HFD** |

## Read contract

- Modbus server: `192.168.250.2:502`, Unit ID `1`, Function Code 02 (Discrete Inputs).
- PLC1: read offsets `88..99` (12 switch aliases) and `26..29` (4 HFD statuses).
- PLC2: read offsets `30..35` (6 HFD statuses).
- Protocol offsets are zero-based. ModScan display addresses are offsets + 10001.
- Controller DI0..DI99 remains the common source map; original points DI0..DI87 retain their meaning, and DI88..DI99 are the PLC-order CB/LBS aliases.
- Verify `READ_VAR` buffer bit packing in the installed EcoStruxure Machine Expert - Basic version before assigning to `%M` bits.

## Test sequence

1. Start seven RTUs, System Behavior, Controller, and HMI in the documented startup order.
2. Verify Controller `192.168.250.2:502` responds to FC02.
3. Test one switch alias (for example DI88 / ModScan 10089) against the corresponding CB/LBS output on PLC1.
4. Test DI26 / ModScan 10027 for GD01 HFD1 on PLC1, then DI30 / ModScan 10031 for GD03 HFD1 on PLC2.
5. Verify each HFD bit's intended polarity before wiring physical lamps or other loads.
6. Confirm RTU offline/unknown switch positions are not misinterpreted as confirmed OPEN; use the original validity and RTU-online points for diagnostics.

## Electrical/safety boundary

- CB/LBS and HFD outputs are status indicators only; they are not intended to energize CB/LBS operating coils.
- TM221CE40R has relay outputs. TM221CE16T has 24 VDC transistor PNP/source outputs rated 0.5 A per point. Check load type, output/common current limits, power supply and electrical interface before wiring.
- Real field control requires a separately reviewed design with Local/Remote permissives, trip interlocks, output feedback, approved interposing interface and protection.

## External references

- Schneider TM221CE40R: https://www.se.com/id/en/product/TM221CE40R/
- Schneider TM221CE16T: https://www.se.com/id/en/product/TM221CE16T/controller-m221-16-io-transistor-pnp-ethernet/
- Schneider `READ_VAR` reference: https://www.se.com/us/en/faqs/FA241658/

The Python package provides the Modbus status source and maps. It does not download or automatically program either physical PLC; configure and test the ladder in EcoStruxure Machine Expert - Basic.
