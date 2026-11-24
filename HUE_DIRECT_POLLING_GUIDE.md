# Saitel DR-HUe — commissioning guide based on NEWEST.ebc

## Architecture and server endpoint

The supplied EBC project configures the HUe `CHFLISR` channel as a Modbus TCP server on `192.168.250.1:502`, with the laptop client at `192.168.250.2` in the allowed remote list. `controller_rtu.py` connects to that endpoint and uses seven CHFLISR logical server Unit IDs 1..7.

The HUe MDBM channels poll seven RTU simulator IPs on TCP/502. **Downstream Unit IDs are not all 1**:

| MDBM bin | RTU IP | Downstream Unit ID | CHFLISR server Unit ID |
|---|---|---:|---:|
| M1_GIA / S1_GIA | `192.168.250.3` | 1 | 1 |
| M2_GD1 / S2_GD1 | `192.168.250.9` | 2 | 2 |
| M3_GD2 / S3_GD2 | `192.168.250.5` | 2 | 3 |
| M4_GD3 / S4_GD3 | `192.168.250.6` | 3 | 4 |
| M5_GD4 / S5_GD4 | `192.168.250.7` | 4 | 5 |
| M6_GD5 / S6_GD5 | `192.168.250.8` | 2 | 6 |
| M7_GIB / S7_GIB | `192.168.250.4` | 3 | 7 |

`M30_TestBench` is a separate MDBM channel to `192.168.250.2:503`, Unit ID 30.

## Status polling

The EBC `mdbm_std.xml` defines the downstream HUe → RTU requests as FC01, start address `0`, interval `1000 ms`, with quantity `6` for each GI and `10` for each GD. Do not change these downstream MDBM requests to FC02:

- GI CS0..5 = CBTR, CLOSE, OPEN, LOCAL, REMOTE, UV.
- GD CS0..9 = HFD1, LBS1 CLOSE, LBS1 OPEN, LBS1 LOCAL, LBS1 REMOTE, HFD2, LBS2 CLOSE, LBS2 OPEN, LBS2 LOCAL, LBS2 REMOTE.

The simulator publishes these exact FC01 images. It serves Unit ID 1 for direct-mode/testbench clients and also exposes the specific downstream Unit ID in the table above, each alias sharing the same status/command datastore. The CHFLISR MDBE XML itself does not specify a request function code. The CoreDb workbook does: the server-side destination coordinates are `CS:0..5` for GI and `CS:0..9` for GD. In the Easergy Modbus Slave STD profile, `CS` is read with FC01 and `IS` with FC02 (Schneider *Modbus Devices – User Manual*, section 3.1.2). Therefore this adapter uses FC01 only for the supplied CS image; FC02 is not a fallback for these points.

## Existing switch command points

The supplied CoreDB Command table contains real source/destination mappings. `controller_rtu.py` sends momentary FC05 writes to the CHFLISR logical Unit ID with these source coil addresses:

- GI: CS1 = CLOSE, CS2 = OPEN.
- GD LBS1: CS1 = CLOSE, CS2 = OPEN.
- GD LBS2: CS6 = CLOSE, CS7 = OPEN.

The corresponding CoreDB destinations are the matching `Mx_* CS` addresses. The adapter checks Remote selector feedback before writing. The simulator translates the downstream FC05 writes at these addresses into switching events while preserving FC01 feedback.

## Reset command limitation — must be fixed in Easergy Builder

The supplied workbook/EB C command database has ten GD HFD reset commands with destinations M2..M6 CS0/CS5 but **without SOURCE_COORD**. It has no GI trip-reset command row. A controller connected to CHFLISR cannot call a command source that does not exist in that project.

The ZIP documents the following proposed source coordinates; they are not configured in the supplied `NEWEST.ebc` and are not written while `HUE_RESET_SOURCE_MAP_AVAILABLE = False`:

| Logical server | Proposed source coil | Required destination |
|---|---:|---|
| S1_GIA / Unit 1 | CS6 | M1_GIA CS0 (GI trip reset) |
| S7_GIB / Unit 7 | CS6 | M7_GIB CS0 (GI trip reset) |
| S2_GD1..S6_GD5 | CS10 | corresponding M2..M6 CS0 (HFD1 reset) |
| S2_GD1..S6_GD5 | CS11 | corresponding M2..M6 CS5 (HFD2 reset) |

Until those source mappings are added to CoreDb Command, transferred to the HUe, and verified, any active protection latch reset requested through Mode Y will return false without writing to an unconfigured address. Only after verification should `HUE_RESET_SOURCE_MAP_AVAILABLE` be set to `True` in `topologi.py`. The controller may therefore report partial restoration. Inactive protection requires no reset and does not block normal startup.

## Commissioning sequence

1. Back up the active Easergy Builder project.
2. Confirm HUe MNT IP `.250.1/24`, laptop `.250.2/24`, and CHFLISR server port 502.
3. Confirm the seven MDBM channel IPs and **downstream** Unit IDs above.
4. Confirm MDBM status requests use FC01 at address 0 with the correct point counts.
5. Confirm CHFLISR logical server Unit IDs 1..7 match S1_GIA, S2_GD1, S3_GD2, S4_GD3, S5_GD4, S6_GD5, S7_GIB.
6. Check existing switch Command sources CS1/2/6/7 are writable and routed to corresponding Mx destinations.
7. Add and test the reset source mappings if full protection reset/recovery is required.
8. Start simulator processes, run `py validate_multi_master.py`, then start controller mode Y.
9. First prove read-only status point changes and selector feedback; the controller log reports whether each CHFLISR Unit ID returned the FC01 CS image. Then test switch commands with no live apparatus connected.

This guide documents the supplied project and software expectations; it does not claim that a physical HUe was reachable or tested from this environment.


## No response after TCP connection

If the TCP connection succeeds but FC01 receives no response, run `py diagnose_hue_gateway.py`. The script opens a fresh connection for each Unit ID 1..7 and performs read-only FC01 queries. Verify the laptop source IP is `192.168.250.2/24` (the configured CHFLISR remote), CHFLISR is CALLED on `192.168.250.1:502`, and the seven MDBE STD bins are loaded and associated with CHFLISR using slave numbers 1..7. A TCP handshake alone does not prove the MDBE protocol service is replying.
