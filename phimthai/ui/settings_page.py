"""Autosaving, grouped settings page. Emits new Settings objects; never saves itself."""
import dataclasses

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QStandardItemModel
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGraphicsOpacityEffect,
                               QHBoxLayout, QKeySequenceEdit, QPlainTextEdit, QProgressBar,
                               QRadioButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ._common import PAGE_MIN_WIDTH, SPACE_L, SPACE_M, SPACE_S, button, label, repolish, section

DEBOUNCE_MS = 400
BETA_TEXT = ("GPU / NPU ยังเป็น Beta · ผลลัพธ์อาจไม่แน่นอนหรือช้ากว่า CPU\n"
             "แนะนำให้ใช้ CPU สำหรับการถอดเสียงทั่วไป")
LANGUAGES = [("อัตโนมัติ · ไทย + English", "auto"), ("ภาษาไทย", "Thai"), ("English", "English")]
LANGUAGES_THAI_ONLY = [("อัตโนมัติ · โมเดลนี้ฟังเฉพาะภาษาไทย", "auto"), ("ภาษาไทย", "Thai"),
                       ("English · ต้องเปลี่ยนเป็น Qwen", "English")]
MODIFIERS = ("Meta", "Ctrl", "Alt", "Shift")


def hotkey_to_text(sequence):
    """QKeySequence → "Meta+H"-style portable text (first chord only)."""
    if sequence.isEmpty():
        return ""
    text = QKeySequence(sequence[0]).toString(QKeySequence.SequenceFormat.PortableText)
    return text.replace("Win+", "Meta+").replace("Super+", "Meta+")


def hotkey_error(text):
    if not text:
        return "กดปุ่มลัดที่ต้องการ เช่น Meta+H"
    parts = text.split("+")
    if len(parts) < 2 or not any(part in ("Meta", "Ctrl", "Alt") for part in parts[:-1]):
        return "ปุ่มลัดต้องมี Meta, Ctrl หรือ Alt ร่วมกับปุ่มอื่น เช่น Meta+H"
    if parts[-1] in MODIFIERS or not parts[-1]:
        return "เพิ่มปุ่มตัวอักษรหรือตัวเลขต่อท้าย เช่น Meta+H"
    return ""


def _combo(values, selected, accessible):
    combo = QComboBox()
    for text, value in values:
        combo.addItem(text, value)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    combo.setAccessibleName(accessible)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(16)
    return combo


def _error_label():
    widget = label("", "fieldError")
    widget.hide()
    return widget


