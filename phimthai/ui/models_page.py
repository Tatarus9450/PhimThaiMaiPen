"""Model management page: one card per model with a single primary action."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QMenu, QProgressBar,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ._common import (PAGE_MIN_WIDTH, SPACE_L, SPACE_M, SPACE_S, button, format_bytes,
                      format_gb, label, repolish)

LANGUAGE_NAMES = {"Thai": "ไทย", "English": "อังกฤษ", "multilingual": "หลายภาษา",
                  "28 other languages": "อีก 28 ภาษา", "Thai to English": "ไทย → อังกฤษ"}


def _languages(spec):
    return " · ".join(LANGUAGE_NAMES.get(item, item) for item in getattr(spec, "languages", ()))


def _is_beta(spec):
    # Typhoon and Qwen only add optional CUDA to a tested CPU path; no badge for them.
    devices = getattr(spec, "devices", ())
    if not any(device in ("gpu", "npu") for device in devices):
        return False
    return "cpu" not in devices or getattr(spec, "backend", "") not in {"typhoon", "qwen"}


class ModelCard(QFrame):
    """A single model card. Emits through the owning page's signals."""

    def __init__(self, page, spec, installed_bytes, selected, downloading):
        super().__init__()
        self.page = page
        self.spec = spec
        self.model_id = spec.id
        self.installed = installed_bytes > 0
        self.selected = selected and self.installed
        self.downloading = downloading
        self.local = getattr(spec, "origin", "catalog") == "local"
        self.setObjectName("modelCard")
        self.setProperty("selected", bool(self.selected))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName(f"โมเดล {spec.name}")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_M, SPACE_M, SPACE_M, SPACE_M)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.name_label = label(spec.name, "modelName")
        font = self.name_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.1)
        self.name_label.setFont(font)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        title_row.addWidget(self.name_label, 1)
        self.chips = []
        for tag in getattr(spec, "tags", ()):
            chip = label(tag, "chip", wrap=False)
            chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
            self.chips.append(chip)
            title_row.addWidget(chip)
        self.beta_badge = None
        if _is_beta(spec) and getattr(spec, "kind", "asr") == "asr":
            accelerators = "/".join(d.upper() for d in spec.devices if d in ("gpu", "npu"))
            self.beta_badge = label(f"{accelerators} Beta", "betaBadge", wrap=False)
            self.beta_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
            self.beta_badge.setToolTip(f"เร่งความเร็วด้วย {accelerators} ได้แบบทดลอง ผลลัพธ์อาจไม่แน่นอน · CPU ใช้งานได้ปกติ")
            self.beta_badge.setAccessibleName(f"{accelerators} รุ่นทดลอง")
            title_row.addWidget(self.beta_badge)
        layout.addLayout(title_row)

        facts = []
        if _languages(spec):
            facts.append("ภาษา " + _languages(spec))
        facts.append("ขนาด " + format_gb(getattr(spec, "download_gb", 0)))
        if getattr(spec, "memory_gb", 0):
            facts.append(f"RAM ~{spec.memory_gb} GB")
        if self.local:
            facts.append("นำเข้าเอง")
        self.facts_label = label(" · ".join(facts), "muted")
        layout.addWidget(self.facts_label)

        self.status_label = label(self._status_text(installed_bytes), "modelStatus")
        layout.addWidget(self.status_label)

        revision = getattr(spec, "revision", "") or ""
        technical = [f"Repo: {spec.repo}", f"Backend: {spec.backend}"]
        if revision:
            technical.append(f"Revision: {revision[:12]}")
        if getattr(spec, "license", ""):
            technical.append(f"License: {spec.license}")
        if getattr(spec, "status", ""):
            technical.append(f"สถานะการทดสอบ: {spec.status}")
        self.technical_label = label("\n".join(technical), "technicalInfo")
        self.technical_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.technical_label.hide()
        layout.addWidget(self.technical_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(SPACE_S)
        self.progress = QProgressBar()
        self.progress.setObjectName("modelProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setAccessibleName(f"ความคืบหน้าการดาวน์โหลด {spec.name}")
        self.progress.setVisible(downloading)
        if downloading:
            self.progress.setRange(0, 0)
        action_row.addWidget(self.progress, 1)
        if not downloading:
            action_row.addStretch(1)

        self.primary = self._primary_button()
        if self.primary is not None:
            action_row.addWidget(self.primary)
        elif self.installed and getattr(spec, "kind", "asr") != "asr":
            note = label("ใช้อัตโนมัติในโหมด TH → ENG", "muted", wrap=False)
            action_row.addWidget(note)

        self.more = QToolButton()
        self.more.setObjectName("cardMenu")
        self.more.setText("⋯")
        self.more.setAccessibleName(f"ตัวเลือกเพิ่มเติมของ {spec.name}")
        self.more.setToolTip("ตัวเลือกเพิ่มเติม")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setMinimumSize(36, 36)
        self.more.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.menu = QMenu(self.more)
        self.repair_action = QAction("ซ่อมไฟล์ / ดาวน์โหลดใหม่", self.menu)
        self.repair_action.triggered.connect(lambda: page.download.emit(self.model_id))
        self.repair_action.setVisible(self.installed and not self.local)
        self.repair_action.setEnabled(not downloading)
        self.remove_action = QAction("ลบโมเดล", self.menu)
        self.remove_action.triggered.connect(lambda: page.remove.emit(self.model_id))
        self.remove_action.setVisible(self.installed or self.local)
        self.remove_action.setEnabled(not downloading)
        self.technical_action = QAction("แสดงข้อมูลทางเทคนิค", self.menu)
        self.technical_action.setCheckable(True)
        self.technical_action.toggled.connect(self.technical_label.setVisible)
        self.menu.addAction(self.repair_action)
        self.menu.addAction(self.remove_action)
        self.menu.addSeparator()
        self.menu.addAction(self.technical_action)
        self.more.setMenu(self.menu)
        action_row.addWidget(self.more)
        layout.addLayout(action_row)

    def _status_text(self, installed_bytes):
        size = format_bytes(installed_bytes)
        if self.downloading:
            return "กำลังดาวน์โหลด… หยุดแล้วโหลดต่อได้"
        if self.selected:
            return "✓ กำลังใช้งานโมเดลนี้" + (f" · ติดตั้งแล้ว {size}" if size else "")
        if self.installed:
            return "ติดตั้งแล้ว พร้อมใช้แบบออฟไลน์" + (f" · {size}" if size else "")
        if self.local:
            return "ไม่พบไฟล์โมเดล · นำเข้าจากโฟลเดอร์ต้นฉบับอีกครั้ง"
        return "ยังไม่ได้ดาวน์โหลด"

    def _primary_button(self):
        name = self.spec.name
        if self.downloading:
            widget = button("หยุด", self.page.cancel_download.emit,
                            accessible=f"หยุดดาวน์โหลด {name}", name="cardAction")
        elif self.selected:
            widget = button("กำลังใช้อยู่", accessible=f"{name} กำลังใช้อยู่", name="cardAction")
            widget.setEnabled(False)
        elif self.installed:
            if getattr(self.spec, "kind", "asr") != "asr":
                return None  # Translation models are used automatically by TH → ENG.
            widget = button("ใช้โมเดลนี้", lambda: self.page.use.emit(self.model_id), True,
                            accessible=f"ใช้โมเดล {name}", name="cardAction")
        elif self.local:
            return None
        else:
            widget = button("ดาวน์โหลด", lambda: self.page.download.emit(self.model_id), True,
                            accessible=f"ดาวน์โหลด {name}", name="cardAction")
        return widget

    def set_progress(self, percent, text):
        self.progress.show()
        if percent is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, int(percent))))
        if text:
            self.status_label.setText(text)


