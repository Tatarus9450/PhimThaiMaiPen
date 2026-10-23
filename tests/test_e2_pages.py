"""PagesMixin wiring, tested against a fake host (independent of MainWindow changes)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from phimthai import app_pages
from phimthai import strings as S
from phimthai.app_pages import PagesMixin
from phimthai.models import CATALOG
from phimthai.settings import Settings, load_settings, save_settings


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    installed = {"typhoon-realtime"}
    monkeypatch.setattr(app_pages, "local_model", lambda model_id, verify=False: tmp_path if model_id in installed else None)
    monkeypatch.setattr(app_pages, "installed_size", lambda model_id: 1000 if model_id in installed else 0)
    return installed


class Jobs:
    busy = False
    warm = False

    def __init__(self):
        self.stopped = 0

    def stop_worker(self):
        self.stopped += 1


class Feedback:
    def __init__(self):
        self.configured = []

    def configure(self, **kwargs):
        self.configured.append(kwargs)

    def set_profile(self, profile):
        pass


class FakeRecorder(QObject):
    level = Signal(int)


class Host(PagesMixin, QMainWindow):
    """Implements just the MainWindow surface PagesMixin relies on, recording calls."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or Settings()
        self.calls = []
        self.jobs = Jobs()
        self.feedback = Feedback()
        self.recorder = FakeRecorder()
        self.recording = False
        self.test_microphone = False
        self.downloading_model = None
        self.download_process = None
        self.download_failure = ""
        self.importing = False
        self.imported_model = None
        self.kde_shortcut_state = {}
        self.portal_shortcut = ""
        self.paste_enabled = False
        self.portal = None
        self.status_text = ""
        self.nav = QListWidget()
        self.nav.addItems(list(S.NAV_PAGES))
        self.pages = QStackedWidget()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.mode_button = QPushButton()
        self.setCentralWidget(self.pages)
        self.page("หน้าแรก", "")
        self.build_models_page()
        self.build_settings_page()
        self.build_diagnostics_page()
        self.build_setup_wizard()

    def page(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(title))
        scroll = QScrollArea()
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return layout

    # --- stubs mirroring MainWindow ---
    def download_model(self, _checked=False, *, model_id=None):
        self.calls.append(("download_model", model_id))

    def cancel_download(self):
        self.calls.append(("cancel_download",))

    def model_details(self, _index):
        pass

    def refresh_models(self):
        self.model_list.clear()
        self.model_list.addItems(list(CATALOG))
        self.calls.append(("refresh_models",))

    def refresh_device_choices(self):
        self.calls.append(("refresh_device_choices",))

    def update_setup_view(self):
        self.calls.append(("update_setup_view",))
        self.sync_setup_wizard()

    def save_setup(self, **changes):
        from dataclasses import replace
        self.settings = replace(self.settings, **changes)
        save_settings(self.settings)
        return True

    def start_model_process(self, arguments):
        self.calls.append(("start_model_process", arguments))

    def refresh_microphones(self):
        self.microphone.clear()
        self.microphone.addItem(S.MIC_SYSTEM_DEFAULT, "")
        self.microphone.addItem("USB Mic", "usb")

    def test_mic(self):
        self.calls.append(("test_mic",))

    def enable_shortcut(self):
        self.calls.append(("enable_shortcut", self.hotkey.text()))

    def portal_command(self, action, **options):
        self.calls.append(("portal_command", action, options))

    def clear_history(self):
        self.calls.append(("clear_history",))

    def set_status(self, text):
        self.status_text = text

    def current_settings(self):
        from dataclasses import replace
        return replace(self.settings, microphone=self.microphone.currentData(), profile=self.profile.currentData(),
                       hotkey=self.hotkey.text(), vad=self.vad.isChecked(),
                       keep_history=self.history.isChecked(), paste_mode=self.paste_mode.currentData())


