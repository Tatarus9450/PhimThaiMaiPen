"""Legacy-sized dictation HUD in an isolated XWayland helper, plus local chimes.

A Wayland xdg-toplevel cannot reliably promise nonactivation or placement.
The 240×52 override-redirect XCB surface preserves the original left-side HUD;
the application's main window continues using its native platform.
"""
import json
import math
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication

HUD_WIDTH, HUD_HEIGHT, HUD_MARGIN = 240, 52, 32
LEVEL_INTERVAL = 1 / 15  # Mic level messages to the helper are capped at 15/s.
FONT_FAMILIES = ["Noto Sans Thai", "IBM Plex Sans Thai", "Noto Sans", "sans-serif"]
PREPARING_WHILE_LISTENING = "โมเดลกำลังโหลด พูดต่อได้เลย"
PREPARING_WHILE_PROCESSING = "โมเดลกำลังโหลด…"


def _env_reduced_motion():
    return os.environ.get("PHIMTHAI_REDUCED_MOTION", "").strip().lower() in {"1", "true", "yes", "on"}


def _clean(text, limit=220):
    return " ".join(str(text).split())[:limit]


class DictationFeedback(QObject):
    unavailable = Signal(str)

    def __init__(self, parent=None, *, sound_enabled=True, popup_enabled=True, reduced_motion=None):
        super().__init__(parent)
        self.sound_enabled = bool(sound_enabled)
        self.popup_enabled = bool(popup_enabled)
        self.reduced_motion = _env_reduced_motion() if reduced_motion is None else bool(reduced_motion)
        self._phase = "idle"
        self._profile = "MIX"
        self._fields = {}  # Values belonging to the current phase (message, hint, count…).
        self._seconds = 0
        self._level = 0
        self._preparing = ""  # Non-empty while the model is loading.
        self._clock = time.monotonic
        self._level_sent = -math.inf
        self._level_timer = QTimer(self)
        self._level_timer.setSingleShot(True)
        self._level_timer.timeout.connect(self._flush_level)
        self._closed = False
        self._ready = False
        self._buffer = b""
        self._pending = {"state": "idle", "profile": self._profile}
        self.last_payload = dict(self._pending)
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
        self.last_payload = payload
        if self._ready and not self._closed:
            self.process.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())

    def _show(self, state, **values):
        self._send(dict(state=state if self.popup_enabled else "idle",
                        profile=self._profile, reduced_motion=self.reduced_motion, **values))

    def _render(self):
        """Send the complete current phase so any redraw (profile, popup toggle) is lossless."""
        values = dict(self._fields)
        if self._phase == "listening":
            values.update(seconds=self._seconds, level=self._level)
            if self._preparing:
                values["detail"] = PREPARING_WHILE_LISTENING
            self._level_sent = self._clock()
            self._level_timer.stop()
        elif self._phase in {"processing", "queued"} and self._preparing:
            values["detail"] = PREPARING_WHILE_PROCESSING
        self._show(self._phase, **values)

    def _enter(self, phase, **fields):
        self._phase = phase
        self._fields = fields
        self._render()

    def configure(self, *, sound_enabled=None, popup_enabled=None, profile=None, reduced_motion=None):
        if self._closed:
            return
        if sound_enabled is not None:
            self.sound_enabled = bool(sound_enabled)
            if not self.sound_enabled:
                self._stop_sounds()
        changed = False
        if popup_enabled is not None:
            self.popup_enabled = bool(popup_enabled)
            changed = True
        if reduced_motion is not None:
            self.reduced_motion = bool(reduced_motion)
            changed = True
        if profile is not None:
            self.set_profile(profile)
        elif changed:
            self._render()

    def set_profile(self, label):
        if self._closed:
            return
        value = str(label)
        self._profile = {"smart": "MIX", "Smart Mix": "MIX", "raw": "RAW", "Raw": "RAW",
                         "th_to_eng": "TH>ENG", "TH → ENG": "TH>ENG"}.get(value, value[:8])
        self._render()

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
            self._seconds = 0
            self._level = 0
        self._enter("listening")

    def tick(self, seconds):
        if self._phase == "listening" and not self._closed:
            self._seconds = max(0, int(seconds))
            self._render()

    def level(self, value):
        """Live 0–100 microphone level; sends to the helper at most 15 times a second."""
        if self._closed:
            return
        try:
            self._level = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return
        if self._phase != "listening":
            return
        wait = LEVEL_INTERVAL - (self._clock() - self._level_sent)
        if wait <= 0:
            self._render()
        elif not self._level_timer.isActive():
            self._level_timer.start(max(1, math.ceil(wait * 1000)))

    def _flush_level(self):
        if self._phase == "listening" and not self._closed:
            self._render()

    def preparing(self, text="กำลังเตรียมโมเดล…"):
        """Model cold start. While listening it only adds a secondary hint line."""
        if self._closed:
            return
        self._preparing = _clean(text) or "กำลังเตรียมโมเดล…"
        if self._phase in {"listening", "processing", "queued"}:
            self._render()
        else:
            self._enter("preparing", message=self._preparing)

    def model_ready(self):
        if self._closed or not self._preparing:
            return
        self._preparing = ""
        if self._phase == "preparing":
            self._enter("idle")
        else:
            self._render()

    def processing(self):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._enter("processing")

    def queued(self, count):
        """A finished recording waits behind an earlier job: "รอคิว N งาน"."""
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        count = max(1, int(count))
        self._enter("queued", count=count, message=f"รอคิว {count} งาน")

    def success(self):
        if self._closed:
            return
        self._enter("success")

    def _ready_chime(self):
        # typing()/pasted()/copied() all mean "text delivered": one chime per delivery.
        if self._phase not in {"typing", "pasted", "copied"}:
            self._play("ready")

    def typing(self):
        if self._closed:
            return
        self._ready_chime()
        self._enter("typing")

    def pasted(self):
        if self._closed:
            return
        self._ready_chime()
        self._enter("pasted", message="วางแล้ว")

    def copied(self, hint="คัดลอกแล้ว · กด Ctrl+V เพื่อวาง"):
        if self._closed:
            return
        self._ready_chime()
        self._enter("copied", message=_clean(hint) or "คัดลอกแล้ว")

    def error(self, message, hint=""):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._enter("error", message=_clean(message), hint=_clean(hint))

    def mode(self, label):
        if self._closed:
            return
        self._play("mode")
        self.set_profile(label)
        if self._phase not in {"listening", "processing", "queued", "preparing"}:
            self._enter("mode")

    def cancel(self):
        if self._closed:
            return
        if self._phase == "listening":
            self._play("stop")
        self._enter("idle")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._level_timer.stop()
        self._stop_sounds()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write(b'{"state":"shutdown"}\n')
            self.process.waitForBytesWritten(100)
            if not self.process.waitForFinished(750):
                self.process.kill()
                self.process.waitForFinished(500)
        self._ready = False