class ModelsPage(QWidget):
    download = Signal(str)
    cancel_download = Signal()
    use = Signal(str)
    remove = Signal(str)
    import_folder = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modelsPage")
        self.setMinimumWidth(PAGE_MIN_WIDTH)
        self.cards = {}
        self._progress = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_M)

        header = QHBoxLayout()
        header.setSpacing(SPACE_S)
        self.intro = label("โมเดลทั้งหมดทำงานในเครื่อง ดาวน์โหลดครั้งเดียวแล้วใช้แบบออฟไลน์ได้", "muted")
        header.addWidget(self.intro, 1)
        self.import_button = button("นำเข้าโมเดลจากโฟลเดอร์…", self.choose_folder,
                                    accessible="นำเข้าโมเดลจากโฟลเดอร์", name="importModel")
        header.addWidget(self.import_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.message = label("", "pageMessage")
        self.message.setProperty("error", False)
        self.message.hide()
        layout.addWidget(self.message)

        self.asr_title = label("ถอดเสียง", "sectionTitle")
        self.translation_title = label("แปลภาษา", "sectionTitle")
        for title in (self.asr_title, self.translation_title):
            font = title.font()
            font.setBold(True)
            title.setFont(font)
        self.asr_list = QVBoxLayout()
        self.asr_list.setSpacing(SPACE_S)
        self.translation_list = QVBoxLayout()
        self.translation_list.setSpacing(SPACE_S)
        layout.addWidget(self.asr_title)
        layout.addLayout(self.asr_list)
        layout.addSpacing(SPACE_L - SPACE_M)
        layout.addWidget(self.translation_title)
        layout.addLayout(self.translation_list)
        layout.addStretch(1)

    # -- actions ---------------------------------------------------------
    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์โมเดล")
        if path:
            self.import_folder.emit(path)

    # -- setters ---------------------------------------------------------
    def refresh(self, catalog, installed, selected_id, downloading_id=None):
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards = {}
        if downloading_id is None:
            self._progress.clear()
        has_translation = False
        for model_id, spec in catalog.items():
            card = ModelCard(self, spec, int(installed.get(model_id, 0) or 0),
                             model_id == selected_id, model_id == downloading_id)
            self.cards[model_id] = card
            if getattr(spec, "kind", "asr") == "asr":
                self.asr_list.addWidget(card)
            else:
                has_translation = True
                self.translation_list.addWidget(card)
            if model_id == downloading_id and model_id in self._progress:
                card.set_progress(*self._progress[model_id])
        self.translation_title.setVisible(has_translation)

    def set_progress(self, model_id, percent, text):
        self._progress[model_id] = (percent, text)
        card = self.cards.get(model_id)
        if card is not None:
            card.set_progress(percent, text)

    def set_message(self, text, error=False):
        self.message.setText(text)
        self.message.setProperty("error", bool(error))
        self.message.setAccessibleName(("ข้อผิดพลาด: " if error else "") + text)
        self.message.setVisible(bool(text))
        repolish(self.message)
