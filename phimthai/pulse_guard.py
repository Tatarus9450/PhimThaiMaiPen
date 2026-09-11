"""Invalidate a recording when its PulseAudio source disappears.

Qt's unpatched PulseAudio backend can move streams without emitting device
removal. A separate subscription plus a final server query prevents forwarding
such a recording to ASR. PipeWire's PulseAudio compatibility server is supported.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


if __name__ == "__main__":
    # The subscription belongs to this app. Do not leave a watcher behind if
    # the GUI crashes or is killed before QProcess can run its normal cleanup.
    import ctypes
    import signal
    parent = os.getppid()
    if parent == 1 or ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise SystemExit(1)
    if os.getppid() != parent:
        raise SystemExit(1)
    os.execvp("pactl", ["pactl", "subscribe"])

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class PulseSourceGuard(QObject):
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.identity = None
        self.buffer = b""

    @staticmethod
    def sources():
        try:
            response = subprocess.run(["pactl", "--format=json", "list", "sources"],
                                      capture_output=True, text=True, timeout=2,
                                      env=dict(os.environ, LC_ALL="C"))
            values = json.loads(response.stdout) if response.returncode == 0 else None
            if not isinstance(values, list):
                raise ValueError("Invalid source list")
            return {(item["name"], item["index"]) for item in values
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                    and type(item.get("index")) is int}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Could not verify the microphone with PulseAudio. Check your audio service.") from exc

    def start(self, device_id):
        if not shutil.which("pactl"):
            if Path("/.flatpak-info").is_file() and Path("/app/lib/libQt6Multimedia.so.6.11.1").is_file():
                return  # Our sandbox recipe provides the patched Qt implementation.
            raise RuntimeError("Install pactl (PulseAudio utilities) before recording so microphone disconnection can be checked.")
        name = device_id.decode("utf-8", errors="strict")
        self.identity = next((item for item in self.sources() if item[0] == name), None)
        if self.identity is None:
            raise RuntimeError("Selected microphone is unavailable from PulseAudio. Reconnect it and refresh inputs.")
        process = QProcess(self)
        self.process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("LC_ALL", "C")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(lambda: self.read(process))
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(lambda *_: self.lost(process))
        process.errorOccurred.connect(lambda *_: self.lost(process))
        process.start(sys.executable, ["-m", "phimthai.pulse_guard"])
        if not process.waitForStarted(2000):
            self.stop(verify=False)
            raise RuntimeError("Could not start microphone disconnect monitoring")
        self.verify()

    def verify(self):
        if self.identity and self.identity not in self.sources():
            raise RuntimeError("Selected microphone disconnected. Recording discarded.")

    def read(self, process):
        if process is not self.process:
            return
        self.buffer += bytes(process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            match = re.fullmatch(rb"Event 'remove' on source #(\d+)\r?", line)
            if match and self.identity and int(match[1]) == self.identity[1]:
                self.failed.emit("Selected microphone disconnected. Recording discarded.")
                return

    def lost(self, process):
        if process is self.process:
            self.failed.emit("Microphone monitoring stopped. Recording discarded; check your audio service.")

    def stop(self, verify=True):
        process, self.process = self.process, None
        error = None
        if process:
            if verify and (process.state() != QProcess.ProcessState.Running or process.waitForFinished(0)):
                error = "Microphone monitoring stopped. Recording discarded; check your audio service."
            process.kill()
            process.waitForFinished(2000)
            process.deleteLater()
        if verify:
            try:
                self.verify()
            except RuntimeError as exc:
                error = str(exc)
        self.identity = None
        self.buffer = b""
        return error
