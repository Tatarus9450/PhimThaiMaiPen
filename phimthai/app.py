"""Native desktop application; model work never runs on the UI thread."""
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections import deque
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QLockFile, QProcess, QTimer, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QMenu, QSystemTrayIcon, QScrollArea)

from . import APP_ID, __version__
from . import strings as S
from .audio import Recorder
from .app_pages import PagesMixin
from .appearance import GlassCanvas, GlassPanel, apply_style
from .clipboard import ClipboardTransaction
from .devices import inventory, openvino_devices
from .feedback import DictationFeedback
from .jobs import JobController
from .models import CATALOG, installed_size, local_model, model_dir, refresh_catalog, remove
from .settings import DEFAULT_MODEL, Settings, data_dir, load_settings, save_settings
from .state import Debouncer, DictationState, derive_state

try:  # Settings repair report (newer settings module); optional.
    from .settings import load_settings_with_report
except ImportError:  # pragma: no cover - older settings module
    load_settings_with_report = None

LOG = logging.getLogger("phimthai.app")
PROFILE_NAMES = S.PROFILE_NAMES
BETA_WARNING = S.BETA_WARNING
TOGGLE_DEBOUNCE_SECONDS = 0.4
MANUAL_PASTE_DELAY_MS = 3000
AUTOMATIC_PASTE_DELAY_MS = 250
STATE_COLORS = {DictationState.RECORDING: "#d93644", DictationState.PROCESSING: "#e0a020",
                DictationState.PASTING: "#2f7de1"}


def _available_memory_gb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _initial_window_size():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1060, 760
    available = screen.availableGeometry()
    return (
        min(1060, max(820, available.width() - 32)),
        min(760, max(600, available.height() - 32)),
    )


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    widget.setMinimumHeight(36)
    if primary:
        widget.setProperty("primary", True)
    return widget


