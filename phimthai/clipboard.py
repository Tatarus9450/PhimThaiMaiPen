"""Temporary clipboard offers preserve all MIME data and concurrent user copies."""
import uuid
from PySide6.QtCore import QMimeData, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication


class ClipboardTransaction(QObject):
    restored = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.previous = None
        self.token = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.restore)

    def offer(self, text):
        self.restore()
        clipboard = QGuiApplication.clipboard()
        old = clipboard.mimeData()
        self.previous = QMimeData()
        if old:
            for fmt in old.formats():
                self.previous.setData(fmt, old.data(fmt))
        self.token = uuid.uuid4().hex.encode()
        mime = QMimeData()
        mime.setText(text)
        mime.setData("x-kde-passwordManagerHint", b"secret")
        mime.setData("application/x-phimthai-transaction", self.token)
        clipboard.setMimeData(mime)

    def restore_later(self):
        # A portal acknowledgement means keys were sent, not that the target
        # consumed the offer. Keep it available for slow applications.
        self.timer.start(1500)

    def owns_clipboard(self):
        current = QGuiApplication.clipboard().mimeData()
        return bool(self.token and current and bytes(current.data("application/x-phimthai-transaction")) == self.token)

    def restore(self):
        self.timer.stop()
        if self.previous is None:
            return
        clipboard = QGuiApplication.clipboard()
        if self.owns_clipboard():
            clipboard.setMimeData(self.previous)
        self.previous = None
        self.token = None
        self.restored.emit()
