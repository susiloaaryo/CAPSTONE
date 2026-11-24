"""Regression checks: injection cases match the user's six-cable HFD table."""
from fault_scenarios import injection_for_case
import topologi as T
from lokalisasi import cari_segmen

EXPECTED_SEGMENT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
EXPECTED_GD_HFD = {
    1: {},
    2: {1: (1, 1)},
    3: {1: (1, 1), 2: (1, 1)},
    4: {4: (1, 1), 5: (1, 1)},
    5: {5: (1, 1)},
    6: {},
}

for case, expected_segment in EXPECTED_SEGMENT.items():
    inj = injection_for_case(case)
    hfd = {}
    actual_pattern = {}
    for gd_number in range(1, 6):
        logical_id = 8020 + gd_number
        hfd1 = int(inj[logical_id].get(0, 0))
        hfd2 = int(inj[logical_id].get(1, 0))
        node = gd_number  # topologi.NODE order is GI SATU, GD01..GD05, GI DUA
        hfd[(node, 0)] = hfd1
        hfd[(node, 1)] = hfd2
        if hfd1 or hfd2:
            actual_pattern[gd_number] = (hfd1, hfd2)

    expected_pattern = EXPECTED_GD_HFD[case]
    assert actual_pattern == expected_pattern, (
        f"Case {case}: pola HFD {actual_pattern}, expected {expected_pattern}"
    )
    from_left = case <= 3
    found = cari_segmen(hfd, from_left)
    assert found == expected_segment, (
        f"Case {case}: localization menemukan kabel {found + 1 if found is not None else None}, "
        f"expected kabel {expected_segment + 1}"
    )
    print(f"PASS case {case}: HFD={actual_pattern}; lokasi kabel {found + 1}")

print("Semua enam skenario kabel cocok dengan tabel HFD.")
