"""Dictation state and the toggle debounce used by the main window."""
import time
from enum import Enum


class DictationState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    PASTING = "pasting"


def derive_state(*, recording=False, pasting=False, processing=False):
    """One precedence rule for every caller: the microphone wins, then paste, then jobs."""
    if recording:
        return DictationState.RECORDING
    if pasting:
        return DictationState.PASTING
    if processing:
        return DictationState.PROCESSING
    return DictationState.IDLE


class Debouncer:
    """Accept one trigger per ``interval`` seconds from any source.

    KDE can deliver Meta+H twice (portal GlobalShortcuts and the native
    service binding); the second event must not immediately stop recording.
    """

    def __init__(self, interval=0.4, clock=time.monotonic):
        self.interval = interval
        self.clock = clock
        self.last = None

    def accept(self):
        now = self.clock()
        if self.last is not None and 0 <= now - self.last < self.interval:
            return False
        self.last = now
        return True

    def reset(self):
        self.last = None