@pytest.fixture
def host(qapp):
    window = Host()
    yield window
    window.deleteLater()


def test_compat_widgets_exist_but_are_hidden(host):
    for name in ("model_list", "download_progress", "download_status", "download_button", "model_description",
                 "model_technical", "model_beta_warning", "import_button", "microphone", "profile", "language",
                 "device", "threads", "paste_mode", "hotkey", "history", "audio_history", "vad",
                 "reduced_transparency", "popup_enabled", "sound_feedback", "dictionary", "remember_desktop",
                 "shortcut_status", "language_hint", "beta_warning", "preference", "diagnostic_summary", "diagnostics"):
        widget = getattr(host, name)
        assert widget.parentWidget().objectName() == "compatWidgets" and widget.parentWidget().isHidden(), name
    assert host.models_page.isVisibleTo(host.models_page.parentWidget())


def test_models_page_signals_route_to_host(host, isolated, monkeypatch):
    page = host.models_page
    assert set(page.cards) == set(CATALOG)
    assert page.cards["typhoon-realtime"].selected
    page.download.emit("qwen-0.6b")
    page.cancel_download.emit()
    page.import_folder.emit("/tmp/some-model")
    assert ("download_model", "qwen-0.6b") in host.calls and ("cancel_download",) in host.calls
    assert ("start_model_process", ["-m", "phimthai.models", "--import", "/tmp/some-model"]) in host.calls
    assert host.importing and host.models_page.message.text() == S.MODEL_IMPORTING

    # use: not installed → message; installed → saved + selected
    page.use.emit("qwen-0.6b")
    assert host.settings.model == "typhoon-realtime" and page.message.text() == S.MODEL_DOWNLOAD_FIRST
    isolated.add("qwen-0.6b")
    page.use.emit("qwen-0.6b")
    assert host.settings.model == "qwen-0.6b" and load_settings().model == "qwen-0.6b"
    assert host.jobs.stopped == 1 and host.model_list.currentRow() == list(CATALOG).index("qwen-0.6b")
    assert host.models_page.cards["qwen-0.6b"].selected
    assert host.settings_page.language_hint.isHidden()  # Qwen is not Thai-only

    # remove asks first (Thai), then removes with the explicit id
    removed = []
    monkeypatch.setattr(app_pages, "remove", removed.append)
    monkeypatch.setattr(app_pages, "model_dir", lambda model_id: type("P", (), {"exists": lambda self: True})())
    questions = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda parent, title, text: questions.append(text) or QMessageBox.StandardButton.No))
    page.remove.emit("whisper-tiny-ov")
    assert removed == [] and "Whisper Tiny" in questions[0] and "ลบ" in questions[0]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    page.remove.emit("qwen-0.6b")
    assert removed == ["qwen-0.6b"] and host.settings.model_setup == "skipped"


def test_download_progress_is_mirrored(host):
    host.downloading_model = "qwen-1.7b"
    host.download_process = object()
    host.download_progress.setRange(0, 0)
    card = host.models_page.cards["qwen-1.7b"]
    assert card.downloading and card.progress.maximum() == 0
    host.download_progress.setRange(0, 100)
    host.download_progress.setValue(37)
    host.download_status.setText("กำลังดาวน์โหลด 37%")
    card = host.models_page.cards["qwen-1.7b"]
    assert card.progress.value() == 37 and card.status_label.text() == "กำลังดาวน์โหลด 37%"
    host.download_failure = "เครือข่ายขัดข้อง"
    host.download_status.setText("เครือข่ายขัดข้อง")
    assert host.models_page.message.text() == "เครือข่ายขัดข้อง"
    assert host.models_page.message.property("error") is True
    host.download_process = None
    host.downloading_model = None
    host.download_failure = ""
    host.download_progress.setRange(0, 100)
    assert not host.models_page.cards["qwen-1.7b"].downloading


