# Dual-PLC update notes

## What changed
- Added PLC1 configuration constant `HOST_PLC1 = 192.168.250.11` for TM221CE40R.
- Added PLC2 configuration constant `HOST_PLC2 = 192.168.250.12` for TM221CE16T.
- Documented both PLCs as Modbus TCP clients reading the shared Controller at `192.168.250.2:502`, Unit ID 1.
- Kept the existing Controller DI map `DI0..DI99`; no new HFD status bits are required because HFD points already occupy DI26..DI35.
- Assigned PLC1 outputs to 12 CB/LBS status points (`DI88..DI99`) and four HFD points (`DI26..DI29`).
- Assigned PLC2 outputs to the other six HFD points (`DI30..DI35`), leaving one output spare.
- Added per-PLC and combined CSV mapping, ladder references, integration guides, a Word mapping reference, and a static mapping validator.

## Output budget
- TM221CE40R: 16 of 16 outputs assigned (12 CB/LBS + 4 HFD).
- TM221CE16T: 6 of 7 transistor outputs assigned (6 HFD + 1 spare).
- Total used: 22 outputs for 22 requested indications.

## Boundary
The Python source publishes status data; it does not automatically create/download EcoStruxure Machine Expert - Basic programs to either physical PLC. Configure each PLC's Modbus TCP client read ranges and `%M` to `%Q` ladder mapping in that software, validate bit packing, and test in the lab. All proposed outputs are status indications, not live CB/LBS operating commands.
