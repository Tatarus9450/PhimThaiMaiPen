"""Small shared builders for the decoupled UI pages (no MainWindow imports)."""
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout

SPACE_S, SPACE_M, SPACE_L = 12, 16, 24
PAGE_MIN_WIDTH = 560


def label(text="", name=None, wrap=True, rich=False):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    widget.setTextFormat(rich_format() if rich else plain_format())
    if name:
        widget.setObjectName(name)
    # Wrapped Thai text must shrink with the page instead of forcing a
    # horizontal scrollbar.
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    # (no forced min width; QLabel word-wrap already shrinks)
    return widget


def plain_format():
    from PySide6.QtCore import Qt
    return Qt.TextFormat.PlainText


def rich_format():
    from PySide6.QtCore import Qt
    return Qt.TextFormat.RichText


def button(text, callback=None, primary=False, accessible=None, name=None):
    widget = QPushButton(text)
    widget.setMinimumHeight(36)
    widget.setAccessibleName(accessible or text)
    if primary:
        widget.setProperty("primary", True)
    if name:
        widget.setObjectName(name)
    if callback is not None:
        widget.clicked.connect(lambda checked=False: callback())
    return widget


def section(title, name="settingsSection"):
    """Return (frame, body_layout) for a titled group."""
    frame = QFrame()
    frame.setObjectName(name)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(SPACE_M, SPACE_M, SPACE_M, SPACE_M)
    layout.setSpacing(SPACE_S)
    heading = label(title, "sectionTitle")
    font = heading.font()
    font.setBold(True)
    heading.setFont(font)
    layout.addWidget(heading)
    return frame, layout


def repolish(widget):
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def format_gb(value):
    if not value:
        return "ไม่ทราบขนาด"
    if value < 1:
        return f"{round(value * 1000)} MB"
    return f"{value:.1f} GB"


def format_bytes(size):
    if size <= 0:
        return ""
    return format_gb(size / 1e9)
