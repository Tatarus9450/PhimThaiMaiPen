#!/usr/bin/env python3
"""Interactive desktop acceptance probe; never approves OS permissions itself.

Run inside the installed Flatpak with this script granted read-only access.
Output contains booleans and portal events, never the user's clipboard data.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QProcess, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget
from phimthai.clipboard import ClipboardTransaction

MARKER = "ทดสอบวางข้อความ Thai + English 2048"


def snapshot():
    mime = QGuiApplication.clipboard().mimeData()
    return {fmt: bytes(mime.data(fmt)) for fmt in mime.formats()} if mime else {}


def mime_from(values):
    mime = QMimeData()
    for fmt, data in values.items():
        mime.setData(fmt, data)
    return mime


class Probe(QWidget):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.events = {"scope": "Interactive Wayland clipboard and portal probe; owned Qt test field; no physical recording", "events": []}
        self.baseline = None
        self.buffer = b""
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_portal)
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.process.start(sys.executable, ["-m", "phimthai.portals"])
        self.clipboard = ClipboardTransaction(self)
        self.clipboard.timer.timeout.disconnect()
        self.clipboard.timer.timeout.connect(self.observe_restore)
        self.setWindowTitle("PhimThaiMaiPen · ทดสอบปุ่มลัดและคลิปบอร์ด")
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        instructions = QLabel("1 · กดอนุญาตวาง แล้วตอบหน้าขอสิทธิ์ของ KDE\n"
                              "2 · กดทดสอบวาง ข้อความตัวอย่างจะลงในช่องของหน้าต่างนี้\n"
                              "3 · เปิดปุ่มลัด แล้วลองกด Ctrl+Alt+Space\n"
                              "แอปบันทึกเฉพาะผลทดสอบ ไม่บันทึกข้อความเดิมในคลิปบอร์ด")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.status = QLabel("รอเริ่มทดสอบ / Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        enable = QPushButton("อนุญาตวาง / Enable paste permission")
        enable.clicked.connect(lambda: self.command("enable_paste"))
        layout.addWidget(enable)
        self.paste = QPushButton("ทดสอบวาง / Test paste")
        self.paste.setEnabled(False)
        self.paste.clicked.connect(self.begin_paste)
        layout.addWidget(self.paste)
        shortcut = QPushButton("เปิดปุ่มลัด / Enable Ctrl+Alt+Space")
        shortcut.clicked.connect(lambda: self.command("shortcuts", trigger="CTRL+ALT+SPACE"))
        layout.addWidget(shortcut)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("ช่องรับข้อความทดสอบ / Test paste destination")
        layout.addWidget(self.editor)
        close = QPushButton("บันทึกผลและปิด / Save and close")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.events["platform"] = QGuiApplication.platformName()
        self.save()

    def save(self):
        self.output.write_text(json.dumps(self.events, ensure_ascii=False, indent=2) + "\n")

    def command(self, action, **kwargs):
        self.process.write((json.dumps(dict(action=action, **kwargs)) + "\n").encode())

    def read_portal(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            self.events["events"].append(event)
            kind = event.get("event")
            if kind == "paste_enabled":
                self.paste.setEnabled(True)
                self.status.setText("อนุญาตแล้ว กดทดสอบวางได้ / Paste permission granted")
            elif kind == "paste_sent":
                self.clipboard.restore_later()
                QTimer.singleShot(1800, self.verify_paste)
            elif kind == "shortcut":
                self.events["shortcut_activated"] = True
                self.status.setText("รับปุ่มลัดจริงแล้ว / Global shortcut activated")
            elif kind == "shortcuts_enabled":
                self.status.setText("ลองกดปุ่มลัด / Press " + event.get("trigger", "configured shortcut"))
            elif kind == "error":
                self.clipboard.restore()
                self.status.setText(event.get("error", "Portal failed"))
            self.save()

    def begin_paste(self):
        self.editor.clear()
        self.editor.setFocus()
        QTimer.singleShot(200, self.send_paste)

    def send_paste(self):
        if not self.isActiveWindow() or not self.editor.hasFocus():
            self.status.setText("คลิกหน้าต่างทดสอบแล้วลองอีกครั้ง / Test window needs focus")
            return
        self.baseline = snapshot()
        self.clipboard.offer(MARKER)
        self.events["baseline_formats"] = list(self.baseline)
        self.events["offer_owned_immediately"] = self.clipboard.owns_clipboard()
        self.command("paste")

    def observe_restore(self):
        self.events["owned_before_restore"] = self.clipboard.owns_clipboard()
        self.events["formats_before_restore"] = list(snapshot())
        self.events["test_window_active_before_restore"] = self.isActiveWindow()
        self.clipboard.restore()

    def verify_paste(self):
        self.events["paste_exactly_once"] = self.editor.toPlainText() == MARKER
        restored = snapshot()
        self.events["clipboard_format_set_identical"] = set(restored) == set(self.baseline)
        self.events["clipboard_restored_all_mime"] = all(restored.get(key) == value for key, value in self.baseline.items())
        self.events["restored_formats"] = list(snapshot())
        self.events["restored_original_formats_match"] = {key: snapshot().get(key) == value for key, value in self.baseline.items()}
        # Emulate a later user copy while an offer is active. Restore only our
        # owned test marker afterwards; a real concurrent copy always wins.
        self.clipboard.offer("temporary offer")
        replacement = QMimeData()
        replacement.setText("newer copy test")
        replacement.setData("x-kde-passwordManagerHint", b"secret")
        replacement.setData("application/x-phimthai-proof", b"owned-new-copy")
        QGuiApplication.clipboard().setMimeData(replacement)
        expected = snapshot()
        self.clipboard.restore()
        self.events["newer_copy_preserved"] = snapshot() == expected
        current = QGuiApplication.clipboard().mimeData()
        if current and bytes(current.data("application/x-phimthai-proof")) == b"owned-new-copy":
            QGuiApplication.clipboard().setMimeData(mime_from(self.baseline))
        self.baseline = None
        self.status.setText("ผลวาง/คืนคลิปบอร์ด/รักษาข้อความใหม่: " +
                            ", ".join(str(self.events[key]) for key in
                                      ("paste_exactly_once", "clipboard_restored_all_mime", "newer_copy_preserved")))
        self.save()

    def closeEvent(self, event):
        self.clipboard.restore()
        self.process.kill()
        self.process.waitForFinished(3000)
        self.events["closed"] = True
        self.save()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    app = QApplication([])
    window = Probe(args.output)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
