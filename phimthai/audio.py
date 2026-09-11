"""Qt microphone capture; unique files and explicit ownership per recording."""
import array
import wave
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices, QtAudio


class Recorder(QObject):
    level = Signal(int)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.output = None
        self.frames = 0
        self.device = None
        self.pending = b""
        self.source_id = None
        self.capture_failed = False
        self.pulse_guard = None
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioInputsChanged.connect(self.inputs_changed)

    def inputs_changed(self):
        if self.source and self.source_id not in {bytes(d.id()) for d in QMediaDevices.audioInputs()}:
            self.capture_failed = True
            self.stop()
            self.failed.emit("Selected microphone disconnected. Recording stopped.")

    def start(self, path: Path, microphone=""):
        inputs = QMediaDevices.audioInputs()
        if not inputs:
            raise RuntimeError("No microphone found. Check your audio settings and microphone permission.")
        device = next((d for d in inputs if bytes(d.id()).hex() == microphone), None) if microphone else QMediaDevices.defaultAudioInput()
        if device is None:
            raise RuntimeError("Selected microphone is disconnected. Select an available input.")
        self.source_id = bytes(device.id())
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt.setSampleRate(device.preferredFormat().sampleRate())
        if not device.isFormatSupported(fmt):
            fmt.setChannelCount(device.preferredFormat().channelCount())
        if not device.isFormatSupported(fmt):
            raise RuntimeError("Microphone does not support PCM16 capture. Select another input.")
        self.frames = 0
        self.capture_failed = False
        self.pending = b""
        self.frame_size = fmt.channelCount() * 2
        from .pulse_guard import PulseSourceGuard
        guard = PulseSourceGuard(self)
        self.pulse_guard = guard
        guard.failed.connect(lambda message: self.guard_failed(guard, message))
        try:
            guard.start(self.source_id)
            if self.pulse_guard is not guard:
                raise RuntimeError("Microphone monitoring failed to start")
            self.output = wave.open(str(path), "wb")
            self.output.setnchannels(fmt.channelCount())
            self.output.setsampwidth(2)
            self.output.setframerate(fmt.sampleRate())
            self.source = QAudioSource(device, fmt, self)
            self.source.stateChanged.connect(self.state_changed)
            self.device = self.source.start()
            if self.device is None:
                raise RuntimeError("Microphone could not start")
            self.device.readyRead.connect(self.read)
            guard.verify()
        except Exception:
            self.capture_failed = True
            self._finish_capture()
            raise

    def guard_failed(self, guard, message):
        if guard is not self.pulse_guard:
            return
        self.capture_failed = True
        self._finish_capture()
        self.failed.emit(message)

    def read(self):
        if not self.device or not self.output:
            return
        data = self.pending + bytes(self.device.readAll())
        count = len(data) // self.frame_size * self.frame_size
        data, self.pending = data[:count], data[count:]
        try:
            self.output.writeframesraw(data)
        except (OSError, wave.Error) as exc:
            self.capture_failed = True
            self._finish_capture()
            self.failed.emit(f"Could not save microphone audio: {exc}")
            return
        self.frames += len(data) // self.frame_size
        samples = array.array("h", data)
        peak = max((abs(v) for v in samples), default=0)
        self.level.emit(min(100, int(peak / 32768 * 100)))

    @Slot()
    def state_changed(self):
        if self.source and self.source.error() not in {QtAudio.Error.NoError, QtAudio.Error.UnderrunError}:
            self.capture_failed = True
            self.stop()
            self.failed.emit("Microphone disconnected or capture failed")

    def stop(self):
        if self.device and self.output:
            self.read()
        error = self._finish_capture()
        if error:
            self.failed.emit(error)
        return self.frames > 0 and not self.capture_failed

    def _finish_capture(self):
        # Detach before stopping: Qt signals and error handlers can reenter stop.
        source, self.source = self.source, None
        self.device = None
        if source:
            source.stop()
            source.deleteLater()
        output, self.output = self.output, None
        error = None
        guard, self.pulse_guard = self.pulse_guard, None
        if guard:
            error = guard.stop(verify=not self.capture_failed)
            guard.deleteLater()
            if error:
                self.capture_failed = True
        if output:
            try:
                output.close()
            except (OSError, wave.Error) as exc:
                self.capture_failed = True
                error = f"Could not finish saving microphone audio: {exc}"
        self.level.emit(0)
        return error
