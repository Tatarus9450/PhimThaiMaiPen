#!/usr/bin/env python3
"""Render owned, isolated Qt windows without contacting the running app.

Run with the app's Python: scripts/check-ui.py --backend wayland.
No main()/single-instance entry point, microphone, worker, portal, clipboard,
model download or desktop shortcut registration is used. Only our QWidget's
own pixels are saved; this is not a desktop screenshot.
"""
import argparse
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication,
                              QComboBox, QLabel, QLineEdit, QScrollArea, QSpinBox)


class SimulatedMediaDevices(QObject):
    audioInputsChanged = Signal()

    @staticmethod
    def audioInputs():
        return [SimulatedMicrophone()]


class SimulatedMicrophone:
    def id(self):
        return b"ui-validation-microphone"

    def description(self):
        return "ไมโครโฟนจำลอง · UI validation only"


class InertRecorder(QObject):
    failed = Signal(str)
    level = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.media_devices = SimulatedMediaDevices(self)
        self.source = None
        self.frames = 0

    def start(self, *_args, **_kwargs):
        raise AssertionError("UI validation must never record audio")

    def stop(self):
        return False


class InertClipboard(QObject):
    restored = Signal()

    def restore(self):
        pass

    def offer(self, *_args):
        raise AssertionError("UI validation must never access the clipboard")


def simulated_shortcut_status(window):
    window.kde_shortcut_state = {
        "available": True, "active": True, "trigger": "Meta+H",
        "mode_active": True, "mode_trigger": "Meta+Shift+H",
    }
    window.show_shortcut_status()
    return window.kde_shortcut_state


@contextlib.contextmanager
def isolated_window():
    """Use real MainWindow construction/layout with inert external services."""
    from phimthai import app as app_module
    from phimthai.settings import Settings

    with tempfile.TemporaryDirectory(prefix="phimthai-ui-check-") as temporary:
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "XDG_CONFIG_HOME": str(Path(temporary) / "config"),
                "XDG_DATA_HOME": str(Path(temporary) / "data"),
            }))
            for name, value in {
                "Recorder": InertRecorder, "ClipboardTransaction": InertClipboard,
                "QMediaDevices": SimulatedMediaDevices,
            }.items():
                stack.enter_context(patch.object(app_module, name, value))
            stack.enter_context(patch.object(app_module, "load_settings", return_value=Settings()))
            stack.enter_context(patch.object(app_module, "installed_size", return_value=0))
            stack.enter_context(patch.object(app_module, "local_model", return_value=None))
            stack.enter_context(patch.object(app_module, "openvino_devices", return_value=[]))
            stack.enter_context(patch.object(app_module, "inventory", return_value={
                "system": "Linux · simulated diagnostic data", "session": "Wayland",
                "cpu_threads": 6, "npu": [], "openvino_installed": False,
                "openvino_devices": [], "flatpak": False,
            }))
            for target, value in {
                "phimthai.fastflowlm_backend.available": False,
                "phimthai.fastflowlm_backend.runtime_path": None,
                "phimthai.vulkan_backend.runtime_path": None,
                "phimthai.performance.measurements": {},
                "phimthai.kde.shortcut_status": {
                    "available": True, "active": True, "trigger": "Meta+H",
                },
            }.items():
                stack.enter_context(patch(target, return_value=value))
            stack.enter_context(patch.object(app_module.MainWindow, "setup_tray"))
            stack.enter_context(patch.object(app_module.MainWindow, "refresh_shortcut_status",
                                            simulated_shortcut_status))
            stack.enter_context(patch.object(app_module.MainWindow, "portal_command",
                                            side_effect=AssertionError("No desktop portal in UI check")))
            window = app_module.MainWindow()  # Deliberately never call app.main().
            window.setWindowTitle("PhimThaiMaiPen · isolated UI validation")
            try:
                yield window
            finally:
                window.quitting = True
                window.close()
                window.deleteLater()
                QApplication.processEvents()


def widget_label(widget):
    text = widget.text() if isinstance(widget, (QLabel, QAbstractButton, QLineEdit)) else ""
    return {"class": type(widget).__name__, "name": widget.objectName(), "text": text[:100]}


