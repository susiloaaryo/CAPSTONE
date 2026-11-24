"""Static validation for the dual-M221 status mapping artefacts."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
path = ROOT / "PLC_M221_Ladder_Mapping.csv"
with path.open(newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 22, f"Expected 22 outputs, got {len(rows)}"
assert sum(r["plc"] == "PLC1" for r in rows) == 16
assert sum(r["plc"] == "PLC2" for r in rows) == 6
assert len({(r["plc"], r["output_coil"]) for r in rows}) == 22, "Duplicate output"
assert len({(r["plc"], r["ladder_contact"]) for r in rows}) == 22, "Duplicate M bit"
assert sorted(int(r["controller_DI_offset"]) for r in rows if r["signal_semantics"] == "Switch position indication") == list(range(88, 100))
assert sorted(int(r["controller_DI_offset"]) for r in rows if r["signal_semantics"] == "HFD status/alarm bit") == list(range(26, 36))
for filename, expected in [("PLC1_TM221CE40R_Ladder_Mapping.csv", 16), ("PLC2_TM221CE16T_Ladder_Mapping.csv", 6)]:
    with (ROOT / filename).open(newline="", encoding="utf-8-sig") as f:
        current = list(csv.DictReader(f))
    assert len(current) == expected, f"{filename}: expected {expected}, got {len(current)}"
print("OK: 22 unique output mappings; PLC1=16, PLC2=6; DI ranges switch=88..99 and HFD=26..35.")
