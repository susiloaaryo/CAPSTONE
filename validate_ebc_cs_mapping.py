"""Static checks for NEWEST.ebc CoreDb CS / FC01 / command mapping."""
from pathlib import Path
import topologi as T

root = Path(__file__).resolve().parent
gd = (root / "rtu_gd.py").read_text(encoding="utf-8")
gi = (root / "rtu_gi.py").read_text(encoding="utf-8")
hue = (root / "lapangan_hue.py").read_text(encoding="utf-8")
helper = (root / "rtu_command_datablock.py").read_text(encoding="utf-8")

assert T.JUMLAH_DI_GD == 10
assert T.JUMLAH_DI_GI == 6
assert T.RTU_MDBM_UNIT_IDS == [1, 2, 2, 3, 4, 2, 3]
assert T.HUE_UNIT_IDS == [1, 2, 3, 4, 5, 6, 7]
assert T.TESTBENCH_EBC_UNIT_ID == 30
assert (T.DI_GD_LBS1_HFD, T.DI_GD_LBS1_CLOSE, T.DI_GD_LBS1_OPEN,
        T.DI_LBS1_LOCAL, T.DI_LBS1_REMOTE, T.DI_GD_LBS2_HFD,
        T.DI_GD_LBS2_CLOSE, T.DI_GD_LBS2_OPEN, T.DI_LBS2_LOCAL,
        T.DI_LBS2_REMOTE) == tuple(range(10))
assert (T.DI_CB_TRIP, T.DI_CB_TUTUP, T.DI_CB_BUKA,
        T.DI_CB_LOCAL, T.DI_CB_REMOTE, T.DI_UV_GI) == tuple(range(6))
assert "read_coils(" in hue
assert "read_discrete_inputs(" not in hue
assert T.HUE_STATUS_FC_PRIMARY == 1
assert T.HUE_STATUS_FORCE_FC == 1
assert T.HUE_RESET_SOURCE_MAP_AVAILABLE is False
assert "read_coils(" in (root / "lapangan.py").read_text(encoding="utf-8")
assert "EBCCommandCoilDataBlock" in gd and "EBCCommandCoilDataBlock" in gi
assert "read_discrete_inputs(0, count" not in (root / "system_behavior.py").read_text(encoding="utf-8")
assert "read_coils(0, count" in (root / "system_behavior.py").read_text(encoding="utf-8")
assert "T.DI_GD_LBS1_HFD" in (root / "system_behavior.py").read_text(encoding="utf-8")
assert "T.DI_GD_LBS2_HFD" in (root / "system_behavior.py").read_text(encoding="utf-8")
assert "event-only" in helper
for token in ("HUE_CMD_GI_CLOSE = 1", "HUE_CMD_GI_OPEN = 2",
              "HUE_CMD_GD_LBS2_CLOSE = 6", "HUE_CMD_GD_LBS2_OPEN = 7"):
    assert token in (root / "topologi.py").read_text(encoding="utf-8")
print("PASS: GI CS0..5 and GD CS0..9 align with EBC FC01; Unit IDs and command points match NEWEST.ebc/CoreDb.")
