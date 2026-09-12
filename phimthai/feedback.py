"""Legacy-sized dictation HUD in an isolated XWayland helper, plus local chimes.

A Wayland xdg-toplevel cannot reliably promise nonactivation or placement.
The 200×52 override-redirect XCB surface preserves the original left-side HUD;
the application's main window continues using its native platform.
"""
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication


class DictationFeedback(QObject):
    unavailable = Signal(str)

    def __init__(self, parent=None, *, sound_enabled=True, popup_enabled=True):
        super().__init__(parent)
        self.sound_enabled = bool(sound_enabled)
        self.popup_enabled = bool(popup_enabled)
        self._phase = "idle"
        self._profile = "MIX"
        self._closed = False
        self._ready = False
        self._buffer = b""
        self._pending = {"state": "idle", "profile": self._profile}
        self.last_report = {}
        self.popup_error = ""
        app = QApplication.instance()
        self._interactive = app is not None and app.platformName() not in {"offscreen", "minimal"}
        self.sounds = {}
        self.audio_outputs = {}
        for name in (("start", "stop", "mode", "ready") if self._interactive else ()):
            # QSoundEffect uses PipeWire's shared Notification role. KDE may
            # mute that group even when dictation feedback is enabled here.
            # Use regular application playback without changing system mutes.
            sound = QMediaPlayer(self)
            output = QAudioOutput(sound)
            output.setVolume(1.0 if name == "ready" else .65)
            sound.setAudioOutput(output)
            sound.setLoops(1)
            sound.errorOccurred.connect(lambda _error, message:
                self.unavailable.emit("เล่นเสียงแจ้งไม่ได้: " + message))
            sound.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "assets" /
                                                  ("feedback-" + name + ".wav"))))
            self.sounds[name] = sound
            self.audio_outputs[name] = output
        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("QT_QPA_PLATFORM", "xcb")
        environment.insert("QT_SCALE_FACTOR", "1")
        environment.insert("QT_SCREEN_SCALE_FACTORS", "1")
        environment.insert("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.errorOccurred.connect(self._failed)
        self.process.finished.connect(self._finished)
        if self._interactive and os.environ.get("DISPLAY"):
            self.process.start(sys.executable, ["-m", "phimthai.feedback", "--overlay"])
        elif self._interactive:
            self.popup_error = "Small left-side popup requires XWayland/XCB; no centered fallback was opened"
            QTimer.singleShot(0, lambda: self.unavailable.emit(self.popup_error))
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def _output(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                report = json.loads(line)
            except ValueError:
                continue
            if report.get("event") == "ready":
                self._ready = True
                self._send(self._pending)
            else:
                self.last_report = report

    def _stderr(self):
        message = bytes(self.process.readAllStandardError()).decode(errors="replace").strip()
        if message:
            self.popup_error = message[-1000:]

    def _failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.popup_error = "Popup helper could not start; check the XWayland/XCB installation"
            self.unavailable.emit(self.popup_error)

    def _finished(self, code, _status):
        self._ready = False
        if not self._closed and code:
            self.popup_error = self.popup_error or "Popup helper stopped; check XWayland/XCB availability"
            self.unavailable.emit(self.popup_error)

    def _send(self, payload):
        self._pending = payload
        if self._ready and not self._closed:
            self.process.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())

    def _show(self, state, **values):
        self._send(dict(state=state if self.popup_enabled else "idle",
                        profile=self._profile, **values))

    def configure(self, *, sound_enabled=None, popup_enabled=None, profile=None):
        if self._closed:
            return
        if sound_enabled is not None:
            self.sound_enabled = bool(sound_enabled)
            if not self.sound_enabled:
                self._stop_sounds()
        if popup_enabled is not None:
            self.popup_enabled = bool(popup_enabled)
            self._show(self._phase)
        if profile is not None:
            self.set_profile(profile)

    def set_profile(self, label):
        if self._closed:
            return
        value = str(label)
        self._profile = {"smart": "MIX", "Smart Mix": "MIX", "raw": "RAW", "Raw": "RAW",
                         "th_to_eng": "TH>ENG", "TH → ENG": "TH>ENG"}.get(value, value[:8])
        self._show(self._phase)

    def _stop_sounds(self):
        for sound in self.sounds.values():
            sound.stop()

    def _play(self, name):
        if self.sound_enabled and self._interactive and not self._closed:
            self._stop_sounds()
            self.sounds[name].play()

    def listening(self):
        if self._closed:
            return
        if self._phase != "listening":
            self._play("start")
        self._phase = "listening"
        self._show("listening")

    def tick(self, seconds):
        if self._phase == "listening" and not self._closed:
            self._show("listening", seconds=max(0, int(seconds)))

    def processing(self):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._phase = "processing"
        self._show("processing")

    def success(self):
        if self._closed:
            return
        self._phase = "success"
        self._show("success")

    def typing(self):
        if self._closed:
            return
        self._play("ready")
        self._phase = "typing"
        self._show("typing")

    def error(self, message):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._phase = "error"
        self._show("error", message=" ".join(str(message).split())[:220])

    def mode(self, label):
        if self._closed:
            return
        self._play("mode")
        self.set_profile(label)
        if self._phase not in {"listening", "processing"}:
            self._phase = "mode"
            self._show("mode")

    def cancel(self):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._phase = "idle"
        self._show("idle")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._stop_sounds()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write(b'{"state":"shutdown"}\n')
            self.process.waitForBytesWritten(100)
            if not self.process.waitForFinished(750):
                self.process.kill()
                self.process.waitForFinished(500)
        self._ready = False


def _overlay():
    """Own helper only: no singleton IPC, microphone, clipboard, or other windows."""
    from PySide6.QtCore import QRectF, QSocketNotifier
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QLabel, QWidget

    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName() != "xcb":
        raise RuntimeError("The small left-side HUD requires XWayland/XCB")

    class Overlay(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.BypassWindowManagerHint |
                             Qt.WindowType.WindowDoesNotAcceptFocus |
                             Qt.WindowType.WindowTransparentForInput)
            self.setWindowTitle("PhimThaiMaiPen dictation HUD")
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setFixedSize(200, 52)
            self.setWindowOpacity(.92)
            self.color = QColor("#ff3b30")
            self.title = QLabel("Listening", self)
            self.title.setGeometry(42, 14, 98, 24)
            self.title.setTextFormat(Qt.TextFormat.PlainText)
            self.title.setStyleSheet("color: white; background: transparent; font: 13px sans-serif;")
            self.badge = QLabel("MIX", self)
            self.badge.setGeometry(138, 14, 46, 24)
            self.badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.badge.setTextFormat(Qt.TextFormat.PlainText)
            self.badge.setStyleSheet("color: #bbc4cb; background: transparent; font: 10px sans-serif;")
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.hide)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#3c464b"), 1))
            painter.setBrush(QColor("#1a1a1a"))
            painter.drawRoundedRect(QRectF(2, 2, 196, 48), 16, 16)
            glow = QColor(self.color)
            glow.setAlpha(75)
            painter.setPen(QPen(glow, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(15, 17, 18, 18))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.color)
            painter.drawEllipse(QRectF(19, 21, 10, 10))

        def update_state(self, message):
            state = message.get("state", "idle")
            self.timer.stop()
            if state == "shutdown":
                self.hide()
                app.quit()
                return
            if state == "idle":
                self.hide()
                return
            title, color, duration = {
                "listening": ("Listening", "#ff3b30", 0),
                "processing": ("Thinking", "#49a8ff", 0),
                "success": ("Ready", "#b1edd7", 2000),
                "typing": ("Typing", "#56df7c", 2000),
                "mode": ("Mode", "#b1edd7", 2000),
                "error": ("Error", "#ff9b91", 5000),
            }.get(state, ("Ready", "#bbbbbb", 2000))
            self.color = QColor(color)
            self.title.setText(title)
            self.title.setStyleSheet(f"color: {'#ffffff' if state == 'listening' else color}; background: transparent; font: 13px sans-serif;")
            self.badge.setText(str(message.get("profile", "MIX")))
            self.setAccessibleName(title + " · " + self.badge.text())
            geometry = app.primaryScreen().geometry()
            self.move(geometry.x() + 32, geometry.y() + (geometry.height() - 52) // 2)
            self.show()
            self.update()
            if duration:
                self.timer.start(duration)
            print(json.dumps({"event": "state", "state": state, "visible": self.isVisible(),
                              "profile": self.badge.text(),
                              "x": self.x(), "y": self.y(), "width": self.width(), "height": self.height(),
                              "focused": app.focusWindow() is self.windowHandle(),
                              "native_id": int(self.winId())}), flush=True)

    window = Overlay()
    buffer = bytearray()
    notifier = QSocketNotifier(0, QSocketNotifier.Type.Read)

    def incoming(*_args):
        data = os.read(0, 4096)
        if not data:
            notifier.setEnabled(False)
            app.quit()
            return
        buffer.extend(data)
        while b"\n" in buffer:
            line, _, remaining = buffer.partition(b"\n")
            buffer[:] = remaining
            try:
                window.update_state(json.loads(line))
            except (ValueError, TypeError):
                continue

    notifier.activated.connect(incoming)
    print(json.dumps({"event": "ready", "platform": app.platformName()}), flush=True)
    return app.exec()


if __name__ == "__main__":
    if "--overlay" not in sys.argv:
        raise SystemExit("Use the app to control dictation feedback")
    raise SystemExit(_overlay())
