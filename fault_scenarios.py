"""Fault-case HR injection definitions shared by RTU and direct test modes.

Cases 1..6 mirror the cable/HFD table supplied for the FLISR project.
GI logical IDs: 8020 (GI SATU), 8026 (GI DUA).
GD logical IDs: 8021..8025 (GD01..GD05).
GI HR0=forced trip; GD HR0=HFD1 and HR1=HFD2.
"""

def injection_for_case(case: int):
    case = int(case)
    result = {port: {} for port in (8020, 8021, 8022, 8023, 8024, 8025, 8026)}

    if case == 0:
        return result

    # GI SATU (left side), cases 1..3.
    # Cable 1 has no HFD; cable 2 activates both GD01 HFDs;
    # cable 3 activates both HFDs on GD01 and GD02.
    if case in (1, 2, 3):
        result[8020][0] = 1
        for gd in range(1, case):
            logical_id = 8020 + gd
            result[logical_id][0] = 1  # GD HFD1 (HR0)
            result[logical_id][1] = 1  # GD HFD2 (HR1)
        return result

    # GI DUA (right side), cases 4..6.
    # Cable 4 activates both HFDs on GD04 and GD05; cable 5 activates
    # both HFDs on GD05; cable 6 has no HFD.
    if case in (4, 5, 6):
        result[8026][0] = 1
        if case == 4:
            for logical_id in (8024, 8025):  # GD04 and GD05
                result[logical_id][0] = 1      # HFD1
                result[logical_id][1] = 1      # HFD2
        elif case == 5:
            result[8025][0] = 1  # GD05 HFD1
            result[8025][1] = 1  # GD05 HFD2
        return result

    # Source faults.
    if case == 7:
        result[8020][1] = 1  # GI SATU HR1 = forced UV
        return result
    if case == 8:
        result[8026][1] = 1  # GI DUA HR1 = forced UV
        return result

    return result
