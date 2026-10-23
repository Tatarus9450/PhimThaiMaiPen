"""Embedded first-run setup: model → microphone → permissions → try it."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QPlainTextEdit, QProgressBar,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ._common import PAGE_MIN_WIDTH, SPACE_L, SPACE_M, SPACE_S, button, format_gb, label, repolish

STEPS = ("โมเดล", "ไมโครโฟน", "สิทธิ์", "ทดลองใช้")
LEVEL_THRESHOLD = 10


class SetupWizard(QWidget):
    download = Signal()
    cancel_download = Signal()
    choose_model = Signal()
    refresh_microphones = Signal()
    test_microphone = Signal()
    microphone_selected = Signal(str)
    enable_shortcut = Signal()
    enable_paste = Signal()
    skip = Signal()
    finished = Signal()
    step_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("setupWizard")
        self.setMinimumWidth(PAGE_MIN_WIDTH)
        self.done = [False] * len(STEPS)
        self._downloading = False
        self._ready = False
        self._hotkey = "Meta+H"
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_L, SPACE_L, SPACE_L, SPACE_L)
        root.setSpacing(SPACE_M)

        title = label("เริ่มต้นใช้งาน PhimThai", "wizardTitle")
        font = title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.4)
        title.setFont(font)
        root.addWidget(title)
        root.addWidget(label("4 ขั้นตอนสั้น ๆ แล้วพูดพิมพ์ได้ทุกแอป · ข้ามได้ตลอด และกลับมาตั้งค่าทีหลังได้", "muted"))

        self.indicator = QWidget()
        self.indicator.setObjectName("stepIndicator")
        indicator_layout = QHBoxLayout(self.indicator)
        indicator_layout.setContentsMargins(0, 0, 0, 0)
        indicator_layout.setSpacing(SPACE_S)
        self.step_labels = []
        for number, name in enumerate(STEPS, 1):
            step = label(f"{number}  {name}", "stepItem", wrap=False, rich=True)
            step.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.step_labels.append(step)
            indicator_layout.addWidget(step)
        root.addWidget(self.indicator)

        self.stack = QStackedWidget()
        self.stack.setObjectName("wizardSteps")
        self.stack.addWidget(self._model_step())
        self.stack.addWidget(self._microphone_step())
        self.stack.addWidget(self._permission_step())
        self.stack.addWidget(self._try_step())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setSpacing(SPACE_S)
        self.skip_button = button("ข้าม", self.skip.emit, accessible="ข้ามการตั้งค่าเริ่มต้น", name="wizardSkip")
        nav.addWidget(self.skip_button)
        nav.addStretch(1)
        self.back_button = button("ย้อนกลับ", self.back, accessible="ย้อนกลับขั้นก่อนหน้า")
        self.next_button = button("ถัดไป", self.next, accessible="ไปขั้นถัดไป", name="wizardNext")
        nav.addWidget(self.back_button)
        nav.addWidget(self.next_button)
        root.addLayout(nav)
        self._update()

    # -- steps -------------------------------------------------------------
    @staticmethod
    def _page(heading):
        page = QFrame()
        page.setObjectName("wizardStep")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_M, SPACE_M, SPACE_M, SPACE_M)
        layout.setSpacing(SPACE_S)
        title = label(heading, "sectionTitle")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        return page, layout

    def _model_step(self):
        page, layout = self._page("1 · ดาวน์โหลดโมเดลถอดเสียง")
        self.model_name = label("Typhoon ASR Realtime", "modelName")
        font = self.model_name.font()
        font.setBold(True)
        self.model_name.setFont(font)
        layout.addWidget(self.model_name)
        self.model_info = label("ดาวน์โหลดครั้งเดียว แล้วใช้แบบออฟไลน์ได้ · เสียงไม่ถูกส่งออกจากเครื่อง", "muted")
        layout.addWidget(self.model_info)
        self.model_progress = QProgressBar()
        self.model_progress.setRange(0, 100)
        self.model_progress.setValue(0)
        self.model_progress.setAccessibleName("ความคืบหน้าการดาวน์โหลดโมเดล")
        self.model_progress.hide()
        layout.addWidget(self.model_progress)
        self.model_status = label("", "stepStatus")
        layout.addWidget(self.model_status)
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        self.download_button = button("ดาวน์โหลด", self.download.emit, True, accessible="ดาวน์โหลดโมเดล")
        self.stop_button = button("หยุด", self.cancel_download.emit, accessible="หยุดดาวน์โหลดโมเดล")
        self.choose_button = button("เลือกโมเดลอื่น", self.choose_model.emit, accessible="เลือกโมเดลอื่น")
        for widget in (self.download_button, self.stop_button, self.choose_button):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _microphone_step(self):
        page, layout = self._page("2 · เลือกและทดสอบไมโครโฟน")
        layout.addWidget(label("กดทดสอบแล้วพูดอะไรก็ได้ 2–3 คำ ถ้าแถบด้านล่างขยับแปลว่าไมค์ใช้ได้", "muted"))
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        self.microphone = QComboBox()
        self.microphone.setAccessibleName("เลือกไมโครโฟน")
        self.microphone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setMinimumContentsLength(16)
        self.microphone.addItem("ไมค์เริ่มต้นของระบบ", "")
        self.microphone.activated.connect(lambda _i: self.microphone_selected.emit(self.microphone.currentData() or ""))
        row.addWidget(self.microphone, 1)
        row.addWidget(button("ตรวจหาไมค์", self.refresh_microphones.emit, accessible="ตรวจหาไมโครโฟนใหม่"))
        layout.addLayout(row)
        test_row = QHBoxLayout()
        test_row.setSpacing(SPACE_S)
        self.test_button = button("ทดสอบ", self.test_microphone.emit, True, accessible="ทดสอบไมโครโฟน")
        test_row.addWidget(self.test_button)
        self.level = QProgressBar()
        self.level.setObjectName("micLevel")
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(8)
        self.level.setAccessibleName("ระดับเสียงไมโครโฟน")
        test_row.addWidget(self.level, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(test_row)
        self.mic_status = label("ยังไม่ได้ยินเสียง", "stepStatus")
        layout.addWidget(self.mic_status)
        layout.addStretch(1)
        return page

    def _permission_step(self):
        page, layout = self._page("3 · อนุญาตปุ่มลัดและการวางข้อความ")
        layout.addWidget(label("เดสก์ท็อปจะแสดงหน้าต่างขอสิทธิ์ · กดอนุญาตเพื่อให้กดปุ่มลัดแล้ววางข้อความในแอปอื่นได้", "muted"))
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        self.shortcut_status = label("ปุ่มลัด: ยังไม่ได้เปิดใช้", "stepStatus")
        row.addWidget(self.shortcut_status, 1)
        self.shortcut_button = button("เปิดใช้ปุ่มลัด", self.enable_shortcut.emit, True, accessible="เปิดใช้ปุ่มลัด")
        row.addWidget(self.shortcut_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(SPACE_S)
        self.paste_status = label("วางข้อความ: ยังไม่ได้อนุญาต", "stepStatus")
        row.addWidget(self.paste_status, 1)
        self.paste_button = button("อนุญาตวางข้อความ", self.enable_paste.emit, True, accessible="อนุญาตวางข้อความ")
        row.addWidget(self.paste_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _try_step(self):
        page, layout = self._page("4 · ลองพูดดู")
        self.try_instructions = label("", "tryInstructions")
        layout.addWidget(self.try_instructions)
        self.try_field = QPlainTextEdit()
        self.try_field.setObjectName("tryField")
        self.try_field.setTabChangesFocus(True)
        self.try_field.setAccessibleName("ช่องทดลองวางข้อความ")
        self.try_field.setPlaceholderText("ข้อความที่พูดจะถูกวางที่นี่…")
        self.try_field.setMinimumHeight(110)
        self.try_field.textChanged.connect(self._try_changed)
        layout.addWidget(self.try_field, 1)
        self.try_status = label("", "stepStatus")
        layout.addWidget(self.try_status)
        self._set_try_text()
        return page

    # -- state -------------------------------------------------------------
    def current_step(self):
        """1-based current step."""
        return self.stack.currentIndex() + 1

    def go_to(self, step):
        """Show step 1..4 (values are clamped)."""
        index = max(0, min(len(STEPS) - 1, int(step) - 1))
        if index != self.stack.currentIndex():
            self.stack.setCurrentIndex(index)
            self.step_changed.emit(index + 1)
        self._update()
        if index == 3:
            self.try_field.setFocus()

    def next(self):
        if self.stack.currentIndex() == len(STEPS) - 1:
            self.finished.emit()
        else:
            self.go_to(self.current_step() + 1)

    def back(self):
        self.go_to(self.current_step() - 1)

    def mark_done(self, step, done=True):
        self.done[step - 1] = bool(done)
        self._update()

    def _update(self):
        current = self.stack.currentIndex()
        for index, item in enumerate(self.step_labels):
            state = "current" if index == current else ("done" if self.done[index] else "todo")
            mark = "✓" if self.done[index] else str(index + 1)
            text = f"{mark}&nbsp;&nbsp;{STEPS[index]}"
            # Bold via markup: app-wide QSS font rules would override setFont() on repolish.
            item.setText(f"<b>{text}</b>" if index == current else text)
            item.setProperty("state", state)
            item.setAccessibleName(f"ขั้นที่ {index + 1} {STEPS[index]}" + (" เสร็จแล้ว" if self.done[index] else ""))
            repolish(item)
        self.back_button.setEnabled(current > 0)
        last = current == len(STEPS) - 1
        self.next_button.setText("เสร็จสิ้น" if last else "ถัดไป")
        self.next_button.setAccessibleName("เสร็จสิ้นการตั้งค่า" if last else "ไปขั้นถัดไป")
        self.next_button.setProperty("primary", self.done[current])
        repolish(self.next_button)

    # -- setters -----------------------------------------------------------
    def set_model(self, name, size_gb, ready):
        self._ready = bool(ready)
        self.model_name.setText(name)
        self.model_info.setText(f"ขนาด {format_gb(size_gb)} · ดาวน์โหลดครั้งเดียว แล้วใช้แบบออฟไลน์ได้")
        if ready:
            self._downloading = False
            self.model_progress.hide()
            self.model_status.setText("✓ โมเดลพร้อมใช้งาน")
        elif not self._downloading:
            self.model_status.setText("ยังไม่ได้ดาวน์โหลด")
        self._update_model_buttons()
        self.mark_done(1, ready)

    def set_downloading(self, downloading):
        self._downloading = bool(downloading) and not self._ready
        self.model_progress.setVisible(self._downloading)
        if not self._downloading and not self._ready:
            self.model_status.setText("หยุดแล้ว · กดดาวน์โหลดเพื่อโหลดต่อจากเดิม")
        self._update_model_buttons()

    def _update_model_buttons(self):
        self.download_button.setVisible(not self._ready and not self._downloading)
        self.stop_button.setVisible(self._downloading)

    def set_progress(self, percent, text):
        if not self._ready:
            self._downloading = True
        self.model_progress.setVisible(self._downloading)
        if percent is None:
            self.model_progress.setRange(0, 0)
        else:
            self.model_progress.setRange(0, 100)
            self.model_progress.setValue(max(0, min(100, int(percent))))
        if text:
            self.model_status.setText(text)
        self._update_model_buttons()

    def set_microphones(self, microphones, selected_id):
        self.microphone.blockSignals(True)
        self.microphone.clear()
        self.microphone.addItem("ไมค์เริ่มต้นของระบบ", "")
        for text, device_id in microphones:
            if device_id:
                self.microphone.addItem(text, device_id)
        self.microphone.setCurrentIndex(max(0, self.microphone.findData(selected_id)))
        self.microphone.blockSignals(False)

    def set_level(self, level):
        level = max(0, min(100, int(level)))
        self.level.setValue(level)
        if level > LEVEL_THRESHOLD and not self.done[1]:
            self.mic_status.setText("✓ ได้ยินเสียงแล้ว ไมค์ใช้งานได้")
            self.mark_done(2)

    def set_permissions(self, shortcut_text, shortcut_ok, paste_ok):
        self.shortcut_status.setText(("✓ " if shortcut_ok else "") + "ปุ่มลัด: " + shortcut_text)
        self.paste_status.setText("✓ วางข้อความ: อนุญาตแล้ว" if paste_ok else "วางข้อความ: ยังไม่ได้อนุญาต")
        self.shortcut_button.setProperty("primary", not shortcut_ok)
        self.paste_button.setProperty("primary", not paste_ok)
        self.shortcut_button.setText("เปิดใช้ใหม่" if shortcut_ok else "เปิดใช้ปุ่มลัด")
        self.paste_button.setText("ขอสิทธิ์ใหม่" if paste_ok else "อนุญาตวางข้อความ")
        repolish(self.shortcut_button)
        repolish(self.paste_button)
        self.mark_done(3, shortcut_ok and paste_ok)

    def set_hotkey(self, text):
        self._hotkey = text or "Meta+H"
        self._set_try_text()

    def _set_try_text(self):
        self.try_instructions.setText(f"คลิกในช่องด้านล่าง กด {self._hotkey} แล้วพูด · กด {self._hotkey} อีกครั้งเมื่อพูดจบ")
        if not self.done[3]:
            self.try_status.setText("ข้อความจะถูกวางลงช่องนี้อัตโนมัติ")

    def _try_changed(self):
        if self.try_field.toPlainText().strip() and not self.done[3]:
            self.try_status.setText("✓ สำเร็จ! ใช้แบบเดียวกันได้กับทุกแอป · กดเสร็จสิ้นเพื่อเริ่มใช้งาน")
            self.mark_done(4)
