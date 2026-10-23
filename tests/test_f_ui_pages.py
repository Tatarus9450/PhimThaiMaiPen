import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog

from phimthai.models import CATALOG
from phimthai.settings import Settings
from phimthai.ui import Check, DiagnosticsPage, ModelsPage, SettingsPage, SetupWizard
from phimthai.ui.settings_page import hotkey_error, hotkey_to_text


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def recorder(signal):
    calls = []
    signal.connect(lambda *args: calls.append(args))
    return calls


def wait(ms):
    timer = QTimer()
    timer.setSingleShot(True)
    timer.start(ms)
    while timer.isActive():
        QCoreApplication.processEvents()


def test_models_page_states_and_signals(app, monkeypatch):
    page = ModelsPage()
    installed = {"typhoon-realtime": 462_000_000, "whisper-tiny-ov": 48_000_000, "translate-th-en": 1}
    page.refresh(CATALOG, installed, "typhoon-realtime", "qwen-0.6b")
    assert set(page.cards) == set(CATALOG)
    selected = page.cards["typhoon-realtime"]
    assert selected.property("selected") is True and not selected.primary.isEnabled()
    assert selected.primary.text() == "กำลังใช้อยู่"
    assert [chip.text() for chip in selected.chips] == list(CATALOG["typhoon-realtime"].tags)
    assert page.cards["qwen-1.7b"].primary.text() == "ดาวน์โหลด"
    assert page.cards["qwen-0.6b"].primary.text() == "หยุด"
    assert page.cards["whisper-tiny-ov"].primary.text() == "ใช้โมเดลนี้"
    assert page.cards["whisper-tiny-ov"].beta_badge is not None
    assert page.cards["translate-th-en"].parent() is not None
    assert page.translation_list.indexOf(page.cards["translate-th-en"]) >= 0

    downloads, uses, removes, cancels = (recorder(page.download), recorder(page.use),
                                         recorder(page.remove), recorder(page.cancel_download))
    page.cards["qwen-1.7b"].primary.click()
    page.cards["whisper-tiny-ov"].primary.click()
    page.cards["qwen-0.6b"].primary.click()
    page.cards["whisper-tiny-ov"].remove_action.trigger()
    page.cards["whisper-tiny-ov"].repair_action.trigger()
    assert downloads == [("qwen-1.7b",), ("whisper-tiny-ov",)]
    assert uses == [("whisper-tiny-ov",)] and removes == [("whisper-tiny-ov",)] and cancels == [()]

    page.set_progress("qwen-0.6b", 42, "42%")
    assert page.cards["qwen-0.6b"].progress.value() == 42
    page.set_progress("qwen-0.6b", None, "กำลังตรวจไฟล์")
    assert page.cards["qwen-0.6b"].progress.maximum() == 0
    page.set_message("ผิดพลาด", error=True)
    assert page.message.property("error") is True and not page.message.isHidden()

    imports = recorder(page.import_folder)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "/tmp/model"))
    page.import_button.click()
    assert imports == [("/tmp/model",)]


def test_local_model_offers_no_download(app):
    from dataclasses import replace
    spec = replace(CATALOG["qwen-0.6b"], id="local-x", origin="local", name="Mine")
    page = ModelsPage()
    page.refresh({"local-x": spec}, {}, "typhoon-realtime", None)
    card = page.cards["local-x"]
    assert card.primary is None and not card.repair_action.isVisible()


def test_settings_debounce_emits_valid_settings(app):
    page = SettingsPage(Settings(), os.cpu_count() or 1)
    changes = recorder(page.changed)
    page.set_settings(Settings(keep_history=True))
    wait(450)
    assert changes == []  # set_settings never emits
    page.paste_review.setChecked(True)
    page.vad.setChecked(False)
    assert changes == []
    wait(450)
    assert len(changes) == 1
    new = changes[0][0]
    assert isinstance(new, Settings) and new.paste_mode == "review" and new.vad is False
    assert new.keep_history is True
    new.validate()


def test_settings_invalid_hotkey_does_not_emit(app):
    page = SettingsPage(Settings(), os.cpu_count() or 1)
    changes = recorder(page.changed)
    page.hotkey.setKeySequence(QKeySequence("H"))
    wait(450)
    assert changes == []
    assert not page.hotkey_error.isHidden()
    page.hotkey.setKeySequence(QKeySequence("Meta+J"))
    wait(450)
    assert changes and changes[-1][0].hotkey == "Meta+J"
    assert page.hotkey_error.isHidden()


