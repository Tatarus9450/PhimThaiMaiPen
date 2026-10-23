"""Glue between MainWindow and the decoupled pages in ``phimthai.ui``.

``PagesMixin`` is inherited by MainWindow (``class MainWindow(PagesMixin, QMainWindow)``).
It builds ModelsPage / SettingsPage / DiagnosticsPage / SetupWizard and routes
their signals to the existing MainWindow methods.

Backward compatibility: MainWindow code (and its tests) still reads and writes
the old page widgets (``model_list``, ``download_progress``, ``download_status``,
``microphone``, ``hotkey`` ...). They are still created, but hidden in a
container that is never added to a layout. Updates to them are mirrored into
the new pages automatically:

* ``download_progress`` value/range changes and ``download_status`` /
  ``shortcut_status`` text changes (``_MirrorLabel``) trigger
  ``sync_models_page`` / ``sync_setup_wizard`` / the settings shortcut status.
* ``profile`` (hidden) index changes, e.g. from ``cycle_profile``, are pushed
  into the visible settings page.

The host only has to call a few hooks for state that has no widget to watch
(see ``refresh_models_page``, ``sync_setup_wizard``, ``sync_device_choices_page``,
``flush_pages``).
"""
import json
import logging
import os
import shutil
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
                               QWidget)

from . import strings as S
from .appearance import apply_style
from .models import CATALOG, installed_size, local_model, model_dir, remove
from .settings import DEFAULT_MODEL, save_settings
from .ui import Check, DiagnosticsPage, ModelsPage, SettingsPage, SetupWizard

LOG = logging.getLogger("phimthai.app")

# Settings fields owned by the settings page (SettingsPage.values() keys).
PAGE_FIELDS = ("microphone", "profile", "language", "vad", "dictionary", "paste_mode", "hotkey",
               "reduced_transparency", "popup_enabled", "sound_feedback", "keep_history",
               "keep_audio_history", "remember_desktop", "device", "cpu_threads")
NAV_MODELS, NAV_SETTINGS = 1, 2
SAVED_TEXT = "บันทึกแล้ว ✓"
REPORT_COPIED = "คัดลอกรายงานแล้ว"
ACTION_LABELS = {"download": "ดาวน์โหลดโมเดล", "settings": "เปิดการตั้งค่า", "shortcut": "เปิดใช้ปุ่มลัด",
                 "paste": "อนุญาตวางข้อความ", "models": "ไปหน้าโมเดล"}


class _MirrorLabel(QLabel):
    """QLabel that announces Python-side ``setText`` calls (QLabel has no textChanged)."""
    textChanged = Signal(str)

    def setText(self, text):
        super().setText(text)
        self.textChanged.emit(text)


class _MirrorProgress(QProgressBar):
    """QProgressBar announcing Python-side range/value changes (it has no rangeChanged)."""
    changed = Signal()

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self.changed.emit()

    def setValue(self, value):
        super().setValue(value)
        self.changed.emit()


def _combo(values, selected):
    combo = QComboBox()
    for text, value in values:
        combo.addItem(text, value)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    return combo


