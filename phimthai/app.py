"""Native desktop application; model work never runs on the UI thread."""
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QLockFile, QProcess, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QMenu, QSystemTrayIcon, QScrollArea)

from . import APP_ID, __version__
from .audio import Recorder
from .appearance import GlassCanvas, GlassPanel, apply_style
from .clipboard import ClipboardTransaction
from .devices import inventory, openvino_devices
from .jobs import JobController
from .models import CATALOG, installed_size, local_model, model_dir, remove
from .settings import Settings, data_dir, load_settings, save_settings

PROFILE_NAMES = {"smart": "Smart Mix", "raw": "Raw", "th_to_eng": "TH → ENG"}


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    widget.setMinimumHeight(36)
    if primary:
        widget.setProperty("primary", True)
    return widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings_error = ""
        try:
            self.settings = load_settings()
        except Exception as exc:
            self.settings = Settings()
            self.settings_error = f"Settings could not load: {exc}. Existing file has not been overwritten."
        self.setWindowTitle("PhimThaiMaiPen · พิมพ์ไทยไม่เป็น")
        self.resize(1060, 760)
        self.setMinimumSize(820, 600)
        self.temp = tempfile.TemporaryDirectory(prefix="phimthai-", dir=os.environ.get("XDG_RUNTIME_DIR"))
        self.recording = False
        self.test_microphone = False
        self.audio_path = None
        self.download_process = None
        self.downloading_model = None
        self.download_buffer = b""
        self.portal_buffer = b""
        self.paste_enabled = False
        self.portal_permission_pending = False
        self.portal = None
        self.portal_shortcut = ""
        self.portal_mode_shortcut = ""
        self.shortcut_process = None
        self.shortcut_installing = False
        self.kde_shortcut_state = {}
        self.last_request = None
        self.quitting = False
        self.tray = None
        self.jobs = JobController(self, temp_root=self.temp.name)
        self.jobs.changed.connect(self.set_status)
        self.jobs.result.connect(self.completed)
        self.jobs.failed.connect(self.job_failed)
        self.recorder = Recorder(self)
        self.recorder.failed.connect(self.capture_error)
        self.clipboard = ClipboardTransaction(self)
        self.paste_busy = False
        self.clipboard.restored.connect(lambda: setattr(self, "paste_busy", False))
        self.paste_timer = QTimer(self)
        self.paste_timer.setSingleShot(True)
        self.paste_timer.timeout.connect(self.send_paste)
        self.build_ui()
        self.recorder.media_devices.audioInputsChanged.connect(self.refresh_microphones)
        self.recorder.level.connect(self.level.setValue)
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.record_tick)
        self.statusBar().showMessage(f"PhimThaiMaiPen {__version__}  ·  ประมวลผลในเครื่อง")
        self.refresh_models()
        self.refresh_device_choices()
        self.setup_tray()
        apply_style(QApplication.instance(), reduced_transparency=self.settings.reduced_transparency)
        self.refresh_shortcut_status()
        if self.settings_error:
            self.set_status(self.settings_error)
        elif local_model(self.settings.model) is None:
            self.set_status("เลือกและดาวน์โหลดโมเดลก่อนเริ่มพูด")
        else:
            self.set_status("พร้อมแล้ว กดเริ่มพูด เมื่อพูดจบให้กดอีกครั้ง")
        if self.settings.remember_desktop:
            QTimer.singleShot(0, lambda: self.portal_command("restore"))

    def build_ui(self):
        root = GlassCanvas()
        root.setObjectName("canvas")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)
        sidebar_panel = GlassPanel()
        sidebar_panel.setObjectName("sidebar")
        sidebar_panel.setFixedWidth(180)
        sidebar = QVBoxLayout(sidebar_panel)
        sidebar.setContentsMargins(16, 24, 16, 20)
        sidebar.setSpacing(8)
        brand = QLabel("PhimThai")
        brand.setObjectName("brand")
        sidebar.addWidget(brand)
        name = QLabel("MaiPen")
        name.setObjectName("muted")
        sidebar.addWidget(name)
        sidebar.addSpacing(28)
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.setAccessibleName("หน้าหลักของแอป")
        self.nav.addItems(["พิมพ์ด้วยเสียง", "โมเดล", "ตั้งค่า", "ตรวจสอบระบบ"])
        for index, tooltip in enumerate(["Transcript", "Models", "Settings", "Diagnostics"]):
            self.nav.item(index).setToolTip(tooltip)
        sidebar.addWidget(self.nav)
        self.shortcut_hint = QLabel(self.settings.hotkey.replace("META", "Meta"))
        self.shortcut_hint.setObjectName("shortcut")
        self.shortcut_hint.setToolTip("ปุ่มลัดเริ่มและหยุดพูด · ตั้งค่าได้ในหน้าตั้งค่า")
        sidebar.addWidget(self.shortcut_hint)
        self.mode_button = button(PROFILE_NAMES[self.settings.profile], self.cycle_profile)
        self.mode_button.setToolTip("สลับโหมด · Smart Mix → Raw → TH → ENG")
        sidebar.addWidget(self.mode_button)
        self.mode_shortcut_hint = QLabel("")
        self.mode_shortcut_hint.setObjectName("muted")
        sidebar.addWidget(self.mode_shortcut_hint)
        footer = QLabel("ไทย + English\nเสียงอยู่ในเครื่องคุณ")
        footer.setObjectName("muted")
        sidebar.addWidget(footer)
        layout.addWidget(sidebar_panel)
        workspace = GlassPanel()
        workspace.setObjectName("workspace")
        content = QVBoxLayout(workspace)
        content.setContentsMargins(10, 10, 10, 10)
        self.pages = QStackedWidget()
        content.addWidget(self.pages)
        layout.addWidget(workspace, 1)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.build_transcript()
        self.build_models()
        self.build_settings()
        self.build_diagnostics()
        self.nav.setCurrentRow(0)
        self.setCentralWidget(root)

    def page(self, title, subtitle):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("heading")
        layout.addWidget(heading)
        description = QLabel(subtitle)
        description.setWordWrap(True)
        description.setObjectName("muted")
        layout.addWidget(description)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        # QScrollArea turns auto-fill on when a widget is attached. Keep the
        # glass visible instead of painting the desktop theme's Window brush.
        page.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        self.pages.addWidget(scroll)
        return layout

    def build_transcript(self):
        layout = self.page("พูดให้เป็นข้อความ", "ไทย อังกฤษ หรือพูดสลับภาษา · แก้ข้อความได้ก่อนวาง")
        self.onboarding = QWidget()
        first_run = QHBoxLayout(self.onboarding)
        first_run.setContentsMargins(0, 0, 0, 0)
        first_run.addWidget(QLabel("เตรียมก่อนเริ่ม"))
        first_run.addStretch()
        first_run.addWidget(button("เลือกโมเดล", lambda: self.nav.setCurrentRow(1)))
        first_run.addWidget(button("ทดสอบไมค์", self.test_mic))
        self.onboarding.setVisible(local_model(self.settings.model) is None)
        layout.addWidget(self.onboarding)
        row = QHBoxLayout()
        self.record_button = button("เริ่มพูด", self.toggle_record, True)
        self.record_button.setMinimumSize(168, 48)
        self.record_button.setToolTip("Start / stop recording")
        row.addWidget(self.record_button)
        row.addWidget(button("เปิดไฟล์เสียง", self.open_audio))
        row.addStretch()
        self.cancel_button = button("ยกเลิก", self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(8)
        self.level.setAccessibleName("Microphone input level")
        layout.addWidget(self.level)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("editor")
        self.editor.setPlaceholderText("เริ่มจากเสียงของคุณ…\n\nข้อความที่ถอดจะปรากฏที่นี่ แล้วแก้ไขได้ตามต้องการ")
        self.editor.setAccessibleName("Editable transcript")
        layout.addWidget(self.editor, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("วางในแอป", self.paste, True))
        actions.addWidget(button("คัดลอก", self.copy))
        actions.addStretch()
        actions.addWidget(button("แปลอังกฤษ", self.translate))
        actions.addWidget(button("ถอดใหม่", self.retry))
        layout.addLayout(actions)
        self.metrics = QLabel(CATALOG[self.settings.model].name + " · เวลาและอุปกรณ์จะแสดงเมื่อถอดเสียงเสร็จ")
        self.metrics.setObjectName("muted")
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)

    def build_models(self):
        layout = self.page("เลือกเสียงที่เข้าใจคุณ", "เลือกโมเดลให้เหมาะกับภาษาและเครื่อง ดาวน์โหลดครั้งเดียวแล้วใช้แบบออฟไลน์")
        self.model_list = QListWidget()
        self.model_list.currentRowChanged.connect(self.model_details)
        layout.addWidget(self.model_list)
        self.model_description = QLabel()
        self.model_description.setWordWrap(True)
        layout.addWidget(self.model_description)
        actions = QHBoxLayout()
        actions.addWidget(button("ดาวน์โหลด / ซ่อมไฟล์", self.download_model, True))
        actions.addWidget(button("หยุดโหลด", self.cancel_download))
        actions.addStretch()
        actions.addWidget(button("เลือกใช้", self.use_model))
        actions.addWidget(button("ลบโมเดล", self.remove_model))
        layout.addLayout(actions)
        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)
        self.download_status = QLabel("หยุดแล้วโหลดต่อได้ · ตรวจความสมบูรณ์ของไฟล์ก่อนเปิดใช้")
        self.download_status.setWordWrap(True)
        layout.addWidget(self.download_status)
        layout.addStretch()

    def build_settings(self):
        layout = self.page("ปรับให้ถนัดคุณ", "ตั้งค่าไมค์ ภาษา และปุ่มลัด การเปลี่ยนแปลงมีผลกับงานถัดไป")
        actions = QHBoxLayout()
        actions.addWidget(button("บันทึกการตั้งค่า", self.save, True))
        actions.addStretch()
        actions.addWidget(button("เปิดใช้ปุ่มลัด", self.enable_shortcut))
        actions.addWidget(button("อนุญาตวางข้อความ", lambda: self.portal_command("enable_paste", persist=self.remember_desktop.isChecked())))
        layout.addLayout(actions)
        form = QFormLayout()
        form.setSpacing(12)
        self.microphone = QComboBox()
        self.refresh_microphones()
        form.addRow("ไมโครโฟน", self.microphone)
        mic_actions = QHBoxLayout()
        mic_actions.addWidget(button("ตรวจหาไมค์", self.refresh_microphones))
        mic_actions.addWidget(button("ทดสอบไมค์ 5 วินาที", self.test_mic))
        form.addRow(mic_actions)
        self.profile = self.combo([("Smart Mix · ปรับข้อความให้อ่านง่าย", "smart"), ("Raw · ถอดตามที่พูด", "raw"), ("TH → ENG · พูดไทย แปลอังกฤษ", "th_to_eng")], self.settings.profile)
        self.profile.currentIndexChanged.connect(lambda: self.mode_button.setText(PROFILE_NAMES[self.profile.currentData()]))
        form.addRow("รูปแบบข้อความ", self.profile)
        self.language = self.combo([("อัตโนมัติ · ไทย + English", "auto"), ("ภาษาไทย", "Thai"), ("English", "English")], self.settings.language)
        form.addRow("ภาษาที่พูด", self.language)
        self.device = self.combo([("Automatic", "auto"), ("CPU", "cpu"), ("GPU (compatible CUDA)", "gpu"), ("NPU (check compatibility)", "npu")], self.settings.device)
        form.addRow("ประมวลผลด้วย", self.device)
        self.preference = self.combo([("ตอบสนองเร็ว", "speed"), ("ประหยัดพลังงาน · ต้องมีผลวัด", "power")], self.settings.preference)
        form.addRow("โหมดอัตโนมัติเน้น", self.preference)
        self.threads = QSpinBox()
        self.threads.setRange(1, os.cpu_count() or 1)
        self.threads.setValue(self.settings.cpu_threads)
        form.addRow("CPU threads", self.threads)
        self.paste_mode = self.combo([("ตรวจและแก้ข้อความก่อนวาง", "review"), ("วางทันทีเมื่อถอดเสียงเสร็จ", "immediate")], self.settings.paste_mode)
        form.addRow("เมื่อพูดจบ", self.paste_mode)
        self.hotkey = QLineEdit(self.settings.hotkey)
        form.addRow("ปุ่มลัดเริ่ม / หยุด", self.hotkey)
        self.shortcut_status = QLabel("กำลังตรวจปุ่มลัด…")
        self.shortcut_status.setObjectName("muted")
        self.shortcut_status.setWordWrap(True)
        form.addRow(self.shortcut_status)
        self.history = QCheckBox("เก็บประวัติข้อความในเครื่อง")
        self.history.setChecked(self.settings.keep_history)
        form.addRow(self.history)
        self.audio_history = QCheckBox("เก็บประวัติเสียงในเครื่อง")
        self.audio_history.setChecked(self.settings.keep_audio_history)
        form.addRow(self.audio_history)
        self.vad = QCheckBox("ตรวจช่วงพูดและตัดความเงียบต้น–ท้าย")
        self.vad.setChecked(self.settings.vad)
        form.addRow(self.vad)
        self.reduced_transparency = QCheckBox("ลดความโปร่งใส เพิ่มความชัดของพื้นหลัง")
        self.reduced_transparency.setChecked(self.settings.reduced_transparency)
        self.reduced_transparency.toggled.connect(lambda checked: apply_style(QApplication.instance(), reduced_transparency=checked))
        form.addRow(self.reduced_transparency)
        layout.addLayout(form)
        layout.addWidget(QLabel("พจนานุกรมส่วนตัว · คำเดิม ตามด้วย Tab และคำที่ให้แทน"))
        self.dictionary = QPlainTextEdit(self.settings.dictionary)
        self.dictionary.setAccessibleName("Custom replacement dictionary")
        self.dictionary.setMaximumHeight(100)
        layout.addWidget(self.dictionary)
        self.remember_desktop = QCheckBox("จำสิทธิ์วางข้อความและปุ่มลัดที่ขอผ่านระบบ")
        self.remember_desktop.setChecked(self.settings.remember_desktop)
        self.remember_desktop.setToolTip("Enable before granting shortcut/paste permission, then Save. The desktop decides whether permission can persist.")
        layout.addWidget(self.remember_desktop)
        layout.addWidget(button("ลบประวัติข้อความและเสียงที่บันทึก", self.clear_history))

    def build_diagnostics(self):
        layout = self.page("เครื่องของคุณ", "ตรวจไมค์ โมเดล และอุปกรณ์ที่ใช้ได้ พร้อมข้อมูลสำหรับแก้ปัญหา")
        self.diagnostic_summary = QLabel()
        self.diagnostic_summary.setWordWrap(True)
        layout.addWidget(self.diagnostic_summary)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setAccessibleName("Device diagnostics")
        layout.addWidget(self.diagnostics)
        layout.addWidget(button("ตรวจสอบใหม่", self.refresh_diagnostics))
        self.refresh_diagnostics()

    @staticmethod
    def combo(values, selected):
        combo = QComboBox()
        for text, value in values:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        return combo

    def refresh_microphones(self):
        selected = self.microphone.currentData() if self.microphone.count() else self.settings.microphone
        self.microphone.clear()
        self.microphone.addItem("ไมค์เริ่มต้นของระบบ", "")
        for device in QMediaDevices.audioInputs():
            self.microphone.addItem(device.description(), bytes(device.id()).hex())
        index = self.microphone.findData(selected)
        if index < 0:
            self.microphone.addItem("Microphone disconnected — select an available input", selected)
            index = self.microphone.count() - 1
            self.microphone.model().item(index).setEnabled(False)
        self.microphone.setCurrentIndex(index)

    def current_settings(self):
        return replace(self.settings, microphone=self.microphone.currentData(), profile=self.profile.currentData(),
            language=self.language.currentData(), device=self.device.currentData(), cpu_threads=self.threads.value(),
            paste_mode=self.paste_mode.currentData(), hotkey=self.hotkey.text().strip(),
            preference=self.preference.currentData(),
            vad=self.vad.isChecked(),
            dictionary=self.dictionary.toPlainText(), keep_history=self.history.isChecked(),
            keep_audio_history=self.audio_history.isChecked(), remember_desktop=self.remember_desktop.isChecked(),
            reduced_transparency=self.reduced_transparency.isChecked(),
            onboarding_done=True).validate()

    def save(self):
        try:
            previous_hotkey = self.settings.hotkey
            self.settings = self.current_settings()
            save_settings(self.settings)
            if not self.settings.remember_desktop:
                from .portals import state_path
                state_path().unlink(missing_ok=True)
                if self.portal is not None:
                    # A pending permission grant may write a new one-use token.
                    # Process opt-out after that grant in the existing bridge.
                    self.portal_command("forget")
            self.set_status("บันทึกการตั้งค่าแล้ว")
            if self.settings.hotkey != previous_hotkey:
                self.enable_shortcut()
            self.refresh_shortcut_status()
        except Exception as exc:
            self.error(str(exc))

    def set_status(self, text):
        self.status.setText(text)

    def refresh_shortcut_status(self):
        from .kde import is_kde
        if self.quitting:
            return self.kde_shortcut_state
        self.show_shortcut_status()
        if is_kde() and not Path("/.flatpak-info").exists() and (data_dir() / "bin/phimthai").exists():
            self.kde_shortcut_command()
        return self.kde_shortcut_state

    def show_shortcut_status(self):
        state = self.kde_shortcut_state
        trigger = state.get("trigger") if state.get("active") else self.portal_shortcut
        if trigger:
            self.shortcut_hint.setText(trigger)
            self.shortcut_status.setText(f"{trigger} · พร้อมเริ่มและหยุดพูด")
        else:
            self.shortcut_hint.setText("ตั้งค่าปุ่มลัด")
            self.shortcut_status.setText("ยังไม่เปิดใช้ปุ่มลัด · กดเปิดใช้ปุ่มลัดด้านบน")
        mode_trigger = state.get("mode_trigger", "") if state.get("mode_active") else self.portal_mode_shortcut
        self.mode_shortcut_hint.setText(mode_trigger)
        if mode_trigger:
            self.shortcut_status.setText(self.shortcut_status.text() + f"\n{mode_trigger} · สลับโหมด")

    def cycle_profile(self):
        profiles = list(PROFILE_NAMES)
        next_profile = profiles[(profiles.index(self.profile.currentData()) + 1) % len(profiles)]
        try:
            selected = replace(self.settings, profile=next_profile)
            save_settings(selected)
        except Exception as exc:
            self.error(f"เปลี่ยนโหมดไม่สำเร็จ: {exc}")
            return
        self.settings = selected
        self.profile.setCurrentIndex(self.profile.findData(next_profile))
        message = f"โหมด {PROFILE_NAMES[next_profile]}"
        if self.recording or self.jobs.busy:
            message += " · ใช้กับการพูดครั้งถัดไป"
        if next_profile == "th_to_eng" and local_model("translate-th-en") is None:
            message += " · ต้องดาวน์โหลดโมเดลแปลภาษาในหน้าโมเดล"
        self.set_status(message)
        if self.tray and self.tray.isVisible():
            self.tray.showMessage("PhimThaiMaiPen", message, QSystemTrayIcon.MessageIcon.Information, 1800)

    def kde_shortcut_command(self, trigger=None):
        # D-Bus timeouts and registration must never freeze recording controls.
        if self.quitting:
            return
        if self.shortcut_process is not None:
            if trigger is not None:
                self.error("รอตรวจปุ่มลัดเสร็จสักครู่ แล้วลองใหม่")
            return
        process = QProcess(self)
        self.shortcut_process = process
        self.shortcut_installing = trigger is not None
        def finished(*_args):
            if self.shortcut_process is not process:
                return
            self.shortcut_process = None
            self.shortcut_installing = False
            try:
                state = json.loads(bytes(process.readAllStandardOutput()))
            except (ValueError, TypeError):
                state = {"active": False, "error": "ตรวจปุ่มลัดไม่สำเร็จ ลองเปิดใช้ปุ่มลัดอีกครั้ง"}
            self.kde_shortcut_state = state
            self.show_shortcut_status()
            if trigger is not None:
                if state.get("active"):
                    self.set_status(f"ปุ่มลัด {state['trigger']} พร้อมใช้งาน")
                else:
                    self.error(state.get("error", "เปิดใช้ปุ่มลัดไม่สำเร็จ"))
            process.deleteLater()
            if self.quitting:
                QTimer.singleShot(0, self.quit)
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished() if error == QProcess.ProcessError.FailedToStart else None)
        args = ["-m", "phimthai.kde", "--status"] if trigger is None else ["-m", "phimthai.kde", "--install", trigger]
        process.start(sys.executable, args)

    def enable_shortcut(self):
        from .kde import is_kde
        if is_kde() and not Path("/.flatpak-info").exists():
            self.kde_shortcut_command(self.hotkey.text().strip())
        else:
            self.portal_command("shortcuts", trigger=self.hotkey.text(), persist=self.remember_desktop.isChecked())

    def error(self, message):
        self.set_status("Error: " + message)
        self.nav.setCurrentRow(0)

    def job_failed(self, message):
        warnings = self.cleanup_temporary_audio()
        self.error("; ".join([message, *warnings]))

    def toggle_record(self):
        if self.recording:
            self.finish_recording()
            return
        if self.jobs.busy:
            self.error("A job is still running. Finish or cancel it before recording again.")
            return
        try:
            self.record_settings = self.current_settings()
            if not self.test_microphone and self.downloading_model == self.record_settings.model:
                raise RuntimeError("Wait for the selected model download or repair to finish")
            if not self.test_microphone and local_model(self.record_settings.model) is None:
                raise RuntimeError("Download a model in Models before recording")
            self.audio_path = Path(self.temp.name) / (uuid.uuid4().hex + ".wav")
            self.recorder.start(self.audio_path, self.record_settings.microphone)
            self.recording = True
            self.record_started = time.monotonic()
            self.record_button.setText("หยุดพูด")
            self.record_timer.start(200)
            self.nav.setCurrentRow(0)
            self.set_status("กำลังฟัง… พูดจบแล้วกดหยุดพูดหรือปุ่มลัดอีกครั้ง")
        except Exception as exc:
            self.recorder.stop()
            self.test_microphone = False
            self.error(str(exc))

    def record_tick(self):
        seconds = int(time.monotonic() - self.record_started)
        self.set_status(f"กำลังฟัง…  {seconds // 60:02d}:{seconds % 60:02d}  ·  กดอีกครั้งเมื่อพูดจบ")
        if seconds >= (5 if self.test_microphone else 900):
            self.finish_recording()

    def finish_recording(self):
        self.recording = False
        self.record_timer.stop()
        valid = self.recorder.stop()
        self.record_button.setText("เริ่มพูด")
        if self.test_microphone:
            self.test_microphone = False
            self.audio_path.unlink(missing_ok=True)
            self.audio_path = None
            self.set_status("Microphone test finished" if valid else "No audio captured")
        elif valid:
            self.transcribe(self.audio_path, self.record_settings)
        else:
            self.error("No audio captured. Check the microphone.")

    def capture_error(self, message):
        self.cancel()
        self.error(message)

    def test_mic(self):
        if self.recording or self.jobs.busy:
            self.error("Finish the current job before testing the microphone")
            return
        self.test_microphone = True
        self.toggle_record()

    def open_audio(self):
        if self.recording or self.jobs.busy:
            self.error("Finish or cancel the current job first")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open audio", "", "Audio (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*)")
        if path:
            try:
                target = Path(self.temp.name) / (uuid.uuid4().hex + Path(path).suffix)
                shutil.copyfile(path, target)
                self.audio_path = target
                self.transcribe(target, self.current_settings())
            except Exception as exc:
                self.error(str(exc))

    def transcribe(self, path, settings):
        # Keep Retry attached to the audio the user just selected, including
        # when a model download temporarily prevents submitting that audio.
        self.last_request = (path, settings)
        try:
            if self.downloading_model == settings.model or (settings.profile == "th_to_eng" and self.downloading_model == "translate-th-en"):
                raise RuntimeError("Wait for the selected model download or repair to finish")
            self.jobs.submit(settings, action="transcribe", audio=str(path))
        except Exception as exc:
            self.error(str(exc))

    def retry(self):
        if self.recording or self.jobs.busy:
            self.error("Finish or cancel the current job first")
        elif self.last_request and self.last_request[0].exists():
            self.transcribe(self.last_request[0], self.current_settings())
        else:
            self.error("Record or open an audio file first")

    def translate(self):
        if self.jobs.busy or self.recording:
            self.error("Finish or cancel the current job first")
        elif self.downloading_model == "translate-th-en":
            self.error("Wait for the translation model download or repair to finish")
        elif self.editor.toPlainText().strip():
            try:
                self.jobs.submit(self.current_settings(), action="translate", text=self.editor.toPlainText())
            except Exception as exc:
                self.error(str(exc))

    def completed(self, result):
        job_settings = Settings(**result["settings"])
        if result.get("no_speech"):
            warnings = self.cleanup_temporary_audio()
            self.set_status("No speech detected. Check the microphone or disable speech detection for a quiet voice." +
                            (" " + "; ".join(warnings) if warnings else ""))
            return
        self.onboarding.hide()
        # A transcript must remain available even when optional persistence fails.
        self.editor.selectAll()
        self.editor.insertPlainText(result.get("text", ""))
        warnings = [result["warning"]] if result.get("warning") else []
        if not self.settings.onboarding_done and not self.settings_error:
            self.settings.onboarding_done = True
            try:
                save_settings(self.settings)
            except OSError as exc:
                self.settings.onboarding_done = False
                warnings.append(f"Transcript ready; could not save setup state: {exc}")
        self.metrics.setText(f"{result.get('model', '')} · {result.get('device', '')} · {result.get('elapsed', 0):.1f}s")
        if job_settings.keep_history:
            try:
                directory = data_dir() / "history"
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = directory / (result["id"] + ".txt")
                path.write_text(result.get("text", ""), encoding="utf-8")
                path.chmod(0o600)
            except OSError as exc:
                warnings.append(f"Transcript ready; history could not be saved: {exc}")
        if job_settings.keep_audio_history and result.get("source_audio"):
            created = False
            try:
                source = Path(result["source_audio"])
                directory = data_dir() / "audio-history"
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination = directory / (result["id"] + source.suffix)
                with destination.open("xb") as saved:
                    created = True
                    destination.chmod(0o600)
                    with source.open("rb") as original:
                        shutil.copyfileobj(original, saved)
            except OSError as exc:
                if created:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                warnings.append(f"Transcript ready; audio history could not be saved: {exc}")
        warnings.extend(self.cleanup_temporary_audio())
        self.set_status("; ".join(warnings) or "Transcript ready — edit, copy, or paste")
        if job_settings.paste_mode == "immediate" and result.get("text"):
            self.paste()
        else:
            self.showNormal()
            self.raise_()

    def cleanup_temporary_audio(self):
        retained = self.last_request[0] if self.last_request else None
        warnings = []
        for audio in Path(self.temp.name).iterdir():
            if audio.is_file() and audio != retained:
                try:
                    audio.unlink(missing_ok=True)
                except OSError as exc:
                    warnings.append(f"Could not remove temporary audio: {exc}")
        return warnings

    def cancel(self):
        self.paste_busy = False
        self.paste_timer.stop()
        self.clipboard.restore()
        if self.recording:
            self.record_timer.stop()
            self.recorder.stop()
            self.recording = False
            self.record_button.setText("เริ่มพูด")
            if self.audio_path:
                self.audio_path.unlink(missing_ok=True)
        self.test_microphone = False
        self.jobs.cancel()

    def copy(self):
        self.paste_busy = False
        self.paste_timer.stop()
        self.clipboard.restore()
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.set_status("Copied — clipboard kept for manual pasting")

    def paste(self):
        if self.paste_timer.isActive() or self.paste_busy:
            return
        if not self.editor.toPlainText():
            return
        if self.portal_permission_pending:
            self.error("Finish the desktop permission request before pasting")
            return
        if not self.paste_enabled:
            self.error("Enable paste permission in Settings first, or choose Copy")
            return
        self.clipboard.offer(self.editor.toPlainText())
        self.paste_busy = True
        self.set_status("Switch to your target app — sending paste in 3 seconds")
        self.showMinimized()
        self.paste_timer.start(3000)

    def send_paste(self):
        if self.portal_permission_pending:
            self.clipboard.restore()
            self.set_status("Paste cancelled while desktop permissions are being configured")
        elif self.clipboard.owns_clipboard():
            self.portal_command("paste")
        else:
            self.clipboard.restore()
            self.set_status("Paste cancelled because the clipboard changed")

    def portal_command(self, action, **options):
        if action == "paste" and (self.portal_permission_pending or not self.paste_busy
                                  or not self.paste_enabled or not self.clipboard.owns_clipboard()):
            self.clipboard.restore()
            return
        if action in {"shortcuts", "enable_paste", "restore"}:
            if self.portal_permission_pending:
                self.error("Finish the current desktop permission request first")
                return
            if self.paste_busy and not self.paste_timer.isActive():
                self.error("Wait for the current paste to finish before configuring permissions")
                return
            self.paste_timer.stop()
            self.clipboard.restore()
            self.paste_busy = False
            self.portal_permission_pending = True
        payload = json.dumps(dict(action=action, **options)) + "\n"
        if self.portal is None:
            self.portal = QProcess(self)
            self.portal.readyReadStandardOutput.connect(self.portal_output)
            self.portal.readyReadStandardError.connect(lambda: self.portal.readAllStandardError() if self.portal else None)
            self.portal.finished.connect(self.portal_finished)
            self.portal.errorOccurred.connect(self.portal_error)
            self.portal.started.connect(lambda: self.portal.write(payload.encode()) if self.portal else None)
            self.portal.start(sys.executable, ["-m", "phimthai.portals"])
        else:
            self.portal.write(payload.encode())

    def portal_output(self):
        self.portal_buffer += bytes(self.portal.readAllStandardOutput())
        while b"\n" in self.portal_buffer:
            line, self.portal_buffer = self.portal_buffer.split(b"\n", 1)
            try:
                response = json.loads(line)
            except ValueError:
                continue
            event = response.get("event")
            if event == "shortcut":
                self.toggle_record()
            elif event == "cycle_mode":
                self.cycle_profile()
            elif event == "mode_shortcut_enabled":
                self.portal_mode_shortcut = response.get("trigger", "")
                self.show_shortcut_status()
            elif event == "paste_enabled":
                self.paste_enabled = True
                self.set_status("Paste permission enabled" + ("; desktop supports restoring it on launch" if response.get("persistent") else " for this session"))
            elif event == "paste_sent":
                self.clipboard.restore_later()
                self.set_status("Paste keys sent. Check the target app; clipboard will be restored.")
            elif event == "shortcuts_enabled":
                self.portal_shortcut = response.get("trigger", "Configured by desktop")
                self.refresh_shortcut_status()
                self.set_status("Global shortcut: " + response.get("trigger", "Configured by desktop"))
            elif event == "shortcuts_disabled":
                self.portal_shortcut = ""
                self.portal_mode_shortcut = ""
                self.refresh_shortcut_status()
                self.set_status("No active global shortcut. Enable or configure one in Settings.")
            elif event == "paste_disabled":
                self.paste_enabled = False
            elif event == "error":
                self.clipboard.restore()
                self.error(response["error"])
            elif event == "warning":
                self.set_status(response["error"])
            elif event == "command_finished":
                self.portal_permission_pending = False

    def portal_finished(self):
        self.paste_enabled = False
        self.portal_permission_pending = False
        self.portal = None
        self.portal_buffer = b""
        self.portal_shortcut = ""
        self.portal_mode_shortcut = ""
        self.refresh_shortcut_status()
        self.clipboard.restore()

    def portal_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.portal_finished()
            self.error("Desktop integration could not start. You can retry or use Copy.")

    def selected_model(self):
        index = self.model_list.currentRow()
        return list(CATALOG)[max(0, index)]

    def refresh_models(self):
        current = self.model_list.currentRow()
        self.model_list.clear()
        for key, spec in CATALOG.items():
            size = installed_size(key)
            size_text = f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"
            status = f"Available · {size_text}" if size else "Not downloaded"
            self.model_list.addItem(f"{spec.name}\n{status}" + (" · Selected" if key == self.settings.model else ""))
        self.model_list.setCurrentRow(max(0, current))

    def model_details(self, _index):
        spec = CATALOG[self.selected_model()]
        from .performance import measurements
        rates = measurements().get(spec.id, {})
        formats = {"qwen": "SafeTensors", "openvino": "OpenVINO IR · INT8", "fastflowlm": "Q4NX", "marian": "PyTorch + SentencePiece", "vulkan": "GGML · Q5"}
        self.model_description.setText(f"{spec.repo}\n{', '.join(spec.languages)} · {spec.license}\nDownload: ~{spec.download_gb:.2f} GB · Estimated memory: {spec.memory_gb} GB\nBackend: {spec.backend} · Devices: {' / '.join(spec.devices)}\nFormat: {formats[spec.backend]}\nStatus: {spec.status}\nRevision: {spec.revision[:12]}\nMeasured seconds per audio second: {rates or 'No measurements yet'}")

    def refresh_device_choices(self):
        spec = CATALOG[self.settings.model]
        labels = {"openvino": "Intel GPU (OpenVINO)", "vulkan": "Hardware GPU (Vulkan)"}
        self.device.setItemText(self.device.findData("gpu"), labels.get(spec.backend, "GPU (compatible CUDA)"))
        from .fastflowlm_backend import available
        enabled = (spec.backend == "openvino" and "NPU" in openvino_devices()) or (spec.backend == "fastflowlm" and available())
        item = self.device.model().item(self.device.findData("npu"))
        item.setEnabled(enabled)
        item.setToolTip("Experimental NPU: test this model first and review its accuracy" if enabled else "Selected model and installed runtime have no available NPU. See Diagnostics.")
        if not enabled and self.device.currentData() == "npu":
            self.device.setCurrentIndex(self.device.findData("auto"))

    def download_model(self):
        if self.download_process:
            return
        model_id = self.selected_model()
        if model_id in {self.settings.model, "translate-th-en"}:
            if self.recording or self.jobs.busy:
                self.download_status.setText("Finish the current job before repairing its model")
                return
            self.jobs.stop_worker()
        self.downloading_model = model_id
        self.download_process = QProcess(self)
        self.download_buffer = b""
        self.download_process.readyReadStandardOutput.connect(self.download_output)
        self.download_process.readyReadStandardError.connect(lambda: self.download_process.readAllStandardError() if self.download_process else None)
        self.download_process.finished.connect(self.download_finished)
        self.download_process.errorOccurred.connect(self.download_error)
        self.download_process.start(sys.executable, ["-m", "phimthai.models", model_id])
        self.download_progress.setRange(0, 0)
        self.download_status.setText("Downloading model files… You can keep using the app.")

    def download_output(self):
        self.download_buffer += bytes(self.download_process.readAllStandardOutput())
        while b"\n" in self.download_buffer:
            line, self.download_buffer = self.download_buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if "error" in event:
                self.download_status.setText(event["error"])
            else:
                self.download_progress.setRange(0, 100)
                self.download_progress.setValue(int(event.get("completed", 0) / max(1, event.get("total", 1)) * 100))
                self.download_status.setText("Verified and ready" if event.get("done") else "Downloading: " + event.get("file", ""))

    def download_finished(self, code, _status):
        self.download_process = None
        self.downloading_model = None
        self.download_progress.setRange(0, 100)
        if code:
            self.download_status.setText("Download stopped. Select Download to resume. " + self.download_status.text())
        self.refresh_models()

    def download_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.download_process = None
            self.downloading_model = None
            self.download_progress.setRange(0, 100)
            self.download_status.setText("Could not start download worker. Select Download to retry.")

    def cancel_download(self):
        if self.download_process:
            self.download_process.kill()

    def use_model(self):
        if self.recording or self.jobs.busy:
            self.download_status.setText("Finish the current job before switching models")
            return
        model_id = self.selected_model()
        if model_id == self.downloading_model:
            self.download_status.setText("Wait for this model download to finish")
            return
        if CATALOG[model_id].kind != "asr":
            self.download_status.setText("This translation model is used by Translate and the Thai to English profile")
            return
        if local_model(model_id) is None:
            self.download_status.setText("Download this model first")
            return
        selected = replace(self.settings, model=model_id)
        try:
            save_settings(selected)
        except OSError as exc:
            self.download_status.setText(f"Could not save model selection: {exc}")
            return
        self.settings = selected
        self.jobs.stop_worker()
        self.refresh_models()
        self.refresh_device_choices()

    def remove_model(self):
        model_id = self.selected_model()
        if self.jobs.busy or self.recording or self.download_process:
            self.download_status.setText("Finish active jobs and downloads before removing a model")
            return
        if not model_dir(model_id).exists():
            self.download_status.setText("This model belongs to the legacy installation. Its cache is preserved.")
            return
        if QMessageBox.question(self, "Remove model", "Remove downloaded files for this model? You can download them again.") == QMessageBox.StandardButton.Yes:
            self.jobs.stop_worker()
            remove(model_id)
            self.refresh_models()

    def refresh_diagnostics(self):
        state = inventory()
        from .fastflowlm_backend import available, runtime_path
        from .vulkan_backend import runtime_path as vulkan_runtime
        state["amd_runtime"] = str(runtime_path() or "Not installed")
        state["amd_runtime_and_device_available"] = available()
        state["vulkan_runtime_installed"] = vulkan_runtime() is not None
        state["npu_note"] = "Patched AMD FastFlowLM passed initial ASR samples on Ryzen AI 5 340; experimental quality. Intel NPU needs hardware testing."
        state["model"] = self.settings.model
        state["data_directory"] = str(data_dir())
        microphone_count = len(QMediaDevices.audioInputs())
        model_ready = local_model(self.settings.model) is not None
        summary = [f"ไมโครโฟน / Microphones: {microphone_count}",
                   "โมเดล / Model: " + ("Downloaded — ready for verification when used" if model_ready else "Choose and download a model in Models"),
                   "CPU: available. Auto starts with CPU until comparable speed measurements exist."]
        if not microphone_count:
            summary.append("Connect a microphone and allow microphone access in your system's application permissions.")
        if state["vulkan_runtime_installed"]:
            summary.append("GPU: choose Whisper Turbo Vulkan in Models, then GPU in Settings. The result shows the device actually used.")
        if available():
            summary.append("AMD NPU: runtime and device found. Choose the AMD NPU model and NPU manually; speech quality is experimental.")
        elif state["flatpak"]:
            summary.append("NPU is unavailable in this sandbox. CPU works with the standard permissions. Experimental NPU setup needs compatible host drivers, runtime and device access.")
        else:
            summary.append("NPU: install a compatible vendor runtime and host driver before testing. Hardware detection alone does not enable ASR.")
        summary.append("ปุ่มลัดและวาง / Shortcut and paste: enable each in Settings and respond to your desktop's permission dialog.")
        self.diagnostic_summary.setText("\n\n".join(summary))
        self.diagnostics.setPlainText(json.dumps(state, ensure_ascii=False, indent=2))

    def clear_history(self):
        if QMessageBox.question(self, "Clear history", "Delete all text and audio history saved by this app?") == QMessageBox.StandardButton.Yes:
            try:
                for directory in (data_dir() / "history", data_dir() / "audio-history"):
                    for file in directory.glob("*"):
                        if file.is_file():
                            file.unlink()
                self.set_status("Saved text and audio history cleared")
            except OSError as exc:
                self.error(f"Some saved history could not be removed: {exc}")

    def closeEvent(self, event):
        if self.tray and self.tray.isVisible() and not self.quitting:
            self.hide()
            event.ignore()
            return
        self.quitting = True
        self.cancel()
        self.clipboard.restore()
        if self.shortcut_process and self.shortcut_installing:
            # Let the desktop transaction finish or roll back before exiting.
            self.set_status("กำลังตั้งปุ่มลัด รอสักครู่แล้วแอปจะปิดให้")
            event.ignore()
            return
        if self.shortcut_process:
            self.shortcut_process.kill()
            self.shortcut_process.waitForFinished(3000)
        if self.download_process:
            self.download_process.kill()
            self.download_process.waitForFinished(3000)
        if self.portal:
            self.portal.kill()
            self.portal.waitForFinished(3000)
        self.temp.cleanup()
        event.accept()

    def quit(self):
        self.quitting = True
        self.close()
        if not (self.shortcut_process and self.shortcut_installing):
            QApplication.instance().quit()

    def setup_tray(self):
        quit_action = QAction("ออกจาก PhimThaiMaiPen", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        menu_bar = self.menuBar().addMenu("แอป")
        clear_action = QAction("ล้างข้อความและเสียงชั่วคราว", self)
        clear_action.setShortcut("Ctrl+L")
        clear_action.triggered.connect(self.clear_current)
        menu_bar.addAction(clear_action)
        menu_bar.addAction(quit_action)
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon_path = Path(__file__).parent / "assets" / (APP_ID + ".svg")
            icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon.fromTheme("audio-input-microphone")
            self.setWindowIcon(icon)
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("PhimThaiMaiPen · Voice typing")
            menu = QMenu(self)
            menu.addAction("เปิด PhimThaiMaiPen", self.showNormal)
            menu.addAction("เริ่ม / หยุดพูด", self.toggle_record)
            menu.addAction("ยกเลิก", self.cancel)
            menu.addSeparator()
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

    def clear_current(self):
        self.cancel()
        self.editor.clear()
        self.last_request = None
        self.audio_path = None
        for audio in Path(self.temp.name).iterdir():
            if audio.is_file():
                audio.unlink(missing_ok=True)
        self.set_status("Transcript and temporary audio cleared")


def single_instance(app):
    """Keep one application and forward launcher actions without stale PID files."""
    name = APP_ID + "-" + str(os.getuid())
    lock_path = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / (name + ".lock")
    app.instance_lock = QLockFile(str(lock_path))
    app.instance_lock.setStaleLockTime(0)
    if not app.instance_lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(2000):
            command = b"toggle\n" if "--toggle" in sys.argv else b"cycle-mode\n" if "--cycle-mode" in sys.argv else b"show\n"
            socket.write(command)
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return None
        raise RuntimeError("PhimThaiMaiPen is already running but did not respond")
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        raise RuntimeError(server.errorString())
    return server


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PhimThaiMaiPen")
    app.setOrganizationName("PhimThaiMaiPen")
    app.setDesktopFileName(APP_ID)
    if "--status" in sys.argv:
        socket = QLocalSocket()
        socket.connectToServer(APP_ID + "-" + str(os.getuid()))
        if not socket.waitForConnected(1500):
            print(json.dumps({"running": False}))
            return 1
        socket.write(b"status\n")
        socket.waitForBytesWritten(1000)
        if not socket.waitForReadyRead(2000):
            print(json.dumps({"running": True, "error": "Application did not report its status"}))
            return 2
        print(bytes(socket.readAll()).decode().strip())
        return 0
    server = single_instance(app)
    if server is None:
        return 0
    apply_style(app)
    window = MainWindow()
    def receive():
        socket = server.nextPendingConnection()
        def read_command():
            command = bytes(socket.readAll()).strip()
            if command == b"toggle":
                window.toggle_record()
            elif command == b"cycle-mode":
                window.cycle_profile()
            elif command == b"show":
                window.showNormal()
                window.raise_()
                window.activateWindow()
            elif command == b"status":
                socket.write((json.dumps({"running": True, "pid": os.getpid(),
                    "version": __version__, "recording": window.recording,
                    "busy": window.jobs.busy, "transcript_characters": len(window.editor.toPlainText()),
                    "shortcut": window.shortcut_hint.text(), "mode_shortcut": window.mode_shortcut_hint.text(),
                    "profile": window.profile.currentData(), "visible": window.isVisible()}) + "\n").encode())
                socket.flush()
            socket.disconnectFromServer()
            socket.deleteLater()
        socket.readyRead.connect(read_command)
        if socket.bytesAvailable():
            read_command()
    server.newConnection.connect(receive)
    window.show()
    if "--smoke" in sys.argv:
        QTimer.singleShot(1000, window.quit)
    elif "--toggle" in sys.argv:
        QTimer.singleShot(0, window.toggle_record)
    elif "--cycle-mode" in sys.argv:
        QTimer.singleShot(0, window.cycle_profile)
    return app.exec()