class DictionaryEdit(QPlainTextEdit):
    """Tab inserts the separator; Ctrl+Tab / Ctrl+Shift+Tab leave the field (no keyboard trap)."""

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.focusNextPrevChild(not (event.key() == Qt.Key.Key_Backtab or
                                         event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        super().keyPressEvent(event)


class SettingsPage(QWidget):
    changed = Signal(object)
    refresh_microphones = Signal()
    test_microphone = Signal()
    enable_shortcut = Signal(str)
    enable_paste = Signal(bool)
    clear_history = Signal()
    reduced_transparency_toggled = Signal(bool)

    def __init__(self, settings, cpu_count, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.setMinimumWidth(PAGE_MIN_WIDTH)
        self._settings = settings
        self._cpu_count = max(1, int(cpu_count or 1))
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._commit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_M)

        header = QHBoxLayout()
        header.addWidget(label("การเปลี่ยนแปลงบันทึกอัตโนมัติ และมีผลกับการพูดครั้งถัดไป", "muted"), 1)
        self.saved_indicator = label("", "savedIndicator", wrap=False)
        self._saved_effect = QGraphicsOpacityEffect(self.saved_indicator)
        self._saved_effect.setOpacity(1.0)
        self.saved_indicator.setGraphicsEffect(self._saved_effect)
        self._saved_fade = QPropertyAnimation(self._saved_effect, b"opacity", self)
        self._saved_fade.setDuration(300)
        self._saved_fade.setStartValue(1.0)
        self._saved_fade.setEndValue(0.0)
        self._saved_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._saved_fade.finished.connect(self.saved_indicator.hide)
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.setInterval(2000)
        self._saved_timer.timeout.connect(self._saved_fade.start)
        self.saved_indicator.hide()
        header.addWidget(self.saved_indicator, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.general_error = _error_label()
        root.addWidget(self.general_error)

        root.addWidget(self._build_microphone())
        root.addWidget(self._build_speech())
        root.addWidget(self._build_paste())
        root.addWidget(self._build_shortcut())
        root.addWidget(self._build_appearance())
        root.addWidget(self._build_privacy())
        root.addWidget(self._build_advanced())
        root.addStretch(1)

        self.field_errors = {"hotkey": self.hotkey_error, "device": self.device_error,
                             "cpu_threads": self.threads_error, "dictionary": self.dictionary_error,
                             "microphone": self.microphone_error}
        self._connect_edits()
        self.set_settings(settings)

    # -- sections --------------------------------------------------------
    def _build_microphone(self):
        frame, layout = section("ไมโครโฟน")
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        self.microphone = QComboBox()
        self.microphone.setAccessibleName("เลือกไมโครโฟน")
        self.microphone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setMinimumContentsLength(16)
        self.microphone.addItem("ไมค์เริ่มต้นของระบบ", "")
        row.addWidget(self.microphone, 1)
        self.refresh_mic_button = button("ตรวจหาไมค์", self.refresh_microphones.emit,
                                         accessible="ตรวจหาไมโครโฟนใหม่")
        row.addWidget(self.refresh_mic_button)
        layout.addLayout(row)
        self.microphone_error = _error_label()
        layout.addWidget(self.microphone_error)
        test_row = QHBoxLayout()
        test_row.setSpacing(SPACE_S)
        self.test_mic_button = button("ทดสอบไมค์ 5 วินาที", self.test_microphone.emit,
                                      accessible="ทดสอบไมโครโฟน 5 วินาที")
        test_row.addWidget(self.test_mic_button)
        self.mic_level = QProgressBar()
        self.mic_level.setObjectName("micLevel")
        self.mic_level.setRange(0, 100)
        self.mic_level.setValue(0)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedHeight(8)
        self.mic_level.setAccessibleName("ระดับเสียงไมโครโฟน")
        test_row.addWidget(self.mic_level, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(test_row)
        layout.addWidget(label("กดทดสอบแล้วพูดสั้น ๆ แถบควรขยับเมื่อมีเสียง", "muted"))
        return frame

    def _build_speech(self):
        frame, layout = section("การพูดและข้อความ")
        form = QFormLayout()
        form.setSpacing(SPACE_S)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile = _combo([("Smart Mix · ปรับข้อความให้อ่านง่าย", "smart"), ("Raw · ถอดตามที่พูด", "raw"),
                               ("TH → ENG · พูดไทย แปลอังกฤษ", "th_to_eng")], "smart", "รูปแบบข้อความ")
        form.addRow("รูปแบบข้อความ", self.profile)
        self.language = _combo(LANGUAGES, "auto", "ภาษาที่พูด")
        form.addRow("ภาษาที่พูด", self.language)
        layout.addLayout(form)
        self.language_hint = label("Typhoon ฟังเฉพาะภาษาไทย · ถ้าพูดอังกฤษหรือผสมสองภาษา ให้เลือก Qwen ในหน้าโมเดล", "muted")
        self.language_hint.hide()
        layout.addWidget(self.language_hint)
        self.vad = QCheckBox("ตรวจช่วงพูดและตัดความเงียบต้น–ท้าย")
        self.vad.setAccessibleName("ตัดความเงียบอัตโนมัติ")
        layout.addWidget(self.vad)
        layout.addWidget(label("พจนานุกรมส่วนตัว", "fieldLabel"))
        self.dictionary = DictionaryEdit()
        self.dictionary.setObjectName("dictionary")
        self.dictionary.setAccessibleName("พจนานุกรมคำแทนที่")
        self.dictionary.setPlaceholderText("คำเดิม<Tab>คำที่ให้แทน\nเช่น  พิมไท\tPhimThai")
        self.dictionary.setTabChangesFocus(False)
        self.dictionary.setFixedHeight(96)
        layout.addWidget(self.dictionary)
        layout.addWidget(label("บรรทัดละหนึ่งคู่ · คำเดิม<Tab>คำที่ให้แทน · กด Ctrl+Tab เพื่อออกจากช่องนี้", "muted"))
        self.dictionary_error = _error_label()
        layout.addWidget(self.dictionary_error)
        return frame

    def _build_paste(self):
        frame, layout = section("เมื่อพูดจบ")
        self.paste_group = QButtonGroup(self)
        self.paste_immediate = QRadioButton("วางทันที")
        self.paste_immediate.setAccessibleName("วางข้อความทันทีเมื่อพูดจบ")
        self.paste_review = QRadioButton("ตรวจก่อนวาง")
        self.paste_review.setAccessibleName("ตรวจและแก้ข้อความก่อนวาง")
        for radio, value, hint in ((self.paste_immediate, "immediate", "ข้อความถูกวางลงในแอปที่ใช้อยู่ทันทีเมื่อถอดเสียงเสร็จ"),
                                   (self.paste_review, "review", "เปิดข้อความให้ตรวจและแก้ก่อน แล้วค่อยกดวางเอง")):
            radio.setProperty("value", value)
            self.paste_group.addButton(radio)
            layout.addWidget(radio)
            hint_label = label(hint, "muted")
            hint_label.setContentsMargins(SPACE_L + 2, 0, 0, 0)
            layout.addWidget(hint_label)
        return frame

    def _build_shortcut(self):
        frame, layout = section("ปุ่มลัด")
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        row.addWidget(label("เริ่ม / หยุดพูด", "fieldLabel", wrap=False))
        self.hotkey = QKeySequenceEdit()
        self.hotkey.setObjectName("hotkeyEdit")
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.setClearButtonEnabled(True)
        self.hotkey.setAccessibleName("ปุ่มลัดเริ่มหรือหยุดพูด")
        self.hotkey.setToolTip("คลิกแล้วกดปุ่มลัดที่ต้องการ เช่น Meta+H")
        row.addWidget(self.hotkey, 1)
        self.hotkey_reset = button("ค่าเริ่มต้น", lambda: self._set_hotkey_text("Meta+H", edit=True),
                                   accessible="คืนปุ่มลัดเป็น Meta+H")
        row.addWidget(self.hotkey_reset)
        layout.addLayout(row)
        self.hotkey_error = _error_label()
        layout.addWidget(self.hotkey_error)
        self.shortcut_status = label("กำลังตรวจปุ่มลัด…", "shortcutStatus")
        self.shortcut_status.setProperty("ok", False)
        layout.addWidget(self.shortcut_status)
        actions = QHBoxLayout()
        actions.setSpacing(SPACE_S)
        self.enable_shortcut_button = button("เปิดใช้ปุ่มลัด", lambda: self.enable_shortcut.emit(self.hotkey_text()),
                                             True, accessible="เปิดใช้ปุ่มลัดกับเดสก์ท็อป")
        self.enable_paste_button = button("อนุญาตวางข้อความ", lambda: self.enable_paste.emit(self.remember_desktop.isChecked()),
                                          accessible="อนุญาตให้วางข้อความในแอปอื่น")
        actions.addWidget(self.enable_shortcut_button)
        actions.addWidget(self.enable_paste_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(label("เดสก์ท็อปจะถามสิทธิ์หนึ่งครั้ง · กดอนุญาตในหน้าต่างที่ระบบแสดง", "muted"))
        return frame

    def _build_appearance(self):
        frame, layout = section("หน้าตา")
        self.reduced_transparency = QCheckBox("ลดความโปร่งใส เพิ่มความชัดของพื้นหลัง")
        self.popup_enabled = QCheckBox("แสดง Popup เล็กขณะพูด")
        self.sound_feedback = QCheckBox("เสียงแจ้งเมื่อเริ่ม หยุด และวางข้อความ")
        for box in (self.reduced_transparency, self.popup_enabled, self.sound_feedback):
            box.setAccessibleName(box.text())
            layout.addWidget(box)
        return frame

    def _build_privacy(self):
        frame, layout = section("ความเป็นส่วนตัว")
        self.keep_history = QCheckBox("เก็บประวัติข้อความในเครื่อง")
        self.keep_audio_history = QCheckBox("เก็บไฟล์เสียงที่พูดไว้ในเครื่อง")
        self.remember_desktop = QCheckBox("จำสิทธิ์วางข้อความและปุ่มลัดที่อนุญาตแล้ว")
        for box in (self.keep_history, self.keep_audio_history, self.remember_desktop):
            box.setAccessibleName(box.text())
            layout.addWidget(box)
        layout.addWidget(label("ข้อมูลทั้งหมดอยู่ในเครื่องนี้เท่านั้น ไม่มีการส่งขึ้นอินเทอร์เน็ต", "muted"))
        row = QHBoxLayout()
        self.clear_history_button = button("ลบประวัติ…", self.clear_history.emit,
                                           accessible="ลบประวัติข้อความและเสียง")
        row.addWidget(self.clear_history_button)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _build_advanced(self):
        frame, layout = section("ขั้นสูง")
        heading = frame.findChild(QWidget, "sectionTitle")
        heading.hide()
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("sectionToggle")
        self.advanced_toggle.setText("ขั้นสูง")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setAccessibleName("แสดงการตั้งค่าขั้นสูง")
        self.advanced_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        font = self.advanced_toggle.font()
        font.setBold(True)
        self.advanced_toggle.setFont(font)
        layout.insertWidget(0, self.advanced_toggle)
        self.advanced_body = QWidget()
        self.advanced_body.setObjectName("advancedBody")
        body = QVBoxLayout(self.advanced_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE_S)
        form = QFormLayout()
        form.setSpacing(SPACE_S)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.device = _combo([("อัตโนมัติ · CPU แนะนำ", "auto"), ("CPU · แนะนำ", "cpu"),
                              ("GPU · Beta", "gpu"), ("NPU · Beta", "npu")], "auto", "อุปกรณ์ประมวลผล")
        form.addRow("ประมวลผลด้วย", self.device)
        self.threads = QSpinBox()
        self.threads.setRange(1, self._cpu_count)
        self.threads.setAccessibleName("จำนวนเธรด CPU")
        self.threads.setSuffix(f" จาก {self._cpu_count}")
        form.addRow("CPU threads", self.threads)
        body.addLayout(form)
        self.beta_warning = label(BETA_TEXT, "betaWarning")
        self.beta_warning.hide()
        body.addWidget(self.beta_warning)
        self.device_error = _error_label()
        self.threads_error = _error_label()
        body.addWidget(self.device_error)
        body.addWidget(self.threads_error)
        layout.addWidget(self.advanced_body)
        self.advanced_body.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        return frame

    def _toggle_advanced(self, checked):
        self.advanced_body.setVisible(checked)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    # -- wiring ----------------------------------------------------------
    def _connect_edits(self):
        for combo in (self.microphone, self.profile, self.language, self.device):
            combo.currentIndexChanged.connect(self._edited)
        for box in (self.vad, self.reduced_transparency, self.popup_enabled, self.sound_feedback,
                    self.keep_history, self.keep_audio_history, self.remember_desktop):
            box.toggled.connect(self._edited)
        self.paste_group.buttonToggled.connect(lambda *_: self._edited())
        self.dictionary.textChanged.connect(self._edited)
        self.threads.valueChanged.connect(self._edited)
        self.hotkey.keySequenceChanged.connect(self._edited)
        self.device.currentIndexChanged.connect(self._update_beta)
        self.reduced_transparency.toggled.connect(self._reduced_toggled)

    def _reduced_toggled(self, checked):
        if not self._loading:
            self.reduced_transparency_toggled.emit(checked)

    def _update_beta(self):
        self.beta_warning.setVisible(self.device.currentData() in ("gpu", "npu"))

    def _edited(self, *_):
        if not self._loading:
            self._timer.start()

    def hotkey_text(self):
        return hotkey_to_text(self.hotkey.keySequence())

    def _set_hotkey_text(self, text, edit=False):
        self.hotkey.setKeySequence(QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText))
        if edit:
            self._edited()

    def values(self):
        paste = self.paste_group.checkedButton()
        return {
            "microphone": self.microphone.currentData() or "",
            "profile": self.profile.currentData(),
            "language": self.language.currentData(),
            "vad": self.vad.isChecked(),
            "dictionary": self.dictionary.toPlainText(),
            "paste_mode": paste.property("value") if paste else self._settings.paste_mode,
            "hotkey": self.hotkey_text(),
            "reduced_transparency": self.reduced_transparency.isChecked(),
            "popup_enabled": self.popup_enabled.isChecked(),
            "sound_feedback": self.sound_feedback.isChecked(),
            "keep_history": self.keep_history.isChecked(),
            "keep_audio_history": self.keep_audio_history.isChecked(),
            "remember_desktop": self.remember_desktop.isChecked(),
            "device": self.device.currentData(),
            "cpu_threads": self.threads.value(),
        }

    def _show_error(self, field, text):
        target = self.field_errors.get(field, self.general_error)
        target.setText("⚠ " + text)
        target.setAccessibleName("ข้อผิดพลาด: " + text)
        target.show()

    def _clear_errors(self):
        for widget in list(self.field_errors.values()) + [self.general_error]:
            widget.clear()
            widget.hide()

    def _commit(self):
        """Validate the current form; emit a new Settings when valid. Returns it or None."""
        self._timer.stop()
        self._clear_errors()
        values = self.values()
        problem = hotkey_error(values["hotkey"])
        if problem:
            self._show_error("hotkey", problem)
            return None
        bad_lines = [n + 1 for n, line in enumerate(values["dictionary"].splitlines())
                     if line.strip() and "\t" not in line]
        if bad_lines:
            # Lines without a Tab are ignored by the replacer; warn without blocking.
            self.dictionary_error.setText("⚠ บรรทัด " + ", ".join(map(str, bad_lines[:5])) +
                                          " ยังไม่มี Tab คั่น จะไม่ถูกใช้แทนคำ")
            self.dictionary_error.show()
        candidate = dataclasses.replace(self._settings, **values)
        try:
            candidate.validate()
        except ValueError as error:
            message = str(error)
            field = next((key for key in self.field_errors if key in message or
                          key.replace("_", " ") in message.lower()), None)
            self._show_error(field, "ค่านี้ใช้ไม่ได้: " + message)
            return None
        self._settings = candidate
        self.changed.emit(candidate)
        return candidate

    def flush(self):
        """Commit pending edits immediately (e.g. before the window closes)."""
        if self._timer.isActive():
            return self._commit()
        return None

    # -- setters ---------------------------------------------------------
    def settings(self):
        return self._settings

    def set_settings(self, settings):
        self._timer.stop()
        self._loading = True
        try:
            self._settings = settings
            self._select(self.microphone, settings.microphone, add_missing=True)
            self._select(self.profile, settings.profile)
            self._select(self.language, settings.language)
            self._select(self.device, settings.device)
            self.vad.setChecked(settings.vad)
            if self.dictionary.toPlainText() != settings.dictionary:
                self.dictionary.setPlainText(settings.dictionary)
            (self.paste_review if settings.paste_mode == "review" else self.paste_immediate).setChecked(True)
            self._set_hotkey_text(settings.hotkey)
            self.reduced_transparency.setChecked(settings.reduced_transparency)
            self.popup_enabled.setChecked(settings.popup_enabled)
            self.sound_feedback.setChecked(settings.sound_feedback)
            self.keep_history.setChecked(settings.keep_history)
            self.keep_audio_history.setChecked(settings.keep_audio_history)
            self.remember_desktop.setChecked(settings.remember_desktop)
            self.threads.setValue(max(1, min(self._cpu_count, settings.cpu_threads)))
            self._update_beta()
            self._clear_errors()
        finally:
            self._loading = False

    @staticmethod
    def _select(combo, value, add_missing=False):
        index = combo.findData(value)
        if index < 0 and add_missing and value:
            combo.addItem(f"{value} (ไม่พบตอนนี้)", value)
            index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))

    def set_microphones(self, microphones, selected_id):
        self._loading = True
        try:
            self.microphone.clear()
            self.microphone.addItem("ไมค์เริ่มต้นของระบบ", "")
            for text, device_id in microphones:
                if device_id:
                    self.microphone.addItem(text, device_id)
            self._select(self.microphone, selected_id, add_missing=True)
        finally:
            self._loading = False

    def set_level(self, level):
        self.mic_level.setValue(max(0, min(100, int(level))))

    def set_shortcut_status(self, text, ok):
        self.shortcut_status.setText(("✓ " if ok else "") + text)
        self.shortcut_status.setProperty("ok", bool(ok))
        repolish(self.shortcut_status)

    def set_language_thai_only(self, thai_only):
        values = LANGUAGES_THAI_ONLY if thai_only else LANGUAGES
        for index, (text, _value) in enumerate(values):
            self.language.setItemText(index, text)
        self.language_hint.setVisible(bool(thai_only))

    def set_npu_available(self, available):
        index = self.device.findData("npu")
        model = self.device.model()
        if index >= 0 and isinstance(model, QStandardItemModel):
            model.item(index).setEnabled(bool(available))
            self.device.setItemText(index, "NPU · Beta" if available else "NPU · ไม่พบในเครื่องนี้")

    def set_saved_indicator(self, text="บันทึกแล้ว ✓"):
        self._saved_fade.stop()
        self._saved_effect.setOpacity(1.0)
        self.saved_indicator.setText(text)
        self.saved_indicator.setVisible(bool(text))
        if text:
            self._saved_timer.start()