class MainWindow(PagesMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        refresh_catalog()
        self.settings_error = ""
        self.settings_warnings = []
        self.load_initial_settings()
        self.setWindowTitle(S.APP_TITLE)
        self.app_icon = QIcon(str(Path(__file__).parent / "assets" / (APP_ID + ".png")))
        self.setWindowIcon(self.app_icon)
        self.resize(*_initial_window_size())
        self.setMinimumSize(820, 600)
        self.temp = tempfile.TemporaryDirectory(prefix="phimthai-", dir=os.environ.get("XDG_RUNTIME_DIR"))
        self._state = DictationState.IDLE
        self._recording = False
        self.toggle_debounce = Debouncer(TOGGLE_DEBOUNCE_SECONDS)
        self.test_microphone = False
        self.audio_path = None
        self.record_settings = self.settings
        self.download_process = None
        self.downloading_model = None
        self.download_buffer = b""
        self.download_cancelled = False
        self.download_failure = ""
        self.importing = False
        self.imported_model = None
        self.model_process_pid = 0
        self.startup_started = False
        self.startup_action = ""
        self.startup_prewarmed = False
        self.desktop_queue = []
        self.desktop_starting = False
        self.desktop_setup_active = False
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
        self.tray_icons = {}
        headless = QGuiApplication.platformName() in {"offscreen", "minimal"}
        self.feedback = DictationFeedback(self, sound_enabled=self.settings.sound_feedback and not headless,
                                         popup_enabled=self.settings.popup_enabled and not headless)
        self.feedback.set_profile(self.settings.profile)
        self.jobs = JobController(self, temp_root=self.temp.name)
        self.jobs.changed.connect(self.job_status_changed)
        self.jobs.result.connect(self.completed)
        self.jobs.failed.connect(self.job_failed)
        warm_changed = getattr(self.jobs, "warm_changed", None)
        if warm_changed is not None and hasattr(warm_changed, "connect"):
            warm_changed.connect(self.warm_changed)
        self.recorder = Recorder(self)
        self.recorder.failed.connect(self.capture_error)
        self.clipboard = ClipboardTransaction(self)
        self.paste_busy = False
        self.paste_request_id = None
        self.paste_inflight = None
        self.paste_committed = False
        self.paste_queue = deque()
        self.clipboard.restored.connect(self.clipboard_restored)
        self.paste_timer = QTimer(self)
        self.paste_timer.setSingleShot(True)
        self.paste_timer.timeout.connect(self.send_paste)
        self.paste_countdown = QTimer(self)
        self.paste_countdown.setInterval(250)
        self.paste_countdown.timeout.connect(self.paste_countdown_tick)
        self.paste_deadline = 0.0
        self.build_ui()
        self.feedback.unavailable.connect(self.set_status)
        self.recorder.media_devices.audioInputsChanged.connect(self.refresh_microphones_page)
        self.recorder.level.connect(self.level.setValue)
        if callable(getattr(self.feedback, "level", None)):
            self.recorder.level.connect(self.feedback.level)
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.record_tick)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.escape_shortcut.activated.connect(self.escape_pressed)
        self.statusBar().showMessage(S.STATUS_BAR.format(version=__version__))
        self.refresh_models()
        self.refresh_device_choices()
        self.setup_tray()
        apply_style(QApplication.instance(), reduced_transparency=self.settings.reduced_transparency)
        self.refresh_shortcut_status()
        self.update_unsaved_indicator()
        if self.settings_error:
            self.set_status(self.settings_error)
        elif self.settings_warnings:
            self.set_status(S.SETTINGS_REPAIRED.format(warnings=" · ".join(self.settings_warnings)))
        elif local_model(self.settings.model) is None:
            self.set_status(S.STATUS_NEED_MODEL)
        else:
            self.set_status(S.STATUS_READY)

    def load_initial_settings(self):
        """Load settings; a repaired file is saved and reported, never a first-run blocker."""
        try:
            if load_settings_with_report is not None:
                self.settings, warnings = load_settings_with_report()
                self.settings_warnings = [str(item) for item in (warnings or []) if str(item).strip()]
            else:
                self.settings = load_settings()
        except Exception as exc:
            # Only an unreadable/unsupported file reaches here; keep it intact.
            self.settings = Settings()
            self.settings_error = S.SETTINGS_LOAD_FAILED.format(error=exc)
            LOG.warning("settings could not load: %s", exc)
            return
        if self.settings_warnings:
            LOG.warning("settings repaired: %s", "; ".join(self.settings_warnings))
            try:
                save_settings(self.settings)
            except (OSError, ValueError) as exc:
                self.settings_warnings.append(S.SETTINGS_REPAIR_SAVE_FAILED.format(error=exc))

    # ----- dictation state -------------------------------------------------
    @property
    def recording(self):
        return self._recording

    @recording.setter
    def recording(self, value):
        self._recording = bool(value)
        self.refresh_state()

    def paste_pending(self):
        timer = getattr(self, "paste_timer", None)
        return bool(getattr(self, "paste_busy", False) or getattr(self, "paste_inflight", None)
                    or (timer is not None and timer.isActive()))

    def jobs_busy(self):
        jobs = getattr(self, "jobs", None)
        return bool(jobs is not None and jobs.busy is True)

    @property
    def state(self):
        return derive_state(recording=self._recording, pasting=self.paste_pending(),
                            processing=self.jobs_busy())

    def refresh_state(self):
        """The single transition point: log, then update tray tooltip/icon."""
        new = self.state
        if new is self._state:
            return new
        LOG.info("state %s -> %s", self._state.value, new.value)
        self._state = new
        self.update_tray_state()
        control = getattr(self, "record_button", None)
        if control is not None:
            # Styled by appearance.py as QPushButton#recordControl[state=...].
            control.setProperty("state", new.value)
            control.style().unpolish(control)
            control.style().polish(control)
        return new

    def update_tray_state(self):
        if self.tray is None:
            return
        state = self._state
        self.tray.setToolTip({DictationState.RECORDING: S.TRAY_RECORDING,
                              DictationState.PROCESSING: S.TRAY_PROCESSING,
                              DictationState.PASTING: S.TRAY_PASTING}.get(state, S.TRAY_IDLE))
        self.tray.setIcon(self.state_icon(state))

    def state_icon(self, state):
        if state not in STATE_COLORS:
            return self.app_icon
        if state not in self.tray_icons:
            pixmap = self.app_icon.pixmap(64, 64)
            if pixmap.isNull():
                pixmap = QPixmap(64, 64)
                pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("white"))
            painter.setBrush(QColor(STATE_COLORS[state]))
            painter.drawEllipse(38, 38, 24, 24)
            painter.end()
            self.tray_icons[state] = QIcon(pixmap)
        return self.tray_icons[state]

    def queued_jobs(self):
        """Jobs ahead of a new submission (active + pending, without warmups)."""
        jobs = self.jobs
        try:
            waiting = list(jobs.pending)
        except (AttributeError, TypeError):
            waiting = []
        active = getattr(jobs, "active", None)
        if isinstance(active, dict):
            waiting.append(active)
        return sum(1 for job in waiting if not (isinstance(job, dict) and job.get("action") == "warmup"))

    def queue_full(self):
        try:
            return len(self.jobs.pending) >= 4
        except (AttributeError, TypeError):
            return False

    def prewarm(self, settings):
        prewarm = getattr(self.jobs, "prewarm", None)
        if not callable(prewarm):
            return False
        try:
            prewarm(settings)
        except Exception as exc:  # Prewarming is an optimization only.
            LOG.warning("prewarm failed: %s", exc)
            return False
        return True

    def jobs_warm(self):
        warm = getattr(self.jobs, "warm", True)
        return warm is not False

    def warm_changed(self, warm):
        if warm:
            model_ready = getattr(self.feedback, "model_ready", None)
            if callable(model_ready):
                model_ready()
            if self.recording and self.status.text() == S.STATUS_PREPARING:
                self.set_status(S.STATUS_LISTENING)

    def startup_prewarm(self):
        """Load the local model once desktop setup is done so the first Meta+H is fast."""
        if self.startup_prewarmed or self.quitting or self.settings_error:
            return
        self.startup_prewarmed = True
        if self.downloading_model == self.settings.model or local_model(self.settings.model) is None:
            return
        spec = CATALOG.get(self.settings.model)
        available = _available_memory_gb()
        needed = float(getattr(spec, "memory_gb", 0) or 0)
        if available is not None and needed and available < needed * 1.5:
            LOG.info("startup prewarm skipped: %.1f GB available, model needs about %.1f GB", available, needed)
            return
        if self.prewarm(self.settings):
            LOG.info("startup prewarm requested for %s", self.settings.model)

    def start_first_run(self):
        """Called only by the interactive entry point, never by construction."""
        if self.startup_started or self.quitting or self.settings_error:
            return
        self.startup_started = True
        if self.startup_action and local_model(self.settings.model) is None:
            # A first-ever hotkey launch opens setup, never starts listening
            # unexpectedly several minutes later when a download completes.
            self.startup_action = ""
            self.showNormal()
        if self.settings.model_setup in {"pending", "downloading"}:
            if local_model(self.settings.model) is not None:
                self.save_setup(model_setup="complete")
            elif self.settings.model == DEFAULT_MODEL:
                if self.save_setup(model_setup="downloading"):
                    self.download_model(model_id=DEFAULT_MODEL)
        self.desktop_starting = True
        self.continue_desktop_setup()

    def save_setup(self, **changes):
        try:
            updated = replace(self.settings, **changes)
            save_settings(updated)
            self.settings = updated
            return True
        except (OSError, ValueError) as exc:
            self.set_status(S.SETUP_SAVE_FAILED.format(error=exc))
            return False

    def continue_desktop_setup(self):
        if self.quitting or self.settings_error or not self.desktop_starting:
            return
        if self.shortcut_process is not None or self.portal_permission_pending:
            return
        self.desktop_starting = False
        fresh = not self.settings.desktop_setup_done
        self.desktop_setup_active = fresh
        native_ready = self.kde_shortcut_state.get("active") and self.kde_shortcut_state.get("mode_active")
        if self.settings.remember_desktop:
            self.desktop_queue.append(("restore", {"skip_shortcuts": bool(native_ready)}))
        if fresh:
            if not native_ready:
                self.desktop_queue.append(("shortcuts", {}))
            self.desktop_queue.append(("enable_paste", {}))
        self.next_desktop_request()

    def next_desktop_request(self):
        if self.quitting or self.portal_permission_pending or self.shortcut_process is not None:
            return
        while self.desktop_queue:
            action, options = self.desktop_queue.pop(0)
            if action == "shortcuts":
                if self.portal_shortcut or self.portal_mode_shortcut:
                    # Do not launch ConfigureShortcuts during automatic setup.
                    # Partial bindings remain visible for the user to repair.
                    continue
                self.enable_shortcut()
            elif action == "enable_paste":
                if self.paste_enabled:
                    continue
                self.portal_command(action, persist=self.settings.remember_desktop)
            else:
                self.portal_command(action, **options)
            return
        if self.desktop_setup_active:
            self.save_setup(desktop_setup_done=True)
            self.desktop_setup_active = False
        self.update_setup_view()
        if self.startup_action:
            action, self.startup_action = self.startup_action, ""
            self.toggle_record() if action == "toggle" else self.cycle_profile()
        if self.startup_started:
            # Desktop setup is finished; warm the model for the first hotkey.
            self.startup_prewarm()

    def update_setup_view(self):
        if not hasattr(self, "setup_message"):
            return
        ready = local_model(self.settings.model) is not None
        self.record_button.setEnabled(self.recording or
                                      (ready and self.downloading_model != self.settings.model))
        if self.download_process and (self.downloading_model == self.settings.model or self.importing):
            self.setup_message.setText(self.download_status.text())
            self.setup_progress.setRange(self.download_progress.minimum(), self.download_progress.maximum())
            self.setup_progress.setValue(self.download_progress.value())
        elif not ready:
            self.setup_message.setText(S.SETUP_NO_MODEL)
            self.setup_progress.setRange(0, 100)
            self.setup_progress.setValue(0)
        else:
            self.setup_message.setText(S.SETUP_MODEL_READY)
            self.setup_progress.setRange(0, 100)
            self.setup_progress.setValue(100)
        if self.download_failure:
            self.setup_message.setText(self.download_status.text())
        self.setup_stop.setVisible(bool(self.download_process))
        self.setup_resume.setVisible(not ready and not self.download_process)
        self.setup_progress.setVisible(not ready or bool(self.download_process))
        shortcut_ready = bool((self.kde_shortcut_state.get("active") and self.kde_shortcut_state.get("mode_active"))
                              or (self.portal_shortcut and self.portal_mode_shortcut))
        self.onboarding.setVisible(self.setup_wizard.isHidden() and
                                   (not ready or not shortcut_ready or not self.paste_enabled or bool(self.download_process)))
        if self.portal_permission_pending or self.shortcut_installing:
            self.setup_desktop.setText(S.SETUP_DESKTOP_PENDING)
        elif shortcut_ready and self.paste_enabled:
            self.setup_desktop.setText(S.SETUP_DESKTOP_READY)
        else:
            missing = []
            if not shortcut_ready:
                missing.append(S.SETUP_MISSING_SHORTCUT)
            if not self.paste_enabled:
                missing.append(S.SETUP_MISSING_PASTE)
            self.setup_desktop.setText(" · ".join(missing) + S.SETUP_MISSING_SUFFIX)
        self.sync_setup_wizard()

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
        identity = QHBoxLayout()
        identity.setSpacing(9)
        mascot = QLabel()
        mascot.setPixmap(self.app_icon.pixmap(44, 44))
        mascot.setFixedSize(44, 44)
        mascot.setAccessibleName(S.MASCOT_ACCESSIBLE)
        identity.addWidget(mascot)
        brand = QLabel(S.BRAND)
        brand.setObjectName("brand")
        identity.addWidget(brand)
        sidebar.addLayout(identity)
        sidebar.addSpacing(24)
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.setAccessibleName(S.NAV_ACCESSIBLE)
        self.nav.addItems(list(S.NAV_PAGES))
        for index, tooltip in enumerate(S.NAV_TOOLTIPS):
            self.nav.item(index).setToolTip(tooltip)
        sidebar.addWidget(self.nav)
        self.shortcut_hint = QLabel(self.settings.hotkey.replace("META", "Meta"))
        self.shortcut_hint.setObjectName("shortcut")
        self.shortcut_hint.setToolTip(S.SHORTCUT_HINT_TOOLTIP)
        sidebar.addWidget(self.shortcut_hint)
        self.mode_button = button(PROFILE_NAMES[self.settings.profile], self.cycle_profile)
        self.mode_button.setObjectName("modeSwitch")
        self.mode_button.setToolTip(S.MODE_TOOLTIP)
        sidebar.addWidget(self.mode_button)
        self.mode_shortcut_hint = QLabel("")
        self.mode_shortcut_hint.setObjectName("muted")
        sidebar.addWidget(self.mode_shortcut_hint)
        footer = QLabel(S.SIDEBAR_FOOTER)
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
        self.build_models_page()
        self.build_settings_page()
        self.build_diagnostics_page()
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
        layout = self.page(S.TRANSCRIPT_TITLE, S.TRANSCRIPT_SUBTITLE)
        self.onboarding = QWidget()
        self.onboarding.setObjectName("onboarding")
        first_run = QVBoxLayout(self.onboarding)
        first_run.setContentsMargins(14, 12, 14, 12)
        self.setup_message = QLabel(S.SETUP_INTRO)
        self.setup_message.setObjectName("setupMessage")
        self.setup_message.setWordWrap(True)
        first_run.addWidget(self.setup_message)
        self.setup_progress = QProgressBar()
        self.setup_progress.setValue(0)
        self.setup_progress.setAccessibleName(S.SETUP_PROGRESS_ACCESSIBLE)
        first_run.addWidget(self.setup_progress)
        self.setup_desktop = QLabel(S.SETUP_DESKTOP_INTRO)
        self.setup_desktop.setWordWrap(True)
        first_run.addWidget(self.setup_desktop)
        first_actions = QHBoxLayout()
        self.setup_resume = button(S.BTN_RESUME_DOWNLOAD, lambda: self.download_model(model_id=self.settings.model), True)
        self.setup_stop = button(S.BTN_STOP_DOWNLOAD, self.cancel_download)
        first_actions.addWidget(self.setup_resume)
        first_actions.addWidget(self.setup_stop)
        first_actions.addWidget(button(S.BTN_MANAGE_MODELS, lambda: self.nav.setCurrentRow(1)))
        first_actions.addWidget(button(S.BTN_PERMISSIONS, lambda: self.nav.setCurrentRow(2)))
        first_run.addLayout(first_actions)
        self.setup_resume.hide()
        self.setup_stop.hide()
        self.onboarding.setVisible(local_model(self.settings.model) is None)
        # First run gets the wizard; the compact banner covers later gaps.
        layout.addWidget(self.build_setup_wizard())
        layout.addWidget(self.onboarding)
        row = QHBoxLayout()
        self.record_button = button(S.BTN_RECORD, self.toggle_record, True)
        self.record_button.setObjectName("recordControl")
        self.record_button.setMinimumSize(168, 48)
        self.record_button.setToolTip(S.RECORD_TOOLTIP)
        row.addWidget(self.record_button)
        row.addWidget(button(S.BTN_OPEN_AUDIO, self.open_audio))
        row.addStretch()
        self.cancel_button = button(S.BTN_CANCEL, self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(8)
        self.level.setAccessibleName(S.LEVEL_ACCESSIBLE)
        layout.addWidget(self.level)
        self.status = QLabel(S.STATUS_IDLE)
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        transcript_label = QLabel(S.TRANSCRIPT_LABEL)
        transcript_label.setObjectName("section")
        layout.addWidget(transcript_label)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("editor")
        self.editor.setPlaceholderText(S.EDITOR_PLACEHOLDER)
        self.editor.setAccessibleName(S.EDITOR_ACCESSIBLE)
        layout.addWidget(self.editor, 1)
        actions = QHBoxLayout()
        paste_button = button(S.BTN_PASTE, lambda: self.paste())
        paste_button.setObjectName("pasteAction")
        actions.addWidget(paste_button)
        actions.addWidget(button(S.BTN_COPY, self.copy))
        actions.addStretch()
        actions.addWidget(button(S.BTN_TRANSLATE, self.translate))
        actions.addWidget(button(S.BTN_RETRY, self.retry))
        layout.addLayout(actions)
        self.metrics = QLabel(S.METRICS_PLACEHOLDER.format(model=CATALOG[self.settings.model].name))
        self.metrics.setObjectName("muted")
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)

    def build_models(self):
        layout = self.page(S.MODELS_TITLE, S.MODELS_SUBTITLE)
        self.model_list = QListWidget()
        self.model_list.currentRowChanged.connect(self.model_details)
        layout.addWidget(self.model_list)
        self.model_description = QLabel()
        self.model_description.setWordWrap(True)
        self.model_description.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.model_description)
        technical_toggle = QCheckBox(S.MODELS_TECHNICAL)
        layout.addWidget(technical_toggle)
        self.model_technical = QLabel()
        self.model_technical.setObjectName("muted")
        self.model_technical.setWordWrap(True)
        self.model_technical.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.model_technical)
        self.model_technical.hide()
        technical_toggle.toggled.connect(self.model_technical.setVisible)
        self.model_beta_warning = QLabel(BETA_WARNING)
        self.model_beta_warning.setObjectName("betaWarning")
        self.model_beta_warning.setWordWrap(True)
        layout.addWidget(self.model_beta_warning)
        actions = QHBoxLayout()
        self.download_button = button(S.BTN_DOWNLOAD, self.download_model, True)
        actions.addWidget(self.download_button)
        actions.addWidget(button(S.BTN_STOP_DOWNLOAD_SHORT, self.cancel_download))
        actions.addStretch()
        actions.addWidget(button(S.BTN_USE_MODEL, self.use_model))
        actions.addWidget(button(S.BTN_REMOVE_MODEL, self.remove_model))
        layout.addLayout(actions)
        self.import_button = button(S.BTN_IMPORT_MODEL, self.import_model)
        layout.addWidget(self.import_button)
        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)
        self.download_status = QLabel(S.DOWNLOAD_HINT)
        self.download_status.setWordWrap(True)
        layout.addWidget(self.download_status)
        layout.addStretch()

    def build_settings(self):
        layout = self.page(S.SETTINGS_TITLE, S.SETTINGS_SUBTITLE)
        actions = QHBoxLayout()
        actions.addWidget(button(S.BTN_SAVE, self.save, True))
        self.unsaved_label = QLabel(S.SETTINGS_UNSAVED)
        self.unsaved_label.setObjectName("unsaved")
        self.unsaved_label.setAccessibleName(S.SETTINGS_UNSAVED)
        self.unsaved_label.hide()
        actions.addWidget(self.unsaved_label)
        actions.addStretch()
        actions.addWidget(button(S.BTN_ENABLE_SHORTCUT, self.enable_shortcut))
        actions.addWidget(button(S.BTN_ENABLE_PASTE, lambda: self.portal_command("enable_paste", persist=self.remember_desktop.isChecked())))
        layout.addLayout(actions)
        form = QFormLayout()
        form.setSpacing(12)
        self.microphone = QComboBox()
        self.refresh_microphones()
        form.addRow(S.LABEL_MICROPHONE, self.microphone)
        mic_actions = QHBoxLayout()
        mic_actions.addWidget(button(S.BTN_REFRESH_MICS, self.refresh_microphones))
        mic_actions.addWidget(button(S.BTN_TEST_MIC, self.test_mic))
        form.addRow(mic_actions)
        self.profile = self.combo(S.PROFILE_CHOICES, self.settings.profile)
        self.profile.currentIndexChanged.connect(lambda: self.mode_button.setText(PROFILE_NAMES[self.profile.currentData()]))
        form.addRow(S.LABEL_PROFILE, self.profile)
        self.language = self.combo(S.LANGUAGE_CHOICES, self.settings.language)
        form.addRow(S.LABEL_LANGUAGE, self.language)
        self.language_hint = QLabel(S.LANGUAGE_HINT)
        self.language_hint.setWordWrap(True)
        self.language_hint.setObjectName("muted")
        form.addRow(self.language_hint)
        self.device = self.combo(S.DEVICE_CHOICES, self.settings.device)
        form.addRow(S.LABEL_DEVICE, self.device)
        for value in ("gpu", "npu"):
            self.device.setItemData(self.device.findData(value), QBrush(QColor("#9b2c39")), Qt.ItemDataRole.ForegroundRole)
        self.beta_warning = QLabel(BETA_WARNING)
        self.beta_warning.setWordWrap(True)
        self.beta_warning.setObjectName("betaWarning")
        form.addRow(self.beta_warning)
        self.preference = self.combo(S.PREFERENCE_CHOICES, self.settings.preference)
        self.preference.hide()  # Auto remains on CPU until accelerators leave Beta.
        self.threads = QSpinBox()
        self.threads.setRange(1, os.cpu_count() or 1)
        self.threads.setValue(self.settings.cpu_threads)
        form.addRow(S.LABEL_THREADS, self.threads)
        self.paste_mode = self.combo(S.PASTE_MODE_CHOICES, self.settings.paste_mode)
        form.addRow(S.LABEL_PASTE_MODE, self.paste_mode)
        self.hotkey = QLineEdit(self.settings.hotkey)
        form.addRow(S.LABEL_HOTKEY, self.hotkey)
        self.shortcut_status = QLabel(S.SHORTCUT_CHECKING)
        self.shortcut_status.setObjectName("muted")
        self.shortcut_status.setWordWrap(True)
        form.addRow(self.shortcut_status)
        self.history = QCheckBox(S.CHECK_HISTORY)
        self.history.setChecked(self.settings.keep_history)
        form.addRow(self.history)
        self.audio_history = QCheckBox(S.CHECK_AUDIO_HISTORY)
        self.audio_history.setChecked(self.settings.keep_audio_history)
        form.addRow(self.audio_history)
        self.vad = QCheckBox(S.CHECK_VAD)
        self.vad.setChecked(self.settings.vad)
        form.addRow(self.vad)
        self.reduced_transparency = QCheckBox(S.CHECK_REDUCED_TRANSPARENCY)
        self.reduced_transparency.setChecked(self.settings.reduced_transparency)
        self.reduced_transparency.toggled.connect(lambda checked: apply_style(QApplication.instance(), reduced_transparency=checked))
        form.addRow(self.reduced_transparency)
        self.popup_enabled = QCheckBox(S.CHECK_POPUP)
        self.popup_enabled.setChecked(self.settings.popup_enabled)
        form.addRow(self.popup_enabled)
        self.sound_feedback = QCheckBox(S.CHECK_SOUND)
        self.sound_feedback.setChecked(self.settings.sound_feedback)
        form.addRow(self.sound_feedback)
        layout.addLayout(form)
        layout.addWidget(QLabel(S.DICTIONARY_LABEL))
        self.dictionary = QPlainTextEdit(self.settings.dictionary)
        self.dictionary.setAccessibleName(S.DICTIONARY_ACCESSIBLE)
        self.dictionary.setMaximumHeight(100)
        layout.addWidget(self.dictionary)
        self.remember_desktop = QCheckBox(S.CHECK_REMEMBER_DESKTOP)
        self.remember_desktop.setChecked(self.settings.remember_desktop)
        self.remember_desktop.setToolTip(S.REMEMBER_DESKTOP_TOOLTIP)
        layout.addWidget(self.remember_desktop)
        layout.addWidget(button(S.BTN_CLEAR_HISTORY, self.clear_history))
        for combo in (self.microphone, self.profile, self.language, self.device, self.preference, self.paste_mode):
            combo.currentIndexChanged.connect(self.update_unsaved_indicator)
        self.threads.valueChanged.connect(self.update_unsaved_indicator)
        self.hotkey.textChanged.connect(self.update_unsaved_indicator)
        self.dictionary.textChanged.connect(self.update_unsaved_indicator)
        for check in (self.history, self.audio_history, self.vad, self.reduced_transparency,
                      self.popup_enabled, self.sound_feedback, self.remember_desktop):
            check.toggled.connect(self.update_unsaved_indicator)

    def build_diagnostics(self):
        layout = self.page(S.DIAGNOSTICS_TITLE, S.DIAGNOSTICS_SUBTITLE)
        self.diagnostic_summary = QLabel()
        self.diagnostic_summary.setWordWrap(True)
        layout.addWidget(self.diagnostic_summary)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setAccessibleName(S.DIAGNOSTICS_ACCESSIBLE)
        layout.addWidget(self.diagnostics)
        diagnostic_actions = QHBoxLayout()
        diagnostic_actions.addWidget(button(S.BTN_REFRESH_DIAGNOSTICS, self.refresh_diagnostics))
        diagnostic_actions.addWidget(button(S.BTN_COPY_REPORT, self.copy_diagnostic_report, True))
        diagnostic_actions.addStretch()
        layout.addLayout(diagnostic_actions)
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
        self.microphone.addItem(S.MIC_SYSTEM_DEFAULT, "")
        for device in QMediaDevices.audioInputs():
            self.microphone.addItem(device.description(), bytes(device.id()).hex())
        index = self.microphone.findData(selected)
        if index < 0:
            self.microphone.addItem(S.MIC_DISCONNECTED, selected)
            index = self.microphone.count() - 1
            self.microphone.model().item(index).setEnabled(False)
        self.microphone.setCurrentIndex(index)

    def form_values(self):
        """Raw settings-form values (unvalidated) keyed like Settings fields."""
        return dict(microphone=self.microphone.currentData(), profile=self.profile.currentData(),
            language=self.language.currentData(), device=self.device.currentData(), cpu_threads=self.threads.value(),
            paste_mode=self.paste_mode.currentData(), hotkey=self.hotkey.text().strip(),
            preference=self.preference.currentData(),
            vad=self.vad.isChecked(),
            dictionary=self.dictionary.toPlainText(), keep_history=self.history.isChecked(),
            keep_audio_history=self.audio_history.isChecked(), remember_desktop=self.remember_desktop.isChecked(),
            reduced_transparency=self.reduced_transparency.isChecked(),
            popup_enabled=self.popup_enabled.isChecked(), sound_feedback=self.sound_feedback.isChecked())

    def current_settings(self):
        return replace(self.settings, onboarding_done=True, **self.form_values()).validate()

    def settings_form_dirty(self):
        try:
            values = self.form_values()
        except AttributeError:  # Form still being built.
            return False
        return any(getattr(self.settings, key) != value for key, value in values.items())

    def update_unsaved_indicator(self, *_args):
        label = getattr(self, "unsaved_label", None)
        if label is not None:
            label.setVisible(self.settings_form_dirty())

    def save(self):
        try:
            previous_hotkey = self.settings.hotkey
            self.settings = self.current_settings()
            save_settings(self.settings)
            self.feedback.configure(sound_enabled=self.settings.sound_feedback,
                                    popup_enabled=self.settings.popup_enabled)
            if not self.settings.remember_desktop:
                from .portals import state_path
                state_path().unlink(missing_ok=True)
                if self.portal is not None:
                    # A pending permission grant may write a new one-use token.
                    # Process opt-out after that grant in the existing bridge.
                    self.portal_command("forget")
            self.set_status(S.SETTINGS_SAVED)
            LOG.info("settings saved")
            if self.settings.hotkey != previous_hotkey:
                self.enable_shortcut()
            self.refresh_shortcut_status()
        except Exception as exc:
            self.error(str(exc))
        self.update_unsaved_indicator()

    def set_status(self, text):
        self.status.setText(S.job_message(text))

    def job_status_changed(self, text):
        self.refresh_state()
        if self.recording:
            return  # The listening timer owns the status line while recording.
        self.set_status(text)

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
            self.shortcut_status.setText(S.SHORTCUT_TRIGGER_READY.format(trigger=trigger))
        else:
            self.shortcut_hint.setText(S.SHORTCUT_SET_UP)
            self.shortcut_status.setText(S.SHORTCUT_NOT_ENABLED)
        mode_trigger = state.get("mode_trigger", "") if state.get("mode_active") else self.portal_mode_shortcut
        self.mode_shortcut_hint.setText(mode_trigger)
        if mode_trigger:
            self.shortcut_status.setText(self.shortcut_status.text() + S.SHORTCUT_MODE_LINE.format(trigger=mode_trigger))
        self.update_setup_view()

    def cycle_profile(self):
        profiles = list(PROFILE_NAMES)
        current = self.settings.profile if self.settings.profile in profiles else self.profile.currentData()
        next_profile = profiles[(profiles.index(current) + 1) % len(profiles)]
        try:
            selected = replace(self.settings, profile=next_profile)
            save_settings(selected)
        except Exception as exc:
            self.error(S.MODE_SAVE_FAILED.format(error=exc))
            return
        self.settings = selected
        self.profile.setCurrentIndex(self.profile.findData(next_profile))
        message = S.STATUS_MODE.format(name=PROFILE_NAMES[next_profile])
        if self.recording or self.jobs.busy:
            message += S.STATUS_MODE_NEXT
        if next_profile == "th_to_eng" and local_model("translate-th-en") is None:
            message += S.STATUS_MODE_NEEDS_TRANSLATION
        self.set_status(message)
        self.feedback.mode(PROFILE_NAMES[next_profile])
        self.update_unsaved_indicator()

    def kde_shortcut_command(self, trigger=None):
        # D-Bus timeouts and registration must never freeze recording controls.
        if self.quitting:
            return
        if self.shortcut_process is not None:
            if trigger is not None:
                self.error(S.ERR_SHORTCUT_BUSY)
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
                state = {"active": False, "error": S.ERR_SHORTCUT_CHECK_FAILED}
            self.kde_shortcut_state = state
            self.show_shortcut_status()
            if trigger is not None:
                if state.get("active"):
                    self.set_status(S.SHORTCUT_READY.format(trigger=state["trigger"]))
                else:
                    self.error(state.get("error") or S.ERR_SHORTCUT_FAILED)
            process.deleteLater()
            if self.quitting:
                QTimer.singleShot(0, self.quit)
            elif self.desktop_starting:
                self.continue_desktop_setup()
            else:
                self.next_desktop_request()
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

    def error(self, message, jump=False):
        """Show an error. ``jump`` brings the dictation page forward (dictation/hotkey errors only)."""
        message = S.job_message(message)
        self.set_status(S.ERROR_PREFIX + message)
        if jump and self.isVisible():
            # A hidden window relies on the HUD; never reopen it for an error.
            self.nav.setCurrentRow(0)
        self.feedback.error(message)

    def job_failed(self, message):
        LOG.warning("job failed")
        warnings = self.cleanup_temporary_audio()
        self.error("; ".join([S.job_message(message), *warnings]), jump=True)
        self.refresh_state()

    def toggle_record(self):
        if not self.toggle_debounce.accept():
            LOG.info("toggle ignored (debounce)")
            return
        if self.recording:
            self.finish_recording()
            return
        try:
            # Recording always uses SAVED settings (profile included, via
            # cycle_profile). Unsaved or invalid form text cannot break it.
            self.record_settings = self.settings
            if not self.test_microphone and self.downloading_model == self.record_settings.model:
                raise RuntimeError(S.ERR_MODEL_DOWNLOADING)
            if not self.test_microphone and local_model(self.record_settings.model) is None:
                raise RuntimeError(S.ERR_NO_MODEL)
            if not self.test_microphone and self.queue_full():
                raise RuntimeError(S.ERR_QUEUE_FULL)
            queued = 0 if self.test_microphone else self.queued_jobs()
            self.audio_path = Path(self.temp.name) / (uuid.uuid4().hex + ".wav")
            self.recorder.start(self.audio_path, self.record_settings.microphone)
            self.recording = True
            LOG.info("record start (queued ahead: %d)", queued)
            self.record_started = time.monotonic()
            self.record_button.setText(S.BTN_STOP)
            self.record_button.setEnabled(True)
            self.record_timer.start(200)
            self.nav.setCurrentRow(0)
            self.feedback.set_profile(self.record_settings.profile)
            self.feedback.listening()
            status = S.STATUS_LISTENING_QUEUED if queued else S.STATUS_LISTENING
            if not self.test_microphone:
                self.prewarm(self.record_settings)
                if not self.jobs_warm():
                    preparing = getattr(self.feedback, "preparing", None)
                    if callable(preparing):
                        preparing()
                    if not queued:
                        status = S.STATUS_PREPARING
            self.set_status(status)
        except Exception as exc:
            self.recorder.stop()
            self.test_microphone = False
            self.recording = False
            LOG.warning("record start failed: %s", exc)
            self.error(str(exc), jump=True)

    def record_tick(self):
        seconds = int(time.monotonic() - self.record_started)
        if self.status.text() != S.STATUS_PREPARING or seconds >= 3:
            self.set_status(S.STATUS_LISTENING_TICK.format(minutes=seconds // 60, seconds=seconds % 60))
        self.feedback.tick(seconds)
        if seconds >= (5 if self.test_microphone else 900):
            self.finish_recording()

    def finish_recording(self):
        self.recording = False
        self.record_timer.stop()
        valid = self.recorder.stop()
        LOG.info("record stop (audio captured: %s)", bool(valid))
        self.record_button.setText(S.BTN_RECORD)
        self.update_setup_view()
        if self.test_microphone:
            self.test_microphone = False
            self.audio_path.unlink(missing_ok=True)
            self.audio_path = None
            self.set_status(S.STATUS_MIC_TEST_DONE if valid else S.STATUS_MIC_TEST_SILENT)
            self.feedback.cancel()
        elif valid:
            self.transcribe(self.audio_path, self.record_settings)
        else:
            self.error(S.ERR_NO_AUDIO, jump=True)

    def capture_error(self, message):
        self.cancel()
        self.error(message, jump=True)

    def test_mic(self):
        if self.recording or self.jobs.busy:
            self.error(S.ERR_BUSY_TEST_MIC)
            return
        self.test_microphone = True
        self.toggle_debounce.reset()
        self.toggle_record()

    def open_audio(self):
        if self.recording:
            self.error(S.ERR_BUSY_RECORDING)
            return
        path, _ = QFileDialog.getOpenFileName(self, S.OPEN_AUDIO_TITLE, "", S.OPEN_AUDIO_FILTER)
        if path:
            try:
                target = Path(self.temp.name) / (uuid.uuid4().hex + Path(path).suffix)
                shutil.copyfile(path, target)
                self.audio_path = target
                self.transcribe(target, self.settings)
            except Exception as exc:
                self.error(str(exc))

    def transcribe(self, path, settings):
        # Keep Retry attached to the audio the user just selected, including
        # when a model download temporarily prevents submitting that audio.
        self.last_request = (path, settings)
        try:
            if self.downloading_model == settings.model or (settings.profile == "th_to_eng" and self.downloading_model == "translate-th-en"):
                raise RuntimeError(S.ERR_WAIT_MODEL_DOWNLOAD)
            ahead = self.queued_jobs()
            self.jobs.submit(settings, action="transcribe", audio=str(path))
            LOG.info("job submit transcribe (ahead: %d)", ahead)
            queued = getattr(self.feedback, "queued", None)
            if ahead and callable(queued):
                queued(ahead)
                self.set_status(S.STATUS_QUEUED.format(count=ahead))
            else:
                self.feedback.processing()
        except Exception as exc:
            self.error(str(exc), jump=True)
        self.refresh_state()

    def retry(self):
        if self.recording:
            self.error(S.ERR_BUSY_RECORDING)
        elif self.last_request and self.last_request[0].exists():
            self.transcribe(self.last_request[0], self.settings)
        else:
            self.error(S.ERR_NOTHING_TO_RETRY)

    def translate(self):
        if self.recording:
            self.error(S.ERR_BUSY_RECORDING)
        elif self.downloading_model == "translate-th-en":
            self.error(S.ERR_WAIT_TRANSLATION_DOWNLOAD)
        elif self.editor.toPlainText().strip():
            try:
                self.jobs.submit(self.settings, action="translate", text=self.editor.toPlainText())
                LOG.info("job submit translate")
            except Exception as exc:
                self.error(str(exc))
            self.refresh_state()

    def completed(self, result):
        job_settings = Settings(**result["settings"])
        LOG.info("job result (no_speech: %s, characters: %d)", bool(result.get("no_speech")),
                 len(result.get("text", "") or ""))
        self.refresh_state()
        if result.get("no_speech"):
            warnings = self.cleanup_temporary_audio()
            self.set_status(S.ERR_NO_SPEECH + (" " + "; ".join(warnings) if warnings else ""))
            self.feedback.error(S.HUD_NO_SPEECH)
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
                warnings.append(S.WARN_SETUP_STATE.format(error=exc))
        self.metrics.setText(f"{result.get('model', '')} · {result.get('device', '')} · {result.get('elapsed', 0):.1f}s")
        if job_settings.keep_history:
            try:
                directory = data_dir() / "history"
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = directory / (result["id"] + ".txt")
                path.write_text(result.get("text", ""), encoding="utf-8")
                path.chmod(0o600)
            except OSError as exc:
                warnings.append(S.WARN_HISTORY.format(error=exc))
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
                warnings.append(S.WARN_AUDIO_HISTORY.format(error=exc))
        warnings.extend(self.cleanup_temporary_audio())
        self.set_status("; ".join(warnings) or S.STATUS_TRANSCRIPT_READY)
        if job_settings.paste_mode == "immediate" and result.get("text"):
            self.paste(automatic=True)
        elif self.recording:
            pass  # Never steal focus or HUD from a newer recording.
        else:
            self.feedback.success()
            self.showNormal()
            self.raise_()

    def protected_audio(self):
        """Audio that cleanup must keep: Retry's audio, the live recording, queued jobs."""
        keep = set()
        if self.last_request:
            keep.add(Path(self.last_request[0]))
        if self.recording and self.audio_path:
            keep.add(Path(self.audio_path))
        jobs = []
        try:
            jobs = list(self.jobs.pending)
        except (AttributeError, TypeError):
            pass
        active = getattr(self.jobs, "active", None)
        if isinstance(active, dict):
            jobs.append(active)
        for job in jobs:
            if isinstance(job, dict) and job.get("audio"):
                keep.add(Path(job["audio"]))
        return keep

    def cleanup_temporary_audio(self):
        retained = self.protected_audio()
        warnings = []
        for audio in Path(self.temp.name).iterdir():
            if audio.is_file() and audio not in retained:
                try:
                    audio.unlink(missing_ok=True)
                except OSError as exc:
                    warnings.append(S.WARN_TEMP_AUDIO.format(error=exc))
        return warnings

    def clipboard_restored(self):
        self.paste_busy = False
        self.paste_committed = False
        if not self.recording and not self.jobs.busy and self.status.text() == S.PASTE_SENT:
            self.set_status(S.PASTE_DONE)
        self.refresh_state()
        if self.paste_queue:
            QTimer.singleShot(0, self.drain_paste_queue)
        if self.quitting:
            QTimer.singleShot(0, self.quit)

    def drain_paste_queue(self):
        """Paste a transcript that finished while an earlier paste was still running."""
        if not self.paste_queue or self.quitting:
            return
        if self.paste_busy or self.paste_inflight or self.paste_committed or self.paste_timer.isActive():
            return
        text = self.paste_queue.popleft()
        self.paste(automatic=True, text=text)

    def escape_pressed(self):
        """Esc stops a pending paste countdown or the current recording, nothing else."""
        if self.paste_timer.isActive() and not self.paste_committed and not self.paste_inflight:
            self.abort_pending_paste(S.PASTE_CANCELLED)
            self.feedback.cancel()
        elif self.recording:
            self.record_timer.stop()
            self.recorder.stop()
            self.recording = False
            self.record_button.setText(S.BTN_RECORD)
            if self.audio_path:
                self.audio_path.unlink(missing_ok=True)
            self.test_microphone = False
            self.feedback.cancel()
            self.set_status(S.STATUS_CANCELLED)
            LOG.info("record cancelled (Esc)")
            self.update_setup_view()

    def cancel(self):
        self.feedback.cancel()
        self.paste_busy = self.paste_committed
        self.paste_request_id = None
        self.paste_timer.stop()
        self.paste_countdown.stop()
        self.paste_queue.clear()
        if not self.paste_committed:
            self.clipboard.restore()
        if self.recording:
            self.record_timer.stop()
            self.recorder.stop()
            self.recording = False
            self.record_button.setText(S.BTN_RECORD)
            if self.audio_path:
                self.audio_path.unlink(missing_ok=True)
        self.test_microphone = False
        self.toggle_debounce.reset()
        self.jobs.cancel()
        LOG.info("cancel")
        self.refresh_state()
        self.update_setup_view()

    def copy(self):
        if self.paste_committed:
            self.error(S.COPY_WAIT_PREVIOUS)
            return
        self.paste_busy = False
        self.paste_request_id = None
        self.paste_timer.stop()
        self.paste_countdown.stop()
        self.clipboard.restore()
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.set_status(S.COPIED)
        self.refresh_state()

    def copy_fallback(self, text, status=S.COPIED_FALLBACK):
        """Paste is impossible: leave the text on the clipboard and say so (not an error)."""
        try:
            QGuiApplication.clipboard().setText(text)
        except Exception as exc:  # Best effort; the editor still has the text.
            LOG.warning("clipboard fallback failed: %s", exc)
        LOG.info("paste outcome: copied fallback")
        if not self.recording:
            self.set_status(status)
            copied = getattr(self.feedback, "copied", None)
            if callable(copied):
                copied(hint=S.COPIED_FALLBACK)
            else:
                self.feedback.success()
        self.refresh_state()

    def paste(self, automatic=False, text=None):
        if text is None:
            text = self.editor.toPlainText()
        if self.paste_inflight:
            if automatic and text:
                self.paste_queue.append(text)
                return
            self.error(S.PASTE_WAIT_PREVIOUS)
            return
        if self.paste_timer.isActive() or self.paste_busy:
            if automatic and text:
                self.paste_queue.append(text)
            return
        if not text:
            return
        if self.portal_permission_pending:
            if automatic:
                self.copy_fallback(text)
            else:
                self.error(S.PASTE_PERMISSION_PENDING)
            return
        if not self.paste_enabled:
            self.copy_fallback(text, S.COPIED_FALLBACK_NO_PERMISSION)
            return
        offered = self.clipboard.offer(text)
        if offered is False or getattr(self.clipboard, "mode", None) == "failed":
            LOG.warning("clipboard offer failed; falling back to plain copy")
            self.clipboard.restore()
            self.copy_fallback(text)
            return
        self.paste_busy = True
        self.paste_request_id = uuid.uuid4().hex
        delay = AUTOMATIC_PASTE_DELAY_MS if automatic and not self.isActiveWindow() else MANUAL_PASTE_DELAY_MS
        if self.isVisible():
            self.showMinimized()
        self.paste_timer.start(delay)
        self.paste_deadline = time.monotonic() + delay / 1000
        if delay == AUTOMATIC_PASTE_DELAY_MS:
            self.set_status(S.PASTING)
        else:
            self.paste_countdown_tick()
            self.paste_countdown.start()
        self.refresh_state()

    def paste_countdown_tick(self):
        if not self.paste_timer.isActive():
            self.paste_countdown.stop()
            return
        seconds = max(1, math.ceil(self.paste_deadline - time.monotonic()))
        text = S.PASTE_COUNTDOWN.format(seconds=seconds)
        if self.status.text() != text:
            self.set_status(text)

    def send_paste(self):
        self.paste_timer.stop()
        self.paste_countdown.stop()
        self.portal_command("paste")
        self.refresh_state()

    def report_paste_failure(self, message):
        # A delayed paste failure must not hide a newer recording or ASR job.
        LOG.info("paste outcome: failed")
        if self.recording or self.jobs.busy:
            return
        self.set_status(message)
        self.feedback.error(message)

    def abort_pending_paste(self, message):
        if self.paste_committed or self.paste_inflight:
            return
        self.paste_timer.stop()
        self.paste_countdown.stop()
        self.paste_request_id = None
        self.paste_busy = False
        self.clipboard.restore()
        self.report_paste_failure(message)
        self.refresh_state()

    def portal_command(self, action, **options):
        if action == "paste":
            if self.paste_inflight or self.paste_committed or not self.paste_request_id:
                return
            reason = None
            if self.portal_permission_pending:
                reason = S.PASTE_ABORT_PERMISSION_PENDING
            elif not self.paste_enabled:
                reason = S.PASTE_ABORT_PERMISSION_ENDED
            elif not self.paste_busy:
                reason = S.PASTE_CANCELLED
            elif not self.clipboard.owns_clipboard():
                reason = S.PASTE_ABORT_CLIPBOARD_CHANGED
            if reason:
                self.abort_pending_paste(reason)
                return
        if action in {"shortcuts", "enable_paste", "restore"}:
            if self.portal_permission_pending:
                self.error(S.PERMISSION_PENDING)
                return
            if self.paste_busy and not self.paste_timer.isActive():
                self.error(S.PERMISSION_WAIT_PASTE)
                return
            if self.paste_timer.isActive():
                self.abort_pending_paste(S.PASTE_ABORT_PERMISSION_PENDING)
            else:
                self.clipboard.restore()
                self.paste_busy = False
                self.paste_request_id = None
            self.portal_permission_pending = True
            self.update_setup_view()
        if action == "paste":
            self.paste_inflight = self.paste_request_id
            self.paste_committed = True
            options["request_id"] = self.paste_request_id
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
                message = S.PASTE_ENABLED
                if response.get("persistent"):
                    message += S.PASTE_ENABLED_PERSISTENT
                else:
                    message += S.PASTE_ENABLED_SESSION
                self.set_status(message)
            elif event == "paste_sent":
                request_id = response.get("request_id")
                if not request_id or request_id != self.paste_inflight:
                    continue
                self.paste_inflight = None
                if not self.paste_busy or request_id != self.paste_request_id:
                    self.clipboard.restore_later()
                    continue
                self.clipboard.restore_later()
                LOG.info("paste outcome: sent")
                if not self.recording:
                    pasted = getattr(self.feedback, "pasted", None)
                    pasted() if callable(pasted) else self.feedback.typing()
                    self.set_status(S.PASTE_SENT)
            elif event == "shortcuts_enabled":
                trigger = response.get("trigger") or S.SHORTCUT_BY_DESKTOP
                self.portal_shortcut = trigger
                self.refresh_shortcut_status()
                self.set_status(S.SHORTCUT_PORTAL.format(trigger=trigger))
            elif event == "shortcuts_disabled":
                self.portal_shortcut = ""
                self.refresh_shortcut_status()
                self.set_status(S.SHORTCUT_NONE)
            elif event == "paste_disabled":
                self.paste_enabled = False
            elif event == "error":
                self.desktop_queue.clear()
                if self.desktop_setup_active and not self.quitting:
                    self.save_setup(desktop_setup_done=True)
                    self.desktop_setup_active = False
                if response.get("action") == "paste":
                    request_id = response.get("request_id")
                    if not request_id or request_id != self.paste_inflight:
                        continue
                    self.paste_inflight = None
                    if not self.paste_busy or request_id != self.paste_request_id:
                        self.clipboard.restore_later()
                        continue
                    self.clipboard.restore_later()
                    self.report_paste_failure(response["error"])
                else:
                    self.clipboard.restore()
                    self.error(response["error"], jump=response.get("action") == "shortcut")
            elif event == "warning":
                self.set_status(response["error"])
            elif event == "command_finished":
                self.portal_permission_pending = False
                self.next_desktop_request()
            self.update_setup_view()
            self.refresh_state()

    def portal_finished(self):
        paste_interrupted = bool(self.paste_request_id and (self.paste_inflight or self.paste_timer.isActive()))
        self.paste_timer.stop()
        self.paste_countdown.stop()
        self.paste_request_id = None
        self.desktop_queue.clear()
        if self.startup_action:
            self.startup_action = ""
            self.showNormal()
        self.paste_enabled = False
        self.paste_inflight = None
        self.portal_permission_pending = False
        self.portal = None
        self.portal_buffer = b""
        self.portal_shortcut = ""
        self.portal_mode_shortcut = ""
        self.refresh_shortcut_status()
        if self.paste_committed:
            self.clipboard.restore_later()
        else:
            self.clipboard.restore()
            self.paste_busy = False
        if paste_interrupted and not self.quitting:
            self.report_paste_failure(S.PASTE_ABORT_BRIDGE_CLOSED)
        self.refresh_state()

    def portal_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.portal_finished()
            self.error(S.DESKTOP_START_FAILED)

    def selected_model(self):
        index = self.model_list.currentRow()
        return list(CATALOG)[min(max(0, index), len(CATALOG) - 1)]

    def refresh_models(self):
        current = self.model_list.currentRow()
        self.model_list.clear()
        for key, spec in CATALOG.items():
            size = installed_size(key)
            size_text = f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"
            status = S.MODEL_READY.format(size=size_text) if size else S.MODEL_NOT_DOWNLOADED
            tags = " · " + " · ".join(spec.tags) if spec.tags else ""
            self.model_list.addItem(f"{spec.name}{tags}\n{status}" + (S.MODEL_SELECTED if key == self.settings.model else ""))
        self.model_list.setCurrentRow(min(max(0, current), len(CATALOG) - 1))
        self.refresh_models_page()

    def model_details(self, _index):
        spec = CATALOG[self.selected_model()]
        from .performance import measurements
        rates = measurements().get(spec.id, {})
        formats = {"typhoon": "NeMo · FastConformer", "qwen": "SafeTensors", "openvino": "OpenVINO IR · INT8", "fastflowlm": "Q4NX", "marian": "PyTorch + SentencePiece", "vulkan": "GGML · Q5"}
        storage = (S.MODEL_STORAGE_LOCAL.format(size=installed_size(spec.id) / 1e9)
                   if spec.origin == "local" else S.MODEL_STORAGE_DOWNLOAD.format(size=spec.download_gb))
        self.model_description.setText(S.MODEL_DESCRIPTION.format(storage=storage, memory=spec.memory_gb,
                                       languages=", ".join(spec.languages), license=spec.license))
        self.model_technical.setText(S.MODEL_TECHNICAL.format(repo=spec.repo, backend=spec.backend,
                                     devices=" / ".join(spec.devices), format=formats.get(spec.backend, spec.backend),
                                     status=spec.status, revision=spec.revision[:12],
                                     rates=rates or S.MODEL_NO_MEASUREMENTS))
        self.download_button.setEnabled(spec.origin != "local")
        self.model_beta_warning.setVisible(any(device in spec.devices for device in ("gpu", "npu")))

    def refresh_device_choices(self):
        spec = CATALOG[self.settings.model]
        thai_only = spec.backend == "typhoon"
        self.language.setItemText(self.language.findData("auto"),
                                  S.LANGUAGE_AUTO_THAI if thai_only else S.LANGUAGE_AUTO_MIXED)
        self.language.setItemText(self.language.findData("English"),
                                  S.LANGUAGE_ENGLISH_OTHER_MODEL if thai_only else S.LANGUAGE_ENGLISH)
        self.language_hint.setVisible(thai_only)
        labels = {"openvino": "Intel GPU (OpenVINO)", "vulkan": "Hardware GPU (Vulkan)"}
        self.device.setItemText(self.device.findData("gpu"), labels.get(spec.backend, "GPU (CUDA)") + " · Beta")
        from .fastflowlm_backend import available
        enabled = (spec.backend == "openvino" and "NPU" in openvino_devices()) or (spec.backend == "fastflowlm" and available())
        item = self.device.model().item(self.device.findData("npu"))
        item.setEnabled(enabled)
        item.setToolTip(S.NPU_ENABLED_TOOLTIP if enabled else S.NPU_DISABLED_TOOLTIP)
        if not enabled and self.device.currentData() == "npu":
            self.device.setCurrentIndex(self.device.findData("auto"))
        self.sync_device_choices_page()

    def download_model(self, _checked=False, *, model_id=None):
        if self.download_process:
            return
        model_id = model_id or self.selected_model()
        if CATALOG[model_id].origin == "local":
            self.download_status.setText(S.MODEL_EXTERNAL_REIMPORT)
            return
        if model_id in {self.settings.model, "translate-th-en"}:
            if self.recording or self.jobs.busy:
                self.download_status.setText(S.MODEL_BUSY_REPAIR)
                return
            self.jobs.stop_worker()
        self.importing = False
        if model_id == self.settings.model and self.settings.model_setup in {"pending", "paused", "downloading"}:
            if not self.save_setup(model_setup="downloading"):
                return
        self.downloading_model = model_id
        self.start_model_process(["-m", "phimthai.models", model_id])
        self.download_status.setText(S.MODEL_DOWNLOADING.format(name=CATALOG[model_id].name, size=CATALOG[model_id].download_gb))
        self.update_setup_view()

    def import_model(self):
        if self.download_process or self.recording or self.jobs.busy:
            self.download_status.setText(S.MODEL_IMPORT_BUSY)
            return
        folder = QFileDialog.getExistingDirectory(self, S.MODEL_IMPORT_DIALOG)
        if not folder:
            return
        self.importing = True
        self.imported_model = None
        self.downloading_model = None
        self.start_model_process(["-m", "phimthai.models", "--import", folder])
        self.download_status.setText(S.MODEL_IMPORTING)
        self.update_setup_view()

    def start_model_process(self, arguments):
        self.download_cancelled = False
        self.download_failure = ""
        self.imported_model = None
        self.model_process_pid = 0
        self.download_process = QProcess(self)
        self.download_buffer = b""
        self.download_process.readyReadStandardOutput.connect(self.download_output)
        self.download_process.readyReadStandardError.connect(lambda: self.download_process.readAllStandardError() if self.download_process else None)
        self.download_process.finished.connect(self.download_finished)
        self.download_process.errorOccurred.connect(self.download_error)
        self.download_process.started.connect(self.model_process_started)
        self.download_process.start(sys.executable, arguments)
        self.download_progress.setRange(0, 0)

    def model_process_started(self):
        if self.download_process:
            self.model_process_pid = self.download_process.processId()

    def download_output(self):
        self.download_buffer += bytes(self.download_process.readAllStandardOutput())
        while b"\n" in self.download_buffer:
            line, self.download_buffer = self.download_buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if "error" in event:
                self.download_failure = event["error"]
                self.download_status.setText(event["error"])
            else:
                self.download_progress.setRange(0, 100)
                self.download_progress.setValue(int(event.get("completed", 0) / max(1, event.get("total", 1)) * 100))
                self.download_status.setText(S.MODEL_VERIFIED if event.get("done") else
                    (S.MODEL_PROGRESS_IMPORT if event.get("importing") else S.MODEL_PROGRESS_DOWNLOAD) + event.get("file", "") +
                    S.MODEL_PROGRESS_SIZE.format(done=event.get("completed", 0) / 1e6, total=event.get("total", 0) / 1e6))
                if event.get("model_id"):
                    self.imported_model = event["model_id"]
            self.update_setup_view()

    def download_finished(self, code, _status):
        if self.download_process is None:
            return
        self.download_output()
        process = self.download_process
        model_id = self.downloading_model
        self.download_process = None
        self.downloading_model = None
        process.deleteLater()
        self.download_progress.setRange(0, 100)
        if code:
            self.download_status.setText(S.MODEL_STOPPED + self.download_failure)
        elif self.importing:
            refresh_catalog()
            self.jobs.stop_worker()
            self.download_status.setText(S.MODEL_IMPORTED)
        if self.importing:
            from .external_models import cleanup_interrupted_import
            try:
                cleanup_interrupted_import(self.model_process_pid)
            except OSError as exc:
                self.download_failure = S.MODEL_IMPORT_CLEANUP_FAILED.format(error=exc)
                self.download_status.setText(self.download_failure)
        if model_id == self.settings.model and self.settings.model_setup == "downloading" and (not self.quitting or not code):
            self.save_setup(model_setup="complete" if not code else "paused")
        self.importing = False
        self.refresh_models()
        if self.imported_model in CATALOG:
            self.model_list.setCurrentRow(list(CATALOG).index(self.imported_model))
        self.update_setup_view()

    def download_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.download_process.deleteLater()
            self.download_process = None
            self.downloading_model = None
            if self.settings.model_setup == "downloading":
                self.save_setup(model_setup="paused")
            self.download_progress.setRange(0, 100)
            self.download_status.setText(S.MODEL_DOWNLOAD_START_FAILED)
            self.download_failure = self.download_status.text()
            self.update_setup_view()

    def cancel_download(self):
        if self.download_process:
            self.download_cancelled = True
            if self.settings.model_setup == "downloading":
                self.save_setup(model_setup="paused")
            self.download_process.kill()

    def use_model(self):
        if self.recording or self.jobs.busy:
            self.download_status.setText(S.MODEL_BUSY_SWITCH)
            return
        model_id = self.selected_model()
        if model_id == self.downloading_model:
            self.download_status.setText(S.MODEL_WAIT_DOWNLOAD)
            return
        if CATALOG[model_id].kind != "asr":
            self.download_status.setText(S.MODEL_TRANSLATION_ONLY)
            return
        if local_model(model_id) is None:
            self.download_status.setText(S.MODEL_DOWNLOAD_FIRST)
            return
        selected = replace(self.settings, model=model_id)
        try:
            save_settings(selected)
        except OSError as exc:
            self.download_status.setText(S.MODEL_SELECT_SAVE_FAILED.format(error=exc))
            return
        self.settings = selected
        self.jobs.stop_worker()
        self.refresh_models()
        self.refresh_device_choices()
        self.update_setup_view()

    def remove_model(self):
        model_id = self.selected_model()
        if self.jobs.busy or self.recording or self.download_process:
            self.download_status.setText(S.MODEL_BUSY_REMOVE)
            return
        if not model_dir(model_id).exists():
            self.download_status.setText(S.MODEL_LEGACY)
            return
        if QMessageBox.question(self, S.MODEL_REMOVE_TITLE, S.MODEL_REMOVE_QUESTION) == QMessageBox.StandardButton.Yes:
            self.jobs.stop_worker()
            if model_id == self.settings.model and CATALOG[model_id].origin == "local":
                if not self.save_setup(model=DEFAULT_MODEL, device="auto", model_setup="skipped"):
                    return
            elif model_id == self.settings.model:
                if not self.save_setup(model_setup="skipped"):
                    return
            remove(model_id)
            self.refresh_models()
            self.refresh_device_choices()
            self.update_setup_view()

    def refresh_diagnostics(self):
        state = inventory()
        from .fastflowlm_backend import available, runtime_path
        from .vulkan_backend import runtime_path as vulkan_runtime
        state["amd_runtime"] = str(runtime_path() or S.DIAG_NOT_INSTALLED)
        state["amd_runtime_and_device_available"] = available()
        state["vulkan_runtime_installed"] = vulkan_runtime() is not None
        state["npu_note"] = S.DIAG_NPU_NOTE
        state["model"] = self.settings.model
        state["data_directory"] = str(data_dir())
        microphone_count = len(QMediaDevices.audioInputs())
        model_ready = local_model(self.settings.model) is not None
        summary = [S.DIAG_MICROPHONES.format(count=microphone_count),
                   S.DIAG_MODEL_READY if model_ready else S.DIAG_MODEL_MISSING,
                   S.DIAG_CPU]
        if not microphone_count:
            summary.append(S.DIAG_NO_MICROPHONE)
        if state["vulkan_runtime_installed"]:
            summary.append(S.DIAG_VULKAN)
        if available():
            summary.append(S.DIAG_AMD_NPU)
        elif state.get("flatpak"):
            summary.append(S.DIAG_FLATPAK_NPU)
        else:
            summary.append(S.DIAG_NPU_INSTALL)
        summary.append(S.DIAG_SHORTCUT_PASTE)
        self.diagnostic_summary.setText("\n\n".join(summary))
        self.diagnostics.setPlainText(json.dumps(state, ensure_ascii=False, indent=2))

    def clear_history(self):
        if QMessageBox.question(self, S.CLEAR_HISTORY_TITLE, S.CLEAR_HISTORY_QUESTION) == QMessageBox.StandardButton.Yes:
            try:
                for directory in (data_dir() / "history", data_dir() / "audio-history"):
                    for file in directory.glob("*"):
                        if file.is_file():
                            file.unlink()
                self.set_status(S.STATUS_HISTORY_CLEARED)
            except OSError as exc:
                self.error(S.HISTORY_CLEAR_FAILED.format(error=exc))

    def closeEvent(self, event):
        self.flush_pages()
        if self.tray and self.tray.isVisible() and not self.quitting:
            self.hide()
            event.ignore()
            return
        self.quitting = True
        self.cancel()
        if self.paste_committed:
            self.set_status(S.CLOSING_WAIT_PASTE)
            event.ignore()
            return
        if self.shortcut_process and self.shortcut_installing:
            # Let the desktop transaction finish or roll back before exiting.
            self.set_status(S.CLOSING_WAIT_SHORTCUT)
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
        self.feedback.shutdown()
        event.accept()

    def quit(self):
        self.quitting = True
        self.close()
        if not self.paste_committed and not (self.shortcut_process and self.shortcut_installing):
            QApplication.instance().quit()

    def setup_tray(self):
        quit_action = QAction(S.MENU_QUIT, self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        menu_bar = self.menuBar().addMenu(S.MENU_APP)
        clear_action = QAction(S.MENU_CLEAR, self)
        clear_action.setShortcut("Ctrl+L")
        clear_action.triggered.connect(self.clear_current)
        menu_bar.addAction(clear_action)
        menu_bar.addAction(quit_action)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.app_icon, self)
            self.tray.setToolTip(S.TRAY_IDLE)
            menu = QMenu(self)
            menu.addAction(S.MENU_OPEN, self.showNormal)
            menu.addAction(S.MENU_TOGGLE, self.toggle_record)
            menu.addAction(S.MENU_CANCEL, self.cancel)
            menu.addSeparator()
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
            self.update_tray_state()

    def clear_current(self):
        self.cancel()
        self.editor.clear()
        self.last_request = None
        self.audio_path = None
        for audio in Path(self.temp.name).iterdir():
            if audio.is_file():
                audio.unlink(missing_ok=True)
        self.set_status(S.STATUS_CLEARED)

    def diagnostic_extra(self):
        """Non-private state for the problem report (never transcript text)."""
        return {
            "state": self.state.value,
            "shortcut": self.shortcut_hint.text(),
            "mode_shortcut": self.mode_shortcut_hint.text(),
            "kde_shortcut_active": bool(self.kde_shortcut_state.get("active")),
            "portal_shortcut": self.portal_shortcut or "",
            "paste_enabled": self.paste_enabled,
            "paste_mode": self.settings.paste_mode,
            "model": self.settings.model,
            "model_installed": local_model(self.settings.model) is not None,
            "device": self.settings.device,
            "warm": self.jobs_warm(),
            "popup_error": getattr(self.feedback, "popup_error", ""),
        }

    def copy_diagnostic_report(self):
        extra = self.diagnostic_extra()
        try:
            from . import logs
            report = logs.diagnostic_report(extra=extra)
        except Exception as exc:  # logs module missing or failing: still give something useful.
            LOG.warning("diagnostic report fallback: %s", exc)
            report = "PhimThaiMaiPen diagnostic report\nversion: " + __version__ + "\n" + "\n".join(
                f"{key}: {value}" for key, value in extra.items())
            if hasattr(self, "diagnostics"):
                report += "\n\n" + self.diagnostics.toPlainText()
        QGuiApplication.clipboard().setText(report)
        self.set_status(S.STATUS_REPORT_COPIED)
        return report

    def status_report(self):
        """JSON for ``--status``; keep existing keys, scripts depend on them."""
        return {"running": True, "pid": os.getpid(),
                "version": __version__, "recording": self.recording,
                "busy": self.jobs.busy, "transcript_characters": len(self.editor.toPlainText()),
                "shortcut": self.shortcut_hint.text(), "mode_shortcut": self.mode_shortcut_hint.text(),
                "profile": self.settings.profile, "visible": self.isVisible(),
                "paste_mode": self.settings.paste_mode, "paste_enabled": self.paste_enabled,
                "permission_pending": self.portal_permission_pending,
                "popup": self.feedback.last_report, "popup_error": self.feedback.popup_error,
                "status": self.status.text(), "state": self.state.value}


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
        # A crashed Flatpak process can leave QLockFile containing a PID from
        # the sandbox namespace (often PID 2). With no live QLocalServer,
        # treat that lock as stale and retry once before reporting an error.
        if not app.instance_lock.removeStaleLockFile() or not app.instance_lock.tryLock(0):
            raise RuntimeError("PhimThaiMaiPen is already running but did not respond")
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        raise RuntimeError(server.errorString())
    return server


def setup_logging():
    try:
        from . import logs
    except ImportError:
        return
    setup = getattr(logs, "setup_logging", None)
    if callable(setup):
        try:
            setup()
        except Exception as exc:  # Logging must never prevent the app from starting.
            print(f"PhimThaiMaiPen: logging unavailable: {exc}", file=sys.stderr)


def main():
    if "--status" not in sys.argv:
        setup_logging()
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
                socket.write((json.dumps(window.status_report()) + "\n").encode())
                socket.flush()
            socket.disconnectFromServer()
            socket.deleteLater()
        socket.readyRead.connect(read_command)
        if socket.bytesAvailable():
            read_command()
    server.newConnection.connect(receive)
    if not any(flag in sys.argv for flag in ("--toggle", "--cycle-mode")):
        window.show()
    if "--smoke" in sys.argv:
        QTimer.singleShot(1000, window.quit)
    elif QGuiApplication.platformName() not in {"offscreen", "minimal"}:
        window.startup_action = "toggle" if "--toggle" in sys.argv else "cycle-mode" if "--cycle-mode" in sys.argv else ""
        QTimer.singleShot(0, window.start_first_run)
    return app.exec()