class PagesMixin:
    """Builds and wires the ``phimthai.ui`` pages into MainWindow (see module docstring)."""

    # ----- helpers -------------------------------------------------------------
    def _compat_holder(self, layout):
        """Hidden container for compatibility widgets; never part of a visible layout."""
        holder = QWidget(layout.parentWidget())
        holder.setObjectName("compatWidgets")
        holder.hide()
        return holder

    def _status(self, text):
        setter = getattr(self, "set_status", None)
        if callable(setter):
            setter(text)

    def _shortcut_ok(self):
        state = getattr(self, "kde_shortcut_state", {}) or {}
        return bool(state.get("active") or getattr(self, "portal_shortcut", ""))

    def _shortcut_trigger(self):
        state = getattr(self, "kde_shortcut_state", {}) or {}
        return state.get("trigger") if state.get("active") else getattr(self, "portal_shortcut", "")

    def flush_pages(self):
        """Commit pending (debounced) settings edits; call at the start of closeEvent."""
        page = getattr(self, "settings_page", None)
        if page is not None:
            return page.flush()
        return None

    def route_level(self, value):
        """Microphone level → visible meters (only while a microphone test runs)."""
        level = int(value) if getattr(self, "test_microphone", False) else 0
        for name in ("settings_page", "setup_wizard"):
            page = getattr(self, name, None)
            if page is not None:
                page.set_level(level)

    def _connect_level(self):
        if getattr(self, "_level_routed", False):
            return
        recorder = getattr(self, "recorder", None)
        signal = getattr(recorder, "level", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self.route_level)
            self._level_routed = True

    # ----- models page -----------------------------------------------------------
    def build_models_page(self):
        layout = self.page(S.MODELS_TITLE, S.MODELS_SUBTITLE)
        self.models_page = ModelsPage()
        layout.addWidget(self.models_page)
        holder = self._compat_holder(layout)
        self.model_list = QListWidget(holder)
        self.model_list.currentRowChanged.connect(self.model_details)
        self.model_description = QLabel(holder)
        self.model_technical = QLabel(holder)
        self.model_beta_warning = QLabel(S.BETA_WARNING, holder)
        self.model_beta_warning.setObjectName("betaWarning")
        self.download_button = QPushButton(S.BTN_DOWNLOAD, holder)
        self.import_button = QPushButton(S.BTN_IMPORT_MODEL, holder)
        self.download_progress = _MirrorProgress(holder)
        self.download_progress.setValue(0)
        self.download_status = _MirrorLabel(S.DOWNLOAD_HINT, holder)
        self._models_rendered = None
        page = self.models_page
        page.download.connect(lambda model_id: self.download_model(model_id=model_id))
        page.cancel_download.connect(self.cancel_download)
        page.use.connect(self.use_model_id)
        page.remove.connect(self.remove_model_id)
        page.import_folder.connect(self.import_model_path)
        self.download_progress.changed.connect(self.sync_models_page)
        self.download_status.textChanged.connect(lambda *_: self.sync_models_page())
        self.refresh_models_page()
        return self.models_page

    def refresh_models_page(self):
        """Rebuild the model cards. Call at the end of MainWindow.refresh_models()."""
        page = getattr(self, "models_page", None)
        if page is None:
            return
        downloading = getattr(self, "downloading_model", None)
        page.refresh(CATALOG, {model_id: installed_size(model_id) for model_id in CATALOG},
                     self.settings.model, downloading)
        self._models_rendered = (self.settings.model, downloading, tuple(CATALOG))

    def _download_percent(self):
        bar = self.download_progress
        if bar.maximum() <= bar.minimum():
            return None  # Busy indicator.
        return bar.value()

    def models_page_progress(self, percent, text, error=False):
        """Show download/import progress on the downloading card, or as a page message."""
        page = getattr(self, "models_page", None)
        if page is None:
            return
        downloading = getattr(self, "downloading_model", None)
        if downloading and not error:
            page.set_progress(downloading, percent, text)
            page.set_message("")
        else:
            page.set_message("" if text == S.DOWNLOAD_HINT else text, error=error)

    def sync_models_page(self):
        """Mirror the hidden download_progress/download_status into the models page."""
        page = getattr(self, "models_page", None)
        if page is None or not hasattr(self, "download_status"):
            return
        state = (self.settings.model, getattr(self, "downloading_model", None), tuple(CATALOG))
        if state != self._models_rendered:
            self.refresh_models_page()
        process = getattr(self, "download_process", None)
        failure = bool(getattr(self, "download_failure", ""))
        text = self.download_status.text()
        if process is not None and not failure:
            self.models_page_progress(self._download_percent(), text)
        else:
            self.models_page_progress(None, text, error=failure)
        if getattr(self, "setup_wizard", None) is not None:
            self.sync_setup_wizard()

    def _select_model_row(self, model_id):
        if model_id in CATALOG:
            self.model_list.setCurrentRow(list(CATALOG).index(model_id))

    def use_model_id(self, model_id):
        """MainWindow.use_model with an explicit id (no model_list dependency)."""
        if self.recording or self.jobs.busy:
            self.download_status.setText(S.MODEL_BUSY_SWITCH)
            return False
        if model_id == getattr(self, "downloading_model", None):
            self.download_status.setText(S.MODEL_WAIT_DOWNLOAD)
            return False
        if CATALOG[model_id].kind != "asr":
            self.download_status.setText(S.MODEL_TRANSLATION_ONLY)
            return False
        if local_model(model_id) is None:
            self.download_status.setText(S.MODEL_DOWNLOAD_FIRST)
            return False
        selected = replace(self.settings, model=model_id)
        try:
            save_settings(selected)
        except (OSError, ValueError) as exc:
            self.download_status.setText(S.MODEL_SELECT_SAVE_FAILED.format(error=exc))
            return False
        self.settings = selected
        self.jobs.stop_worker()
        self.refresh_models()
        self._select_model_row(model_id)
        self.refresh_device_choices()
        self.sync_device_choices_page()
        self.update_setup_view()
        self.refresh_models_page()
        return True

    def remove_model_id(self, model_id):
        """MainWindow.remove_model with an explicit id and a named confirmation."""
        if self.jobs.busy or self.recording or getattr(self, "download_process", None):
            self.download_status.setText(S.MODEL_BUSY_REMOVE)
            return False
        if not model_dir(model_id).exists():
            self.download_status.setText(S.MODEL_LEGACY)
            return False
        question = f"ลบโมเดล {CATALOG[model_id].name} ออกจากเครื่องหรือไม่?\nดาวน์โหลดใหม่ได้ภายหลัง"
        if QMessageBox.question(self, S.MODEL_REMOVE_TITLE, question) != QMessageBox.StandardButton.Yes:
            return False
        self.jobs.stop_worker()
        if model_id == self.settings.model and CATALOG[model_id].origin == "local":
            if not self.save_setup(model=DEFAULT_MODEL, device="auto", model_setup="skipped"):
                return False
        elif model_id == self.settings.model:
            if not self.save_setup(model_setup="skipped"):
                return False
        remove(model_id)
        self.refresh_models()
        self.refresh_device_choices()
        self.sync_device_choices_page()
        self.update_setup_view()
        self.refresh_models_page()
        return True

    def import_model_path(self, folder):
        """MainWindow.import_model without the folder dialog."""
        if getattr(self, "download_process", None) or self.recording or self.jobs.busy:
            self.download_status.setText(S.MODEL_IMPORT_BUSY)
            return False
        if not folder:
            return False
        self.importing = True
        self.imported_model = None
        self.downloading_model = None
        self.start_model_process(["-m", "phimthai.models", "--import", str(folder)])
        self.download_status.setText(S.MODEL_IMPORTING)
        self.update_setup_view()
        return True

    # ----- settings page ---------------------------------------------------------
    def build_settings_page(self):
        layout = self.page(S.SETTINGS_TITLE, S.SETTINGS_SUBTITLE)
        holder = self._compat_holder(layout)
        s = self.settings
        # Compatibility widgets read by current_settings()/form_values()/cycle_profile/...
        self.microphone = QComboBox(holder)
        self.profile = _combo(S.PROFILE_CHOICES, s.profile)
        self.language = _combo(S.LANGUAGE_CHOICES, s.language)
        self.device = _combo(S.DEVICE_CHOICES, s.device)
        self.preference = _combo(S.PREFERENCE_CHOICES, s.preference)
        self.paste_mode = _combo(S.PASTE_MODE_CHOICES, s.paste_mode)
        for combo in (self.profile, self.language, self.device, self.preference, self.paste_mode):
            combo.setParent(holder)
        self.threads = QSpinBox(holder)
        self.threads.setRange(1, os.cpu_count() or 1)
        self.hotkey = QLineEdit(holder)
        self.shortcut_status = _MirrorLabel(S.SHORTCUT_CHECKING, holder)
        self.language_hint = QLabel(S.LANGUAGE_HINT, holder)
        self.beta_warning = QLabel(S.BETA_WARNING, holder)
        self.beta_warning.setObjectName("betaWarning")
        self.unsaved_label = QLabel(S.SETTINGS_UNSAVED, holder)
        self.unsaved_label.hide()
        self.history = QCheckBox(holder)
        self.audio_history = QCheckBox(holder)
        self.vad = QCheckBox(holder)
        self.reduced_transparency = QCheckBox(holder)
        self.popup_enabled = QCheckBox(holder)
        self.sound_feedback = QCheckBox(holder)
        self.remember_desktop = QCheckBox(holder)
        self.dictionary = QPlainTextEdit(holder)
        self.refresh_microphones()
        self.sync_settings_widgets(s)

        self.settings_page = SettingsPage(s, os.cpu_count() or 1)
        layout.addWidget(self.settings_page)
        page = self.settings_page
        page.changed.connect(self.apply_settings_from_page)
        page.refresh_microphones.connect(self.refresh_microphones_page)
        page.test_microphone.connect(self.test_mic)
        page.enable_shortcut.connect(self.enable_shortcut_from_page)
        page.enable_paste.connect(self.enable_paste_from_page)
        page.clear_history.connect(self.clear_history)
        page.reduced_transparency_toggled.connect(
            lambda checked: apply_style(QApplication.instance(), reduced_transparency=checked))
        self.shortcut_status.textChanged.connect(self._mirror_shortcut_status)
        # cycle_profile() changes the hidden combo; keep the visible one in step.
        self.profile.currentIndexChanged.connect(self._mirror_profile)
        self._mirror_microphones()
        self.sync_device_choices_page()
        self._connect_level()
        return self.settings_page

    def sync_settings_widgets(self, s):
        """Push a Settings into the hidden compatibility widgets (keeps current_settings() consistent)."""
        self._syncing_widgets = True
        try:
            index = self.microphone.findData(s.microphone)
            if index < 0:
                self.microphone.addItem(S.MIC_DISCONNECTED, s.microphone)
                index = self.microphone.count() - 1
            self.microphone.setCurrentIndex(index)
            for combo, value in ((self.profile, s.profile), (self.language, s.language),
                                 (self.device, s.device), (self.preference, s.preference),
                                 (self.paste_mode, s.paste_mode)):
                combo.setCurrentIndex(max(0, combo.findData(value)))
            self.threads.setValue(s.cpu_threads)
            if self.hotkey.text() != s.hotkey:
                self.hotkey.setText(s.hotkey)
            for box, value in ((self.history, s.keep_history), (self.audio_history, s.keep_audio_history),
                               (self.vad, s.vad), (self.reduced_transparency, s.reduced_transparency),
                               (self.popup_enabled, s.popup_enabled), (self.sound_feedback, s.sound_feedback),
                               (self.remember_desktop, s.remember_desktop)):
                box.setChecked(value)
            if self.dictionary.toPlainText() != s.dictionary:
                self.dictionary.setPlainText(s.dictionary)
        finally:
            self._syncing_widgets = False
        indicator = getattr(self, "update_unsaved_indicator", None)
        if callable(indicator):
            indicator()

    def _mirror_profile(self, *_):
        page = getattr(self, "settings_page", None)
        if page is None or getattr(self, "_syncing_widgets", False):
            return
        value = self.profile.currentData()
        # Only the profile widget changes; pending edits in other fields survive.
        page.profile.blockSignals(True)
        page.profile.setCurrentIndex(max(0, page.profile.findData(value)))
        page.profile.blockSignals(False)
        mode = getattr(self, "mode_button", None)
        if mode is not None and value in S.PROFILE_NAMES:
            mode.setText(S.PROFILE_NAMES[value])

    def _mirror_shortcut_status(self, text):
        page = getattr(self, "settings_page", None)
        if page is not None:
            page.set_shortcut_status(text, self._shortcut_ok())
        if getattr(self, "setup_wizard", None) is not None:
            self.sync_setup_wizard()

    def _microphone_items(self):
        return [(self.microphone.itemText(i), self.microphone.itemData(i))
                for i in range(self.microphone.count()) if self.microphone.itemData(i)]

    def _mirror_microphones(self):
        items = self._microphone_items()
        for name in ("settings_page", "setup_wizard"):
            page = getattr(self, name, None)
            if page is not None:
                page.set_microphones(items, self.settings.microphone)

    def refresh_microphones_page(self):
        """Re-scan microphones (old refresh_microphones) and mirror them into the pages."""
        self.refresh_microphones()
        self._mirror_microphones()

    def sync_device_choices_page(self):
        """Thai-only language labels + NPU availability. Call after refresh_device_choices()."""
        page = getattr(self, "settings_page", None)
        if page is None:
            return
        page.set_language_thai_only(CATALOG[self.settings.model].backend == "typhoon")
        index = self.device.findData("npu")
        item = self.device.model().item(index) if index >= 0 and hasattr(self.device.model(), "item") else None
        page.set_npu_available(bool(item.isEnabled()) if item is not None else False)

    def apply_settings_from_page(self, candidate):
        """Autosave handler for SettingsPage.changed. Returns the saved Settings or None."""
        page = self.settings_page
        previous = self.settings
        try:
            merged = replace(previous, **{key: getattr(candidate, key) for key in PAGE_FIELDS}).validate()
            save_settings(merged)
        except (OSError, ValueError) as exc:
            page.set_saved_indicator("")
            page._show_error(None, f"บันทึกไม่สำเร็จ: {exc}")
            self._status(S.ERROR_PREFIX + str(exc))
            return None
        self.settings = merged
        self.sync_settings_widgets(merged)
        feedback = getattr(self, "feedback", None)
        if feedback is not None:
            headless = QGuiApplication.platformName() in {"offscreen", "minimal"}
            feedback.configure(sound_enabled=merged.sound_feedback and not headless,
                               popup_enabled=merged.popup_enabled and not headless)
            if merged.profile != previous.profile and hasattr(feedback, "set_profile"):
                feedback.set_profile(merged.profile)
        if merged.reduced_transparency != previous.reduced_transparency:
            apply_style(QApplication.instance(), reduced_transparency=merged.reduced_transparency)
        mode = getattr(self, "mode_button", None)
        if mode is not None:
            mode.setText(S.PROFILE_NAMES[merged.profile])
        page.set_language_thai_only(CATALOG[merged.model].backend == "typhoon")
        if previous.remember_desktop and not merged.remember_desktop:
            from .portals import state_path
            try:
                state_path().unlink(missing_ok=True)
            except OSError as exc:
                LOG.warning("could not forget desktop permissions: %s", exc)
            if getattr(self, "portal", None) is not None:
                self.portal_command("forget")
        self._page_enabled_shortcut = False
        if merged.hotkey != previous.hotkey:
            self._page_enabled_shortcut = True
            self.enable_shortcut()
        page.set_saved_indicator(SAVED_TEXT)
        LOG.info("settings autosaved")
        return merged

    def enable_shortcut_from_page(self, trigger):
        self._page_enabled_shortcut = False
        self.flush_pages()  # A changed hotkey already re-enables the shortcut on save.
        if self._page_enabled_shortcut:
            return
        if trigger and trigger != self.hotkey.text():
            self.hotkey.setText(trigger)
        self.enable_shortcut()

    def enable_paste_from_page(self, persist):
        self.flush_pages()
        self.portal_command("enable_paste", persist=bool(persist))

    # ----- diagnostics page --------------------------------------------------------
    def build_diagnostics_page(self):
        layout = self.page(S.DIAGNOSTICS_TITLE, S.DIAGNOSTICS_SUBTITLE)
        holder = self._compat_holder(layout)
        self.diagnostic_summary = QLabel(holder)
        self.diagnostics = QPlainTextEdit(holder)
        self.diagnostics.setReadOnly(True)
        self.diagnostics_page = DiagnosticsPage()
        layout.addWidget(self.diagnostics_page)
        self.diagnostics_page.refresh.connect(self.refresh_diagnostics_page)
        self.diagnostics_page.action.connect(self.diagnostics_action)
        self.diagnostics_page.copy_report.connect(self.copy_report_from_page)
        self.refresh_diagnostics_page()
        return self.diagnostics_page

    def diagnostic_checks(self):
        checks = []
        try:
            from PySide6.QtMultimedia import QMediaDevices
            microphones = len(QMediaDevices.audioInputs())
        except Exception:
            microphones = None
        checks.append(Check("microphone", "ไมโครโฟน", None if microphones is None else microphones > 0,
                            "ตรวจไมโครโฟนไม่ได้" if microphones is None else
                            (f"พบ {microphones} ตัว" if microphones else "ไม่พบไมโครโฟน · เสียบไมค์แล้วกดตรวจสอบใหม่"),
                            ACTION_LABELS["settings"], "settings"))
        spec = CATALOG.get(self.settings.model)
        ready = spec is not None and local_model(self.settings.model) is not None
        checks.append(Check("model", "โมเดลถอดเสียง", ready,
                            f"{spec.name if spec else self.settings.model} · " +
                            ("ติดตั้งและตรวจไฟล์แล้ว" if ready else "ยังไม่ได้ดาวน์โหลดหรือไฟล์ไม่ครบ"),
                            *(("", "") if ready else (ACTION_LABELS["download"], "download"))))
        warm_attr = getattr(self, "jobs_warm", None)
        warm = warm_attr() if callable(warm_attr) else bool(getattr(self.jobs, "warm", False))
        checks.append(Check("worker", "โมเดลพร้อมในหน่วยความจำ", True if warm else None,
                            "โหลดไว้แล้ว เริ่มพูดได้ทันที" if warm else "จะโหลดเมื่อเริ่มพูดครั้งแรก (อาจใช้เวลาสักครู่)"))
        shortcut = self._shortcut_ok()
        trigger = self._shortcut_trigger()
        checks.append(Check("shortcut", "ปุ่มลัด", shortcut,
                            f"{trigger} พร้อมใช้งาน" if shortcut else "ยังไม่ได้เปิดใช้ปุ่มลัดกับเดสก์ท็อป",
                            ACTION_LABELS["shortcut"], "shortcut"))
        paste = bool(getattr(self, "paste_enabled", False))
        checks.append(Check("paste", "สิทธิ์วางข้อความ", paste,
                            "อนุญาตแล้ว" if paste else "ยังไม่ได้อนุญาต · ข้อความจะถูกคัดลอกไว้ให้วางเอง",
                            *(("", "") if paste else (ACTION_LABELS["paste"], "paste"))))
        if self._is_wayland():
            wl = shutil.which("wl-copy") is not None
            checks.append(Check("wl_copy", "wl-clipboard (Wayland)", wl,
                                "พบ wl-copy" if wl else "ไม่พบ wl-copy · การวางข้อความหลังกดปุ่มลัดอาจไม่ทำงาน"))
        try:
            from . import logs
            installs = logs.detect_duplicate_installs()
        except Exception:
            installs = None
        checks.append(Check("installs", "การติดตั้งซ้ำ", None if installs is None else len(installs) <= 1,
                            "ตรวจไม่ได้" if installs is None else
                            ("ไม่พบการติดตั้งซ้ำ" if len(installs) <= 1 else
                             "พบหลายชุด ปุ่มลัดอาจเปิดผิดตัว: " + " · ".join(installs))))
        try:
            from .kde import find_conflicts
            conflicts = find_conflicts()
        except Exception:
            conflicts = None
        checks.append(Check("conflicts", "ปุ่มลัดซ้ำซ้อน", None if conflicts is None else not conflicts,
                            "ตรวจไม่ได้ในสภาพแวดล้อมนี้" if conflicts is None else
                            ("ไม่พบปุ่มลัดซ้ำ" if not conflicts else
                             "ปุ่มเดียวถูกผูกหลายที่: " + ", ".join(c["trigger"] for c in conflicts)),
                            *(("", "") if not conflicts else (ACTION_LABELS["shortcut"], "shortcut"))))
        writable = self._log_writable()
        checks.append(Check("log", "ไฟล์บันทึก (log)", writable,
                            "เขียนได้" if writable else ("ตรวจไม่ได้" if writable is None else "เขียนไฟล์ log ไม่ได้")))
        return checks

    @staticmethod
    def _is_wayland():
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return True
        try:
            from .clipboard import is_wayland
            return is_wayland()
        except Exception:
            return False

    @staticmethod
    def _log_writable():
        try:
            from . import logs
            path = logs.log_path()
        except Exception:
            return None
        target = path
        while not target.exists() and target != target.parent:
            target = target.parent
        return os.access(target, os.W_OK)

    def refresh_diagnostics_page(self):
        refresh = getattr(self, "refresh_diagnostics", None)
        if callable(refresh):
            try:
                refresh()  # Fills the hidden diagnostic_summary/diagnostics widgets.
            except Exception as exc:
                LOG.warning("diagnostics refresh failed: %s", exc)
        raw = self.diagnostics.toPlainText() if hasattr(self, "diagnostics") else ""
        if not raw:
            from .devices import inventory
            raw = json.dumps(inventory(), ensure_ascii=False, indent=2)
        checks = self.diagnostic_checks()
        self.diagnostics_page.set_checks(checks)
        self.diagnostics_page.set_raw(raw)
        return checks

    def diagnostics_action(self, action_id):
        if action_id == "download":
            self.download_model(model_id=self.settings.model)
        elif action_id == "settings":
            self.nav.setCurrentRow(NAV_SETTINGS)
        elif action_id == "models":
            self.nav.setCurrentRow(NAV_MODELS)
        elif action_id == "shortcut":
            self.enable_shortcut()
        elif action_id == "paste":
            self.portal_command("enable_paste", persist=self.settings.remember_desktop)

    def copy_report_from_page(self):
        extra_fn = getattr(self, "diagnostic_extra", None)
        try:
            extra = extra_fn() if callable(extra_fn) else {}
        except Exception:
            extra = {}
        extra = dict(extra or {})
        extra.setdefault("model", self.settings.model)
        extra.setdefault("model_installed", local_model(self.settings.model) is not None)
        extra.setdefault("paste_enabled", bool(getattr(self, "paste_enabled", False)))
        extra.setdefault("shortcut_active", self._shortcut_ok())
        extra["checks"] = ", ".join(f"{c.id}={c.state}" for c in self.diagnostic_checks())
        try:
            from . import logs
            report = logs.diagnostic_report(extra=extra)
        except Exception as exc:
            LOG.warning("diagnostic report fallback: %s", exc)
            report = "PhimThaiMaiPen diagnostic report\n" + "\n".join(f"{k}: {v}" for k, v in extra.items())
        QGuiApplication.clipboard().setText(report)
        self._status(REPORT_COPIED)
        return report

    # ----- setup wizard ------------------------------------------------------------
    def build_setup_wizard(self):
        """Create the wizard; the caller inserts it at the top of the transcript page."""
        self.setup_wizard = wizard = SetupWizard()
        wizard.download.connect(lambda: self.download_model(model_id=self.settings.model))
        wizard.cancel_download.connect(self.cancel_download)
        wizard.choose_model.connect(lambda: self.nav.setCurrentRow(NAV_MODELS))
        wizard.refresh_microphones.connect(self.refresh_microphones_page)
        wizard.test_microphone.connect(self.test_mic)
        wizard.microphone_selected.connect(self.select_microphone)
        wizard.enable_shortcut.connect(self.enable_shortcut)
        wizard.enable_paste.connect(
            lambda: self.portal_command("enable_paste", persist=self.settings.remember_desktop))
        wizard.skip.connect(self.dismiss_setup_wizard)
        wizard.finished.connect(self.dismiss_setup_wizard)
        wizard.setVisible(not self.settings.onboarding_done)
        if hasattr(self, "microphone"):
            self._mirror_microphones()
        self._connect_level()
        self.sync_setup_wizard()
        return wizard

    def select_microphone(self, device_id):
        try:
            updated = replace(self.settings, microphone=device_id or "")
            save_settings(updated)
        except (OSError, ValueError) as exc:
            self._status(S.SETUP_SAVE_FAILED.format(error=exc))
            return False
        self.settings = updated
        if hasattr(self, "microphone"):
            self.sync_settings_widgets(updated)
            self._mirror_microphones()
        return True

    def dismiss_setup_wizard(self):
        try:
            updated = replace(self.settings, onboarding_done=True)
            save_settings(updated)
            self.settings = updated
        except (OSError, ValueError) as exc:
            self._status(S.SETUP_SAVE_FAILED.format(error=exc))
        wizard = getattr(self, "setup_wizard", None)
        if wizard is not None:
            wizard.hide()

    def sync_setup_wizard(self):
        """Model/progress/permission state → wizard. Call at the end of update_setup_view()."""
        wizard = getattr(self, "setup_wizard", None)
        if wizard is None:
            return
        spec = CATALOG.get(self.settings.model)
        ready = spec is not None and local_model(self.settings.model) is not None
        wizard.set_model(spec.name if spec else self.settings.model, getattr(spec, "download_gb", 0), ready)
        downloading = (getattr(self, "download_process", None) is not None
                       and getattr(self, "downloading_model", None) == self.settings.model)
        if downloading and hasattr(self, "download_progress"):
            wizard.set_progress(self._download_percent(), self.download_status.text())
        elif wizard._downloading:
            wizard.set_downloading(False)
        trigger = self._shortcut_trigger()
        ok = self._shortcut_ok()
        wizard.set_permissions(trigger if ok else "ยังไม่ได้เปิดใช้", ok, bool(getattr(self, "paste_enabled", False)))
        wizard.set_hotkey(trigger if ok and trigger else self.settings.hotkey)
