"""Temporary clipboard offers preserve all MIME data and concurrent user copies.

Wayland compositors reject a selection set by a client without keyboard focus,
which is exactly the case after a global-shortcut dictation. Then the offer is
made through wl-clipboard (data-control protocol), which KWin accepts from
unfocused clients. ``mode`` reports which path holds the offer.
"""
import os
import select
import shutil
import subprocess
import time
import uuid
from PySide6.QtCore import QMimeData, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

TOKEN_TYPE = "application/x-phimthai-transaction"
UTF8 = "text/plain;charset=utf-8"
TEXT_TYPES = (UTF8, "text/plain", "UTF8_STRING", "STRING", "TEXT")
SNAPSHOT_LIMIT = 16 * 1024 * 1024
TIMEOUT = 2


def is_wayland():
    return QGuiApplication.platformName().startswith("wayland")


def _read(args, limit=SNAPSHOT_LIMIT, timeout=TIMEOUT):
    """Run a short wl-paste command; None on failure, timeout or oversize."""
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        return None
    chunks, size, deadline = [], 0, time.monotonic() + timeout
    try:
        descriptor = process.stdout.fileno()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
                return None
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                return None
            chunks.append(chunk)
        if process.wait(max(0.1, deadline - time.monotonic())) != 0:
            return None
        return b"".join(chunks)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def _restorable_type(formats):
    for name in TEXT_TYPES:
        if name in formats:
            return name
    for name in formats:
        if "/" in name and not name.startswith(("application/x-kde", TOKEN_TYPE)):
            return name
    return None


class ClipboardTransaction(QObject):
    restored = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.previous = None
        self.token = None
        self.offered = None
        self.mode = None  # "qt" | "wl-copy" | "failed" after offer()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.restore)

    def offer(self, text):
        """Offer text for pasting; False means nothing could be placed."""
        self.restore()
        clipboard = QGuiApplication.clipboard()
        self.previous = self._snapshot(clipboard)
        self.token = uuid.uuid4().hex.encode()
        self.offered = text
        wayland = is_wayland()
        # An unfocused Wayland client's selection is cancelled by the
        # compositor although Qt briefly reports ownership; skip it.
        if not wayland or QGuiApplication.focusWindow() is not None:
            mime = QMimeData()
            mime.setText(text)
            mime.setData("x-kde-passwordManagerHint", b"secret")
            mime.setData(TOKEN_TYPE, self.token)
            clipboard.setMimeData(mime)
            if self._qt_owns():
                self.mode = "qt"
                return True
        if wayland and self._wl_copy(text.encode(), UTF8, sensitive=True):
            self.mode = "wl-copy"
            return True
        self.mode = "failed"
        return False

    def _snapshot(self, clipboard):
        previous = QMimeData()
        old = clipboard.mimeData()
        if old and old.formats():
            for fmt in old.formats():
                previous.setData(fmt, old.data(fmt))
            return previous
        # Qt cannot read another client's selection while unfocused. Never ask
        # wl-paste while this process owns it: we would be the blocked server.
        if is_wayland() and not clipboard.ownsClipboard() and shutil.which("wl-paste"):
            listed = _read(["wl-paste", "--list-types"], limit=65536)
            formats = listed.decode(errors="replace").split() if listed else []
            name = _restorable_type(formats)
            if name:
                data = _read(["wl-paste", "--no-newline", "--type", name])
                if data is not None:
                    previous.setData(name, data)
        return previous

    def _wl_copy(self, data, mime_type=None, sensitive=False):
        program = shutil.which("wl-copy")
        if not program:
            return False
        args = [program, "--clear"] if data is None else [program, "--type", mime_type]
        # wl-copy forks to serve the selection; the parent exits once it is set.
        for extra in (["--sensitive"], []) if sensitive else ([],):
            try:
                subprocess.run(args + extra, input=data, stdin=None if data is not None else subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=True)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    def restore_later(self):
        # A portal acknowledgement means keys were sent, not that the target
        # consumed the offer. Keep it available for slow applications.
        self.timer.start(1500)

    def _qt_owns(self):
        current = QGuiApplication.clipboard().mimeData()
        return bool(self.token and current and bytes(current.data(TOKEN_TYPE)) == self.token)

    def owns_clipboard(self):
        if not self.token or self.mode == "failed":
            return False
        if self.mode != "wl-copy":
            return self._qt_owns()
        # A later copy inside this app is not ours, and reading it would block.
        if QGuiApplication.clipboard().ownsClipboard() or not shutil.which("wl-paste"):
            return False
        current = _read(["wl-paste", "--no-newline", "--type", UTF8], limit=len(self.offered.encode()) + 16)
        return current is not None and current.decode(errors="replace") == self.offered

    def restore(self):
        self.timer.stop()
        if self.previous is None:
            return
        clipboard = QGuiApplication.clipboard()
        if self.owns_clipboard():
            if not is_wayland() or QGuiApplication.focusWindow() is not None:
                clipboard.setMimeData(self.previous)
            else:
                name = _restorable_type(self.previous.formats())
                if not (self._wl_copy(bytes(self.previous.data(name)), name) if name else self._wl_copy(None)):
                    clipboard.setMimeData(self.previous)
        self.previous = None
        self.token = None
        self.offered = None
        self.restored.emit()
