# FLISR routing modes — NEWEST.ebc aligned

GI/GD simulators always run as seven separate Modbus TCP servers. Both controller modes use the GI/GD field status image. Direct mode reads FC01 from the RTU simulators. HUe mode reads FC01 because the supplied CoreDb workbook maps the status points to CS coordinates; the Easergy Modbus Slave STD profile reads CS using FC01 (FC02 is for IS coordinates). The controller's aggregated status server to HMI/PLC remains FC02.

## Mode N — direct to RTU simulators

`controller.py` uses `lapangan.py` to connect to `.3`–`.9:502`, Unit ID 1. It reads FC01 status and uses simulator-only level command coils CO10/CO11 and reset CO12. No HUe connection is needed for this mode.

## Mode Y — through Saitel HUe

`controller_rtu.py` uses `lapangan_hue.py` and connects to `192.168.250.1:502`. The HUe CHFLISR server Unit IDs are 1..7 in order GIA, GD01, GD02, GD03, GD04, GD05, GIB.

HUe's own downstream MDBM Unit IDs follow the uploaded EBC project and differ by RTU: `[1, 2, 2, 3, 4, 2, 3]` in the controller's node order. The Python RTU simulators therefore expose Unit ID 1 for direct mode and the configured MDBM Unit ID as an alias. They publish their CoreDb CS status image on FC01, GI CS0..5 and GD CS0..9, matching the downstream MDBM poll defined in EBC.

### HUe command points

The existing CoreDb Command entries define separate momentary OPEN/CLOSE source points:

- GI: CS1 CLOSE, CS2 OPEN.
- GD LBS1: CS1 CLOSE, CS2 OPEN.
- GD LBS2: CS6 CLOSE, CS7 OPEN.

The adapter checks that each selector explicitly reports Remote before it sends a True/False FC05 pulse. It reads the configured CS status image using FC01 and recreates the TCP client after a transport timeout. The RTU simulator consumes a mapped downstream write as an event and does not overwrite the FC01 status image.

**Reset limitation:** the uploaded CoreDb Command contains only destination coordinates for the GD HFD reset outputs (Mx CS0 and CS5) and no source coordinate for these commands; GI trip reset is absent. New reset sources are documented as proposed additions in `EBC_CS_MAPPING.md`. Until the EBC project is updated, active HFD/trip reset through Mode Y is not available; the code returns failure without writing to proposed/unconfigured addresses and the controller reports partial completion rather than claim success.

## Shared services

- Controller aggregate: `192.168.250.2:502`, FC02 DI0..DI99.
- System Behavior testbench: `192.168.250.2:503`; EBC polls Unit ID 30 / FC01 CS0..CS7.
- Streamlit HMI: `http://192.168.250.2:8501`.
- Physical PLC network: HUe LAN1/LAN2; live addresses remain installation-specific.

## Validation

Run `py validate_ebc_cs_mapping.py`, `py validate_routing_config.py`, `py validate_hfd_cases.py`, then start all RTUs and run `py validate_multi_master.py`. These verify the software mapping and RTU Unit ID aliases; they do not replace live HUe commissioning.
