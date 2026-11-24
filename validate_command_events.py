"""Unit test for translating EBC FC05 commands into simulator events.

Run after installing requirements.txt:
    py validate_command_events.py
"""
from rtu_command_datablock import EBCCommandCoilDataBlock

GI_COMMANDS = {
    0: ("reset_trip", 0),
    1: ("switch", 0, True),   # CB CLOSE
    2: ("switch", 0, False),  # CB OPEN
}
GD_COMMANDS = {
    0: ("reset_hfd", 0),
    1: ("switch", 0, True),
    2: ("switch", 0, False),
    5: ("reset_hfd", 1),
    6: ("switch", 1, True),
    7: ("switch", 1, False),
}


def assert_command_event(command_map, address, expected, count=10):
    block = EBCCommandCoilDataBlock(0, [0] * count, command_map)
    block.setValues(address, [True])
    assert block.pop_events() == [expected], (address, expected)
    # Deasserting a momentary command must not create a second event.
    block.setValues(address, [False])
    assert block.pop_events() == [], ("unexpected OFF event", address)

    # Incoming command writes must not corrupt the FC01 status image.
    assert block.getValues(address, count=1) == [0], address

    # Internal status publication updates the image but is never a command.
    block.set_internal(address, [1])
    assert block.getValues(address, count=1) == [1], address
    assert block.pop_events() == [], ("internal write became event", address)


for address, event in GI_COMMANDS.items():
    assert_command_event(GI_COMMANDS, address, event, count=13)
for address, event in GD_COMMANDS.items():
    assert_command_event(GD_COMMANDS, address, event, count=13)

print("PASS: GI/GD EBC commands become one ON-edge event; OFF and internal status writes are safe.")