def rect_values(rect):
    return {"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()}


def geometry_report(window, requested):
    """Vertical scrolling is allowed; horizontal page overflow is a failure."""
    rows, issues, scrolls = [], [], []
    navigation = []
    if (window.width(), window.height()) != requested:
        issues.append({"kind": "window_size_changed", "requested": list(requested),
                       "actual": [window.width(), window.height()]})
    for scroll in window.findChildren(QAbstractScrollArea):
        if not scroll.isVisibleTo(window):
            continue
        entry = dict(widget_label(scroll), horizontal_max=scroll.horizontalScrollBar().maximum(),
                     vertical_max=scroll.verticalScrollBar().maximum(),
                     viewport=rect_values(scroll.viewport().rect()))
        scrolls.append(entry)
        if entry["horizontal_max"]:
            issues.append(dict(entry, kind="horizontal_scroll_overflow"))
        if isinstance(scroll, QScrollArea):
            entry["page_auto_fill"] = scroll.widget().autoFillBackground()
            entry["viewport_auto_fill"] = scroll.viewport().autoFillBackground()
            if entry["page_auto_fill"] or entry["viewport_auto_fill"]:
                issues.append(dict(entry, kind="opaque_page_or_viewport"))
    for index in range(window.nav.count()):
        item = window.nav.item(index)
        rectangle = window.nav.visualItemRect(item)
        entry = {"text": item.text(), "rectangle": rect_values(rectangle),
                 "fully_visible": window.nav.viewport().rect().contains(rectangle)}
        navigation.append(entry)
        if not entry["fully_visible"]:
            issues.append(dict(entry, kind="navigation_item_clipped"))
    for widget in (window.shortcut_hint, window.mode_button, window.mode_shortcut_hint):
        if not widget.parentWidget().rect().contains(widget.geometry()):
            issues.append(dict(widget_label(widget), kind="sidebar_control_clipped"))
    for widget in window.findChildren(QObject):
        if not isinstance(widget, (QLabel, QAbstractButton, QLineEdit, QComboBox, QSpinBox)):
            continue
        if not widget.isVisibleTo(window):
            continue
        position = widget.mapTo(window, QPoint())
        rectangle = widget.rect().translated(position)
        entry = dict(widget_label(widget), rectangle=rect_values(rectangle),
                     minimum_hint=[widget.minimumSizeHint().width(), widget.minimumSizeHint().height()])
        if isinstance(widget, QLabel):
            entry["word_wrap"] = widget.wordWrap()
            entry["longest_line_pixels"] = max(
                (widget.fontMetrics().horizontalAdvance(line) for line in widget.text().splitlines()),
                default=0)
            if not widget.wordWrap() and entry["longest_line_pixels"] > widget.contentsRect().width() + 2:
                issues.append(dict(entry, kind="unwrapped_label_text_clipped"))
        # Ignore vertical coordinates: lower controls can be reached by scrolling.
        if rectangle.left() < 0 or rectangle.right() >= window.width():
            issues.append(dict(entry, kind="widget_outside_window_horizontally"))
        rows.append(entry)
    return {"requested_logical_size": list(requested),
            "actual_logical_size": [window.width(), window.height()],
            "device_pixel_ratio": window.devicePixelRatioF(),
            "widgets": rows, "scroll_areas": scrolls, "navigation": navigation,
            "issues": issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("wayland", "offscreen"), default="wayland")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/ui-glass-proof")
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = args.backend
    args.output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("PhimThaiMaiPen UI validation")
    from phimthai.appearance import apply_style

    reports = []
    with isolated_window() as window:
        window.show()
        QTest.qWait(100)
        for scheme_name, scheme in (("dark", Qt.ColorScheme.Dark), ("light", Qt.ColorScheme.Light)):
            application.styleHints().setColorScheme(scheme)
            QTest.qWait(40)
            for reduced in (False, True):
                window.reduced_transparency.setChecked(reduced)
                apply_style(application, reduced_transparency=reduced)
                for width, height in ((1040, 760), (820, 600)):
                    window.resize(width, height)
                    QTest.qWait(100)
                    for index, page_name in enumerate(("transcript", "models", "settings", "diagnostics")):
                        window.nav.setCurrentRow(index)
                        scroll = window.pages.widget(index)
                        scroll.verticalScrollBar().setValue(0)
                        QTest.qWait(50)
                        name = f"{args.backend}-{scheme_name}-{'solid' if reduced else 'glass'}-{width}x{height}-{page_name}"
                        screenshot = (args.output / f"{name}.png").resolve()
                        pixmap = window.grab()
                        if not pixmap.save(str(screenshot)):
                            raise RuntimeError(f"Could not save {screenshot}")
                        report = geometry_report(window, (width, height))
                        report.update(theme=scheme_name, reduced_transparency=reduced, page=page_name,
                                      screenshot=str(screenshot), screenshot_pixels=[pixmap.width(), pixmap.height()],
                                      window_color=application.palette().color(QPalette.ColorRole.Window).name())
                        reports.append(report)
    result = {"platform": application.platformName(), "pid": os.getpid(),
              "scope": "Owned QWidget pixels only; simulated external services; no app singleton, microphone or clipboard",
              "cases": len(reports), "issues": sum(len(row["issues"]) for row in reports), "reports": reports}
    result_path = (args.output / "geometry.json").resolve()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(result_path), "cases": result["cases"], "issues": result["issues"]}))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