# state: (title, accent color, auto-dismiss ms, animated)
STATES = {
    "listening": ("กำลังฟัง", "#ff453a", 0, True),
    "preparing": ("กำลังเตรียมโมเดล…", "#ffb340", 0, True),
    "processing": ("กำลังคิด", "#4aa8ff", 0, True),
    "queued": ("รอคิว", "#4aa8ff", 0, True),
    "success": ("พร้อม", "#5fdd8a", 2000, False),
    "typing": ("พิมพ์แล้ว", "#5fdd8a", 2000, False),
    "pasted": ("วางแล้ว", "#5fdd8a", 1200, False),
    "copied": ("คัดลอกแล้ว", "#4aa8ff", 3000, False),
    "mode": ("โหมด", "#b1edd7", 2000, False),
    "error": ("ผิดพลาด", "#ff6b5e", 4000, False),
}


def _make_overlay(app):
    """Build the HUD widget (shared by the helper process and offscreen rendering)."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import QWidget

    def font(pixels, bold=False):
        value = QFont()
        value.setFamilies(FONT_FAMILIES)
        value.setPixelSize(pixels)
        value.setBold(bold)
        return value

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
            self.setFixedSize(HUD_WIDTH, HUD_HEIGHT)
            self.setWindowOpacity(.94)
            self.title_font, self.detail_font, self.badge_font = font(13, True), font(10), font(10, True)
            self.state, self.profile, self.title, self.detail = "idle", "MIX", "", ""
            self.color = QColor(STATES["listening"][1])
            self.seconds, self.level, self.shown_level, self.count = 0, 0, 0.0, 0
            self.reduced_motion, self.animated = False, False
            self.started = time.monotonic()
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.dismiss)
            self.frames = QTimer(self)  # ≤30 fps, only while visible and animated.
            self.frames.setInterval(33)
            self.frames.timeout.connect(self.frame)

        # -- drawing ---------------------------------------------------------
        def phase(self):
            return 0.0 if self.reduced_motion else (time.monotonic() - self.started)

        def frame(self):
            if not self.isVisible():
                self.frames.stop()
                return
            self.shown_level += (self.level - self.shown_level) * .35
            self.update()

        def elided(self, text, painter_font, width):
            return QFontMetrics(painter_font).elidedText(text, Qt.TextElideMode.ElideRight, int(width))

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            width, height = self.width(), self.height()
            painter.setPen(QPen(QColor("#3c464b"), 1))
            painter.setBrush(QColor("#1a1a1a"))
            painter.drawRoundedRect(QRectF(1.5, 1.5, width - 3, height - 3), 16, 16)
            self.draw_icon(painter, QPointF(25, height / 2))
            right = width - 14
            # Badge: profile pill (top-right), timer to its left while listening.
            painter.setFont(self.badge_font)
            metrics = QFontMetrics(self.badge_font)
            badge_width = metrics.horizontalAdvance(self.profile) + 12
            two_lines = self.state == "listening" or bool(self.detail)
            badge = QRectF(right - badge_width, 9 if two_lines else (height - 16) / 2, badge_width, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2b3236"))
            painter.drawRoundedRect(badge, 8, 8)
            painter.setPen(QColor("#bbc4cb"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.profile)
            text_right = badge.left() - 6
            if self.state == "listening":
                clock = "%d:%02d" % divmod(self.seconds, 60)
                painter.setFont(self.title_font)
                clock_width = QFontMetrics(self.title_font).horizontalAdvance(clock)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(text_right - clock_width, 8, clock_width, 18),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, clock)
                text_right -= clock_width + 6
            left = 44
            if self.state == "listening":
                title_rect = QRectF(left, 8, text_right - left, 18)
            elif self.detail:
                title_rect = QRectF(left, 8, text_right - left, 18)
            else:
                title_rect = QRectF(left, 0, text_right - left, height)
            painter.setFont(self.title_font)
            painter.setPen(QColor("#ffffff") if self.state == "listening" else self.color)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self.elided(self.title, self.title_font, title_rect.width()))
            if self.state == "listening":
                bar_top = 30 if not self.detail else 28
                self.draw_level(painter, QRectF(left, bar_top, right - left, 4))
            if self.detail:
                detail_rect = QRectF(left, 31 if self.state != "listening" else 33, right - left, 14)
                painter.setFont(self.detail_font)
                painter.setPen(QColor("#ffcf7a") if self.state == "listening" else QColor("#c3cbd1"))
                painter.drawText(detail_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 self.elided(self.detail, self.detail_font, detail_rect.width()))

        def draw_level(self, painter, rect):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#30363a"))
            painter.drawRoundedRect(rect, 2, 2)
            value = self.level if self.reduced_motion else self.shown_level
            filled = rect.width() * max(0.0, min(100.0, value)) / 100
            if filled >= 1:
                painter.setBrush(QColor("#ff453a") if value > 92 else QColor("#5fdd8a"))
                painter.drawRoundedRect(QRectF(rect.left(), rect.top(), filled, rect.height()), 2, 2)

        def draw_icon(self, painter, center):
            color, state, t = QColor(self.color), self.state, self.phase()
            cx, cy = center.x(), center.y()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if state == "listening":
                pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 1.4)
                glow = QColor(color)
                glow.setAlpha(int(60 + 90 * pulse) if not self.reduced_motion else 90)
                painter.setPen(QPen(glow, 1.5))
                radius = 9 + 2.5 * pulse if not self.reduced_motion else 10
                painter.drawEllipse(center, radius, radius)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 5.5, 5.5)
            elif state == "preparing":
                track = QColor(color)
                track.setAlpha(60)
                painter.setPen(QPen(track, 2.5))
                painter.drawEllipse(center, 9, 9)
                pen = QPen(color, 2.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                start = int(-(t * 360) % 360 * 16)
                painter.drawArc(QRectF(cx - 9, cy - 9, 18, 18), start, 100 * 16)
            elif state in {"processing", "queued"}:
                painter.setPen(Qt.PenStyle.NoPen)
                for index in range(3):
                    dot = QColor(color)
                    wave = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 1.1 - index * .9)
                    dot.setAlpha(int(90 + 165 * wave) if not self.reduced_motion else 220)
                    painter.setBrush(dot)
                    lift = 0 if self.reduced_motion else 2 * wave
                    painter.drawEllipse(QPointF(cx - 7 + index * 7, cy - lift), 2.6, 2.6)
            elif state in {"success", "typing", "pasted"}:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 10, 10)
                path = QPainterPath(QPointF(cx - 4.5, cy + .3))
                path.lineTo(cx - 1.2, cy + 3.6)
                path.lineTo(cx + 4.8, cy - 3.4)
                pen = QPen(QColor("#10261a"), 2.2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            elif state == "copied":
                pen = QPen(color, 1.8)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawRoundedRect(QRectF(cx - 6, cy - 7, 12, 15), 2, 2)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(cx - 3, cy - 9, 6, 4), 1, 1)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(QPointF(cx - 3, cy - 1), QPointF(cx + 3, cy - 1))
                painter.drawLine(QPointF(cx - 3, cy + 3), QPointF(cx + 2, cy + 3))
            elif state == "error":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 10, 10)
                painter.setBrush(QColor("#2a0d0a"))
                painter.drawRoundedRect(QRectF(cx - 1.3, cy - 6, 2.6, 7.5), 1.2, 1.2)
                painter.drawEllipse(QPointF(cx, cy + 4.3), 1.5, 1.5)
            else:  # mode and anything else: ring with a centre dot.
                painter.setPen(QPen(color, 2))
                painter.drawEllipse(center, 8.5, 8.5)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 3, 3)

        # -- protocol --------------------------------------------------------
        def report(self, state):
            handle = self.windowHandle()
            print(json.dumps({"event": "state", "state": state, "visible": self.isVisible(),
                              "profile": self.profile, "title": self.title, "detail": self.detail,
                              "seconds": self.seconds, "level": self.level, "count": self.count,
                              "animated": self.frames.isActive(), "reduced_motion": self.reduced_motion,
                              "x": self.x(), "y": self.y(), "width": self.width(), "height": self.height(),
                              "focused": self.isVisible() and handle is not None and app.focusWindow() is handle,
                              "native_id": int(self.winId()) if handle is not None else 0},
                             ensure_ascii=False), flush=True)

        def dismiss(self, state="idle"):
            self.timer.stop()
            self.frames.stop()
            self.hide()
            self.report(state)

        def apply(self, message):
            """Update visual fields; returns (state, duration) without showing or reporting."""
            state, previous = str(message.get("state", "idle")), self.state
            self.profile = str(message.get("profile", "MIX"))[:8]
            self.reduced_motion = bool(message.get("reduced_motion", False))
            title, color, duration, animated = STATES.get(state, ("พร้อม", "#bbbbbb", 2000, False))
            text, hint = str(message.get("message", "") or ""), str(message.get("hint", "") or "")
            detail = str(message.get("detail", "") or "")
            if state == "error":
                # One line: message; with a hint, the message becomes the title-line text.
                title, detail = (text or title), (hint or detail)
            elif state in {"preparing", "pasted", "queued"} and text:
                title = text
            elif state == "copied" and text:
                title, _, rest = text.partition(" · ")
                detail = rest or detail
            self.state, self.title, self.detail = state, title, detail
            self.color = QColor(color)
            self.animated = animated and not self.reduced_motion
            try:
                self.seconds = max(0, int(message.get("seconds", 0) or 0))
                self.level = max(0, min(100, int(message.get("level", 0) or 0)))
                self.count = max(0, int(message.get("count", 0) or 0))
            except (TypeError, ValueError):
                pass
            if self.reduced_motion or state != previous:
                self.shown_level = self.level
            name = title + (" · " + detail if detail else "") + " · " + self.profile
            self.setAccessibleName(name)
            return state, duration

        def update_state(self, message):
            previous = self.state
            self.timer.stop()
            state, duration = self.apply(message)
            if state == "shutdown":
                self.dismiss("shutdown")
                app.quit()
                return
            if state == "idle":
                self.dismiss()
                return
            if state != previous or not self.isVisible():
                self.started = time.monotonic()
                self.shown_level = self.level
            geometry = app.primaryScreen().geometry()
            self.move(geometry.x() + HUD_MARGIN, geometry.y() + (geometry.height() - HUD_HEIGHT) // 2)
            self.show()
            if self.animated:
                if not self.frames.isActive():
                    self.frames.start()
            else:
                self.frames.stop()
            self.update()
            if duration:
                self.timer.start(duration)
            self.report(state)

    return Overlay()


def _overlay(*, _allow_headless=False):
    """Own helper only: no singleton IPC, microphone, clipboard, or other windows."""
    from PySide6.QtCore import QSocketNotifier

    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName() != "xcb" and not (
            _allow_headless and app.platformName() in {"offscreen", "minimal"}):
        raise RuntimeError("The small left-side HUD requires XWayland/XCB")

    window = _make_overlay(app)
    buffer = bytearray()
    notifier = QSocketNotifier(0, QSocketNotifier.Type.Read)

    def incoming(*_args):
        data = os.read(0, 4096)
        if not data:
            notifier.setEnabled(False)
            window.dismiss("shutdown")
            app.quit()
            return
        buffer.extend(data)
        while b"\n" in buffer:
            line, _, remaining = buffer.partition(b"\n")
            buffer[:] = remaining
            try:
                window.update_state(json.loads(line))
            except (ValueError, TypeError, AttributeError):
                continue

    notifier.activated.connect(incoming)
    print(json.dumps({"event": "ready", "platform": app.platformName()}), flush=True)
    return app.exec()


if __name__ == "__main__":
    if "--overlay" not in sys.argv:
        raise SystemExit("Use the app to control dictation feedback")
    raise SystemExit(_overlay())