def test_hotkey_helpers():
    assert hotkey_to_text(QKeySequence("Meta+H")) == "Meta+H"
    assert hotkey_error("Meta+H") == ""
    assert hotkey_error("Shift+H") and hotkey_error("") and hotkey_error("Ctrl+Shift")


def test_settings_buttons_and_setters(app):
    page = SettingsPage(Settings(), 4)
    shortcut, paste, clear, reduced = (recorder(page.enable_shortcut), recorder(page.enable_paste),
                                       recorder(page.clear_history), recorder(page.reduced_transparency_toggled))
    page.enable_shortcut_button.click()
    page.enable_paste_button.click()
    page.clear_history_button.click()
    page.reduced_transparency.setChecked(True)
    assert shortcut == [("Meta+H",)] and paste == [(True,)] and clear == [()] and reduced == [(True,)]
    page.set_microphones([("USB", "usb")], "usb")
    assert page.microphone.currentData() == "usb"
    page.set_npu_available(False)
    assert not page.device.model().item(page.device.findData("npu")).isEnabled()
    page.set_language_thai_only(True)
    assert not page.language_hint.isHidden()
    page.device.setCurrentIndex(page.device.findData("gpu"))
    assert not page.beta_warning.isHidden()
    page.set_saved_indicator("บันทึกแล้ว ✓")
    assert not page.saved_indicator.isHidden()
    assert page.threads.maximum() == 4


def test_diagnostics_rows_and_action(app):
    page = DiagnosticsPage()
    actions, refreshes, copies = recorder(page.action), recorder(page.refresh), recorder(page.copy_report)
    page.set_checks([Check("mic", "ไมค์", True, "ok"), Check("model", "โมเดล", False, "หาย", "ดาวน์โหลด", "download"),
                     Check("x", "อื่น ๆ", None, "")])
    assert [row.property("state") for row in page.rows] == ["ok", "fail", "unknown"]
    assert [row.icon.text() for row in page.rows] == ["✓", "✕", "?"]
    page.rows[1].action_button.click()
    page.refresh_button.click()
    page.copy_button.click()
    assert actions == [("download",)] and refreshes == [()] and copies == [()]
    page.set_raw("raw text")
    assert page.raw.toPlainText() == "raw text" and page.raw.isReadOnly()


def test_wizard_progression(app):
    wizard = SetupWizard()
    assert wizard.objectName() == "setupWizard" and wizard.current_step() == 1
    finished, skips, downloads = recorder(wizard.finished), recorder(wizard.skip), recorder(wizard.download)
    wizard.set_model("Typhoon", 0.462, False)
    wizard.download_button.click()
    assert downloads == [()] and not wizard.done[0]
    wizard.set_progress(None, "เริ่ม")
    assert wizard.stop_button.isVisibleTo(wizard) and not wizard.download_button.isVisibleTo(wizard)
    wizard.set_model("Typhoon", 0.462, True)
    assert wizard.done[0] and wizard.next_button.property("primary") is True
    wizard.next_button.click()
    assert wizard.current_step() == 2
    wizard.set_level(5)
    assert not wizard.done[1]
    wizard.set_level(30)
    assert wizard.done[1]
    wizard.next()
    wizard.set_permissions("พร้อม", True, False)
    assert not wizard.done[2]
    wizard.set_permissions("พร้อม", True, True)
    assert wizard.done[2]
    wizard.next()
    assert wizard.current_step() == 4 and wizard.next_button.text() == "เสร็จสิ้น"
    wizard.set_hotkey("Meta+J")
    assert "Meta+J" in wizard.try_instructions.text()
    wizard.try_field.setPlainText("สวัสดี")
    assert wizard.done[3]
    wizard.next_button.click()
    wizard.skip_button.click()
    assert finished == [()] and skips == [()]
    wizard.go_to(1)
    assert wizard.current_step() == 1 and not wizard.back_button.isEnabled()
    wizard.go_to(99)
    assert wizard.current_step() == 4


def test_cpu_first_models_have_no_beta_badge(app):
    from phimthai.models import CATALOG
    from phimthai.ui import ModelsPage
    page = ModelsPage()
    page.refresh(CATALOG, {key: 0 for key in CATALOG}, "typhoon-realtime", None)
    assert page.cards["typhoon-realtime"].beta_badge is None
    assert page.cards["qwen-0.6b"].beta_badge is None
