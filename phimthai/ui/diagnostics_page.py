"""Diagnostics as a readable checklist, with raw details tucked away."""
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QPlainTextEdit, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ._common import PAGE_MIN_WIDTH, SPACE_M, SPACE_S, button, label

GLYPHS = {"ok": "✓", "fail": "✕", "unknown": "?"}
STATE_NAMES = {"ok": "ผ่าน", "fail": "มีปัญหา", "unknown": "ยังไม่ทราบ"}


@dataclass
class Check:
    id: str
    title: str
    ok: "bool | None"
    detail: str
    action_label: str = ""
    action_id: str = ""

    @property
    def state(self):
        return "unknown" if self.ok is None else ("ok" if self.ok else "fail")


class CheckRow(QFrame):
    def __init__(self, check, emit_action):
        super().__init__()
        self.check = check
        self.setObjectName("checkRow")
        self.setProperty("state", check.state)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_S)
        layout.setSpacing(SPACE_S)
        self.icon = label(GLYPHS[check.state], "checkIcon", wrap=False)
        self.icon.setProperty("state", check.state)
        self.icon.setFixedWidth(24)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        font = self.icon.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        self.icon.setFont(font)
        self.icon.setAccessibleName(STATE_NAMES[check.state])
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(check.title, "checkTitle")
        title_font = self.title.font()
        title_font.setBold(True)
        self.title.setFont(title_font)
        text.addWidget(self.title)
        self.detail = label(check.detail, "checkDetail")
        self.detail.setVisible(bool(check.detail))
        text.addWidget(self.detail)
        layout.addLayout(text, 1)
        self.action_button = None
        if check.action_label and check.action_id:
            self.action_button = button(check.action_label, lambda: emit_action(check.action_id),
                                        check.ok is False, accessible=f"{check.action_label} · {check.title}",
                                        name="checkAction")
            layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName(f"{check.title}: {STATE_NAMES[check.state]}")
        self.setAccessibleDescription(check.detail)


class DiagnosticsPage(QWidget):
    action = Signal(str)
    refresh = Signal()
    copy_report = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diagnosticsPage")
        self.setMinimumWidth(PAGE_MIN_WIDTH)
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_M)

        header = QHBoxLayout()
        header.setSpacing(SPACE_S)
        self.summary = label("ยังไม่ได้ตรวจสอบ", "diagnosticSummary")
        font = self.summary.font()
        font.setBold(True)
        self.summary.setFont(font)
        header.addWidget(self.summary, 1)
        self.refresh_button = button("ตรวจสอบใหม่", self.refresh.emit, True, accessible="ตรวจสอบเครื่องใหม่")
        self.copy_button = button("คัดลอกรายงานปัญหา", self.copy_report.emit,
                                  accessible="คัดลอกรายงานปัญหาไปคลิปบอร์ด")
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.check_list = QVBoxLayout()
        self.check_list.setSpacing(SPACE_S)
        layout.addLayout(self.check_list)

        self.raw_toggle = QToolButton()
        self.raw_toggle.setObjectName("sectionToggle")
        self.raw_toggle.setText("ข้อมูลทางเทคนิค")
        self.raw_toggle.setCheckable(True)
        self.raw_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.raw_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.raw_toggle.setAccessibleName("แสดงข้อมูลทางเทคนิค")
        self.raw_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.raw_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.raw = QPlainTextEdit()
        self.raw.setObjectName("diagnosticsRaw")
        self.raw.setReadOnly(True)
        self.raw.setTabChangesFocus(True)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.raw.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.raw.setAccessibleName("ข้อมูลทางเทคนิคของเครื่อง")
        self.raw.setMinimumHeight(180)
        self.raw.hide()
        layout.addWidget(self.raw)
        self.raw_toggle.toggled.connect(self._toggle_raw)
        layout.addStretch(1)

    def _toggle_raw(self, checked):
        self.raw.setVisible(checked)
        self.raw_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def set_checks(self, checks):
        for row in self.rows:
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        for check in checks:
            row = CheckRow(check, self.action.emit)
            self.rows.append(row)
            self.check_list.addWidget(row)
        failed = sum(1 for check in checks if check.ok is False)
        unknown = sum(1 for check in checks if check.ok is None)
        if not checks:
            text = "ยังไม่ได้ตรวจสอบ"
        elif failed:
            text = f"พบปัญหา {failed} รายการ · ดูวิธีแก้ด้านล่าง"
        elif unknown:
            text = f"ส่วนใหญ่พร้อมใช้ · มี {unknown} รายการที่ยังตรวจไม่ได้"
        else:
            text = "✓ ทุกอย่างพร้อมใช้งาน"
        self.summary.setText(text)

    def set_raw(self, text):
        self.raw.setPlainText(text)