def test_wizard_download_progress_and_skip(host):
    wizard = host.setup_wizard
    assert not wizard.isHidden() or not host.settings.onboarding_done
    wizard.download.emit()
    wizard.choose_model.emit()
    wizard.test_microphone.emit()
    wizard.enable_shortcut.emit()
    wizard.enable_paste.emit()
    assert ("download_model", host.settings.model) in host.calls and host.nav.currentRow() == 1
    assert ("test_mic",) in host.calls and ("enable_shortcut", "Meta+H") in host.calls
    assert ("portal_command", "enable_paste", {"persist": True}) in host.calls
    wizard.microphone_selected.emit("usb")
    assert host.settings.microphone == "usb" and load_settings().microphone == "usb"
    assert host.microphone.currentData() == "usb" and host.settings_page.microphone.currentData() == "usb"

    host.kde_shortcut_state = {"active": True, "trigger": "Meta+H"}
    host.paste_enabled = True
    host.sync_setup_wizard()
    assert wizard.done[0] and wizard.done[2]  # typhoon installed; permissions granted
    assert wizard.shortcut_status.text().startswith("✓")

    wizard.skip.emit()
    assert wizard.isHidden() and host.settings.onboarding_done and load_settings().onboarding_done


def test_settings_autosave_saves_and_syncs_hidden_widgets(host):
    page = host.settings_page
    page.paste_review.setChecked(True)
    page.keep_history.setChecked(True)
    page.profile.setCurrentIndex(page.profile.findData("raw"))
    page.microphone.setCurrentIndex(page.microphone.findData("usb"))
    saved = page.flush()
    assert saved is not None
    assert host.settings.paste_mode == "review" and host.settings.keep_history and host.settings.profile == "raw"
    disk = load_settings()
    assert disk.paste_mode == "review" and disk.keep_history and disk.microphone == "usb"
    assert host.paste_mode.currentData() == "review" and host.history.isChecked()
    assert host.profile.currentData() == "raw" and host.microphone.currentData() == "usb"
    assert host.current_settings().paste_mode == "review"
    assert host.mode_button.text() == S.PROFILE_NAMES["raw"]
    assert host.feedback.configured and page.saved_indicator.text() == "บันทึกแล้ว ✓"
    assert not any(call[0] == "enable_shortcut" for call in host.calls)

    # Hotkey change re-enables the shortcut once, using the new trigger.
    page._set_hotkey_text("Meta+J", edit=True)
    page.flush()
    assert host.calls.count(("enable_shortcut", "Meta+J")) == 1 and host.settings.hotkey == "Meta+J"
    # Enable button with a pending hotkey edit does not register twice.
    page._set_hotkey_text("Meta+K", edit=True)
    page.enable_shortcut.emit(page.hotkey_text())
    assert [c for c in host.calls if c[0] == "enable_shortcut"][-1] == ("enable_shortcut", "Meta+K")
    assert host.calls.count(("enable_shortcut", "Meta+K")) == 1


def test_settings_merge_keeps_host_only_fields(host, isolated):
    isolated.add("qwen-0.6b")
    host.use_model_id("qwen-0.6b")
    page = host.settings_page
    page.vad.setChecked(False)
    page.flush()
    assert host.settings.model == "qwen-0.6b" and host.settings.vad is False


def test_settings_remember_desktop_off_forgets(host, monkeypatch, tmp_path):
    from phimthai import portals
    state = tmp_path / "desktop-sessions.json"
    state.write_text("{}")
    monkeypatch.setattr(portals, "state_path", lambda: state)
    host.portal = object()
    host.settings_page.remember_desktop.setChecked(False)
    host.settings_page.flush()
    assert not state.exists() and ("portal_command", "forget", {}) in host.calls


def test_settings_other_signals(host):
    page = host.settings_page
    page.test_microphone.emit()
    page.clear_history.emit()
    page.enable_paste.emit(False)
    page.refresh_microphones.emit()
    assert ("test_mic",) in host.calls and ("clear_history",) in host.calls
    assert ("portal_command", "enable_paste", {"persist": False}) in host.calls
    assert page.microphone.findData("usb") >= 0


