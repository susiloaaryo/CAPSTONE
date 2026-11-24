"""Static checks for the direct and HUe gateway network configuration."""
import topologi as T

assert len(T.NODE) == len(T.RTU_IPS) == len(T.HUE_UNIT_IDS) == len(T.RTU_MDBM_UNIT_IDS) == 7
assert T.HUE_UNIT_IDS == [1, 2, 3, 4, 5, 6, 7]
assert T.RTU_MDBM_UNIT_IDS == [1, 2, 2, 3, 4, 2, 3]
assert T.HOST_HUE_MODBUS == "192.168.250.1"
assert T.PORT_HUE_MODBUS == 502
assert T.TESTBENCH_EBC_UNIT_ID == 30
assert all(T.port_node(i) == 502 for i in range(7))
assert (T.CO_PERINTAH, T.CO_RESET) == (10, 12)
assert [T.hue_switch_command_address(0, 0, True),
        T.hue_switch_command_address(0, 0, False)] == [1, 2]
assert [T.hue_switch_command_address(1, 0, True),
        T.hue_switch_command_address(1, 0, False),
        T.hue_switch_command_address(1, 1, True),
        T.hue_switch_command_address(1, 1, False)] == [1, 2, 6, 7]
print("PASS: 7 CHFLISR Unit IDs, downstream MDBM IDs, HUe host/port, FC01 and command addresses.")
for i in range(7):
    print(f"  CHFLISR UID {T.hue_unit_id(i)} -> {T.nama_node(i):8s} {T.ip_node(i)}:502, downstream UID {T.mdbm_unit_id(i)}")
