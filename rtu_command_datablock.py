"""Modbus coil datablock for the Easergy Builder CoreDb command contract.

EBC maps FC01 coil status points and FC05 command inputs through the same
logical CS indexes.  A plain coil datablock cannot distinguish a command write
from the status value at that address, so writes to the configured EBC command
addresses are consumed as events while the FC01 status image is preserved.

The direct Python controller keeps its separate command registers at CO10..12.
"""
from collections import deque
from threading import Lock

from pymodbus.datastore import ModbusSequentialDataBlock


class EBCCommandCoilDataBlock(ModbusSequentialDataBlock):
    """Keep FC01 status bits stable while translating EBC FC05 writes."""

    def __init__(self, address, values, command_map):
        super().__init__(address, values)
        self._command_map = dict(command_map)
        self._events = deque()
        self._events_lock = Lock()

    def setValues(self, address, values):
        """Handle protocol writes; command addresses are event-only points."""
        if isinstance(values, (int, bool)):
            values = [values]
        else:
            values = list(values)

        for offset, value in enumerate(values):
            point = int(address) + offset
            event = self._command_map.get(point)
            if event is not None:
                # EBC command objects are pulsed ON then OFF.  Only the ON
                # edge creates an event; do not overwrite the FC01 status bit.
                if bool(value):
                    with self._events_lock:
                        self._events.append(event)
                continue
            super().setValues(point, [value])

    def set_internal(self, address, values):
        """Update a status/output internally without interpreting it as a command."""
        super().setValues(address, values)

    def pop_events(self):
        """Return and clear all command events received since the last scan."""
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
        return events