def test_cycle_profile_style_change_reaches_page(host):
    host.profile.setCurrentIndex(host.profile.findData("th_to_eng"))
    assert host.settings_page.profile.currentData() == "th_to_eng"
    assert not host.settings_page._timer.isActive()


def test_shortcut_status_mirrored(host):
    host.kde_shortcut_state = {"active": True, "trigger": "Meta+H"}
    host.shortcut_status.setText("Meta+H · พร้อมเริ่มและหยุดพูด")
    assert host.settings_page.shortcut_status.text().startswith("✓ Meta+H")
    assert host.settings_page.shortcut_status.property("ok") is True


def test_level_routing_only_while_testing(host):
    host.recorder.level.emit(60)
    assert host.settings_page.mic_level.value() == 0
    host.test_microphone = True
    host.recorder.level.emit(60)
    assert host.settings_page.mic_level.value() == 60 and host.setup_wizard.level.value() == 60
    assert host.setup_wizard.done[1]


def test_diagnostics_checks_and_actions(host, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(app_pages.shutil, "which", lambda name: None)
    from phimthai import kde, logs
    monkeypatch.setattr(logs, "detect_duplicate_installs", lambda: ["a", "b"])
    monkeypatch.setattr(kde, "find_conflicts", lambda: (_ for _ in ()).throw(OSError("sandbox")))
    checks = {check.id: check for check in host.refresh_diagnostics_page()}
    assert checks["model"].ok is True and not checks["model"].action_id
    assert checks["worker"].ok is None
    assert checks["shortcut"].ok is False and checks["shortcut"].action_id == "shortcut"
    assert checks["paste"].ok is False and checks["paste"].action_id == "paste"
    assert checks["wl_copy"].ok is False
    assert checks["installs"].ok is False
    assert checks["conflicts"].ok is None
    assert checks["log"].ok is True
    assert len(host.diagnostics_page.rows) == len(checks)
    assert json.loads(host.diagnostics_page.raw.toPlainText())["cpu_threads"] == os.cpu_count()

    host.settings.model = "qwen-1.7b"
    host.paste_enabled = True
    host.portal_shortcut = "Meta+H"
    host.jobs.warm = True
    monkeypatch.delenv("XDG_SESSION_TYPE")
    checks = {check.id: check for check in host.refresh_diagnostics_page()}
    assert checks["model"].ok is False and checks["model"].action_id == "download"
    assert checks["paste"].ok and checks["shortcut"].ok and checks["worker"].ok is True
    assert "wl_copy" not in checks

    page = host.diagnostics_page
    for action in ("download", "shortcut", "paste", "settings"):
        page.action.emit(action)
    assert ("download_model", "qwen-1.7b") in host.calls and ("enable_shortcut", "Meta+H") in host.calls
    assert ("portal_command", "enable_paste", {"persist": True}) in host.calls
    assert host.nav.currentRow() == 2
    page.action.emit("models")
    assert host.nav.currentRow() == 1
    model_row = next(row for row in page.rows if row.check.id == "model")
    model_row.action_button.click()
    assert host.calls.count(("download_model", "qwen-1.7b")) == 2


def test_copy_report_puts_text_on_clipboard(host, monkeypatch):
    from phimthai import logs
    seen = {}
    monkeypatch.setattr(logs, "diagnostic_report", lambda extra=None: seen.update(extra) or "REPORT\n" + str(extra))
    host.dictionary.setPlainText("secret words")
    host.diagnostics_page.copy_report.emit()
    text = QGuiApplication.clipboard().text()
    assert text.startswith("REPORT") and "secret words" not in text
    assert seen["model"] == host.settings.model and "checks" in seen
    assert host.status_text == "คัดลอกรายงานแล้ว"
