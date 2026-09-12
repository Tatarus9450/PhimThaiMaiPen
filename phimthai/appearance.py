"""Native glass surfaces and a complete, desktop-theme-independent palette.

The lens samples only our own painted backdrop. It never captures the desktop,
and both the atmosphere and the panel material are cached between repaints.
"""
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath,
                          QPalette, QPen, QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory, QWidget


_REDUCED = "phimthaiReducedTransparency"


def _color(value, alpha=None):
    color = QColor(value)
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def _rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _asset_url(name):
    # Quote both QSS delimiters and path characters, including quoted installs.
    path = str(Path(__file__).resolve().parent / "assets" / name)
    return 'url("' + path.replace("\\", "\\\\").replace('"', '\\"') + '")'


class _GlassStyle(QProxyStyle):
    """Keep native control behavior, with legible arrows and checked states."""

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def drawPrimitive(self, element, option, painter, widget=None):
        arrow = {QStyle.PrimitiveElement.PE_IndicatorArrowDown: 0,
                 QStyle.PrimitiveElement.PE_IndicatorArrowUp: 180,
                 QStyle.PrimitiveElement.PE_IndicatorArrowLeft: 90,
                 QStyle.PrimitiveElement.PE_IndicatorArrowRight: -90}
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        if element in arrow:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(QRectF(option.rect).center())
            painter.rotate(arrow[element])
            painter.setPen(QPen(QColor("#c3d8e4" if enabled else "#899eaf"),
                                1.6, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(QPolygonF([QPointF(-3, -1.5), QPointF(0, 1.5),
                                            QPointF(3, -1.5)]))
            painter.restore()
            return
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
            checked = bool(option.state & (QStyle.StateFlag.State_On |
                                          QStyle.StateFlag.State_NoChange))
            painter.setBrush(QColor(("#8fdcc4" if enabled else "#536e72")
                                    if checked else "#172b3b"))
            focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
            painter.setPen(QPen(QColor("#dcfff0" if focused else "#698b9d"),
                                1.8 if focused else 1))
            painter.drawRoundedRect(rect, 4, 4)
            if checked:
                painter.setPen(QPen(QColor("#102d2a"), 2, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                left, top, width, height = rect.x(), rect.y(), rect.width(), rect.height()
                if option.state & QStyle.StateFlag.State_NoChange:
                    painter.drawLine(QPointF(left + width * .25, top + height * .5),
                                     QPointF(left + width * .75, top + height * .5))
                else:
                    painter.drawPolyline(QPolygonF([
                        QPointF(left + width * .23, top + height * .52),
                        QPointF(left + width * .43, top + height * .72),
                        QPointF(left + width * .79, top + height * .29)]))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


class GlassCanvas(QWidget):
    """An opaque ink backdrop with soft pools of light, drawn once per size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._backdrop = None
        self._backdrop_key = None

    def backdrop(self):
        ratio = self.devicePixelRatioF()
        reduced = bool(QApplication.instance().property(_REDUCED))
        key = (self.width(), self.height(), ratio, reduced)
        if key == self._backdrop_key:
            return self._backdrop
        pixmap = QPixmap(max(1, round(self.width() * ratio)),
                         max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor("#0b1422"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not reduced:
            base = QLinearGradient(0, 0, width, height)
            base.setColorAt(0, QColor("#132634"))
            base.setColorAt(0.52, QColor("#101c30"))
            base.setColorAt(1, QColor("#101c29"))
            painter.fillRect(self.rect(), base)
            for x, y, radius, tint, strength in (
                (0.03, 0.04, 0.65, "#33ac9c", 115),
                (0.76, 0.18, 0.52, "#427cbb", 91),
                (1.00, 0.92, 0.57, "#388c81", 82),
                (0.36, 1.00, 0.47, "#666dae", 59),
            ):
                glow = QRadialGradient(width * x, height * y,
                                       max(width, height) * radius)
                glow.setColorAt(0, _color(tint, strength))
                glow.setColorAt(0.42, _color(tint, strength // 3))
                glow.setColorAt(1, _color(tint, 0))
                painter.fillRect(self.rect(), glow)
            # A quiet curved light ribbon gives the lens an identifiable backdrop.
            ribbon = QPainterPath()
            ribbon.moveTo(width * 0.18, -height * 0.1)
            ribbon.cubicTo(width * 0.95, height * 0.10, width * 0.26,
                           height * 0.63, width * 1.15, height * 0.90)
            for thickness, alpha in ((96, 2), (62, 3), (34, 4), (14, 4)):
                painter.setPen(QPen(_color("#a5e6ec", alpha), thickness))
                painter.drawPath(ribbon)
        painter.end()
        self._backdrop_key, self._backdrop = key, pixmap
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.backdrop())


class GlassPanel(QWidget):
    """Frosted lens, directional rim, and inset ambient shadow; native children."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self._material = None
        self._material_key = None

    def _canvas(self):
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, GlassCanvas):
                return ancestor
            ancestor = ancestor.parentWidget()
        return None

    def _surface(self):
        ratio = self.devicePixelRatioF()
        reduced = bool(QApplication.instance().property(_REDUCED))
        canvas = self._canvas()
        backdrop = canvas.backdrop() if canvas else None
        origin = self.mapTo(canvas, QPoint(0, 0)) if canvas else QPoint()
        key = (self.width(), self.height(), ratio, reduced,
               backdrop.cacheKey() if backdrop else None, origin.x(), origin.y())
        if key == self._material_key:
            return self._material
        pixmap = QPixmap(max(1, round(self.width() * ratio)),
                         max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing |
                               QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(5, 4, -5, -7)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return pixmap
        if not reduced:
            # Offset rings stay inside the widget, avoiding heavyweight effects.
            for spread, alpha in ((5, 10), (3, 15), (1, 23)):
                shadow = rect.adjusted(-spread, -spread + 3, spread, spread + 3)
                painter.fillPath(_rounded(shadow, 23 + spread), _color("#000711", alpha))
        path = _rounded(rect, 22)
        painter.save()
        painter.setClipPath(path)
        if reduced:
            painter.fillRect(rect, QColor("#182737"))
        else:
            if backdrop:
                # A slight magnification bends the diffuse light across the rim.
                source = QRectF(origin.x() + rect.x(), origin.y() + rect.y(),
                                rect.width(), rect.height())
                source.adjust(source.width() * .013, source.height() * .013,
                              -source.width() * .013, -source.height() * .013)
                source = QRectF(source.x() * ratio, source.y() * ratio,
                                source.width() * ratio, source.height() * ratio)
                painter.drawPixmap(rect, backdrop, source)
            frost = QLinearGradient(rect.topLeft(), rect.bottomRight())
            frost.setColorAt(0, _color("#314756", 160))
            frost.setColorAt(.36, _color("#172b3c", 183))
            frost.setColorAt(1, _color("#0b192b", 208))
            painter.fillRect(rect, frost)
            reflection = QRadialGradient(rect.topLeft(), max(180, rect.width() * .85))
            reflection.setColorAt(0, _color("#d4fff4", 17))
            reflection.setColorAt(.42, _color("#9fe8e3", 5))
            reflection.setColorAt(1, _color("#9fe8e3", 0))
            painter.fillRect(rect, reflection)
            shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            shade.setColorAt(0, _color("#ffffff", 3))
            shade.setColorAt(.80, _color("#000613", 0))
            shade.setColorAt(1, _color("#000613", 32))
            painter.fillRect(rect, shade)
        painter.restore()
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, _color("#d2fff4", 108 if not reduced else 42))
        rim.setColorAt(.28, _color("#c0d9ed", 38))
        rim.setColorAt(.70, _color("#b3ccec", 14))
        rim.setColorAt(1, _color("#b9e8ea", 44))
        painter.setPen(QPen(rim, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if not reduced:
            inset = rect.adjusted(1.2, 1.2, -1.2, -1.2)
            inner = QLinearGradient(inset.topLeft(), inset.bottomLeft())
            inner.setColorAt(0, _color("#dcfff8", 24))
            inner.setColorAt(.16, _color("#dcfff8", 0))
            inner.setColorAt(1, _color("#000715", 30))
            painter.setPen(QPen(inner, .8))
            painter.drawPath(_rounded(inset, 21))
        painter.end()
        self._material_key, self._material = key, pixmap
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._surface())


def apply_style(app, reduced_transparency=False):
    """Apply coherent dark glass, independent of KDE/GNOME's current palette."""
    app.setProperty(_REDUCED, bool(reduced_transparency))
    app.setStyle(_GlassStyle())
    palette = QPalette()
    colors = {
        "Window": "#101d2c", "WindowText": "#e7f0f6", "Base": "#112131",
        "AlternateBase": "#1b2f41", "Text": "#e7f0f6", "Button": "#263b4c",
        "ButtonText": "#e7f0f6", "BrightText": "#ffffff", "ToolTipBase": "#24394a",
        "ToolTipText": "#f2f8fc", "PlaceholderText": "#9dafbf", "Highlight": "#38675f",
        "HighlightedText": "#f2fff9", "Light": "#536b7e", "Midlight": "#3c5367",
        "Mid": "#2b4055", "Dark": "#0b1422", "Shadow": "#050c16",
        "Link": "#a0efd9", "LinkVisited": "#c6c1ff", "Accent": "#9ce7d0",
    }
    disabled = {"WindowText": "#8b9cad", "Text": "#8b9cad", "ButtonText": "#8b9cad",
                "Button": "#1c2b3b", "Highlight": "#334953", "HighlightedText": "#b0bec9",
                "PlaceholderText": "#8696a8"}
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, color in colors.items():
            if group == QPalette.ColorGroup.Disabled:
                color = disabled.get(role, color)
            palette.setColor(group, getattr(QPalette.ColorRole, role), QColor(color))
    # standardPalette() follows the system color scheme on native Wayland.
    # Explicit entries survive subsequent Qt system palette/theme updates.
    app.setPalette(palette)
    app.setStyleSheet(_STYLESHEET.replace("@DOWN_ARROW@", _asset_url("glass-chevron-down.svg"))
                     .replace("@UP_ARROW@", _asset_url("glass-chevron-up.svg")))
    for widget in app.allWidgets():
        if isinstance(widget, (GlassCanvas, GlassPanel)):
            widget.update()


_STYLESHEET = """
QWidget { color: #e7f0f6; font-size: 13px; }
QMainWindow, QDialog { background: #101d2c; }
QWidget#canvas, QWidget#sidebar, QWidget#workspace, QWidget#page,
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QLabel { background: transparent; border: none; }
QLabel#brand { color: #f0fbf8; font-size: 24px; font-weight: 700; }
QLabel#heading { color: #eff8fb; font-size: 25px; font-weight: 600; }
QLabel#muted { color: #c1d0dc; }
QLabel#shortcut { color: #c6ddd9; background: rgba(128, 194, 186, 20);
    border: 1px solid rgba(164, 218, 210, 34); border-radius: 9px; padding: 5px 9px; }
QLabel#status { color: #d6e9ee; background: rgba(111, 169, 189, 16);
    border: 1px solid rgba(145, 194, 211, 28); border-radius: 13px; padding: 10px 12px; }
QLabel#recording { color: #ffccc5; }
QLabel#betaWarning { color: #ff9b9b; background: rgba(130, 24, 38, 38);
    border: 1px solid rgba(255, 130, 140, 85); border-radius: 10px; padding: 9px 11px; }
QListWidget { background: #142638; border: 1px solid #40576a;
    border-radius: 14px; padding: 5px; outline: none; }
QListWidget::item { color: #c4d5e2; padding: 10px 12px; border-radius: 10px; }
QListWidget::item:hover { background: rgba(162, 211, 222, 14); }
QListWidget::item:selected { color: #e6fff7; background: #28534f; }
QListWidget#navigation { background: transparent; border: none; padding: 0; }
QListWidget#navigation::item { margin: 3px 0; padding: 13px 12px; border: 1px solid transparent; }
QListWidget#navigation::item:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
    stop:0 rgba(118, 221, 193, 39), stop:1 rgba(126, 198, 220, 18));
    border: 1px solid rgba(177, 237, 224, 62); color: #e6fff7; }
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #112333; color: #e7f0f6; border: 1px solid #40586b;
    border-radius: 10px; padding: 7px 10px; selection-background-color: #38675f;
    selection-color: #f2fff9; placeholder-text-color: #a5bbc9;
}
QPlainTextEdit#editor { background: rgba(5, 18, 31, 132); border-radius: 17px;
    border: 1px solid rgba(157, 190, 211, 53); padding: 15px; font-size: 16px; }
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit#editor:focus { border: 1px solid #9ce7d0; }
QComboBox { padding-right: 29px; min-height: 20px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: none; border-top-right-radius: 9px;
    border-bottom-right-radius: 9px; background: transparent; }
QComboBox::down-arrow { image: @DOWN_ARROW@; width: 16px; height: 16px; }
QComboBox QAbstractItemView { background: #1b3043; color: #e7f0f6;
    selection-background-color: #38675f; selection-color: #f2fff9;
    border: 1px solid #5a7384; padding: 5px; outline: none; }
QSpinBox { padding-right: 32px; min-height: 20px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 29px; height: 19px; border: none; border-top-right-radius: 9px;
    background: transparent; margin: 1px 1px 0 0; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 29px; height: 19px; border: none; border-bottom-right-radius: 9px;
    background: transparent; margin: 0 1px 1px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #284554; }
QSpinBox::up-arrow { image: @UP_ARROW@; width: 14px; height: 14px; }
QSpinBox::down-arrow { image: @DOWN_ARROW@; width: 14px; height: 14px; }
QPushButton { color: #e2edf4; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 rgba(116, 151, 171, 35), stop:1 rgba(72, 105, 132, 24));
    border: 1px solid rgba(172, 203, 220, 67); border-radius: 12px;
    padding: 8px 13px; min-height: 18px; font-weight: 500; }
QPushButton:hover { background: rgba(152, 197, 209, 36); border-color: #759baf; }
QPushButton:pressed { background: #1a3946; }
QPushButton:focus { border: 1px solid #a5f3dc; }
QPushButton[primary=true] { color: #102d2a; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
    stop:0 #c1f9e7, stop:0.55 #a1e9d1, stop:1 #87d3c9);
    border: 1px solid #d0ffef; font-weight: 700; }
QPushButton[primary=true]:hover { background: #cbffec; border-color: #effff8; }
QPushButton[primary=true]:pressed { background: #8bd3c2; }
QPushButton:disabled, QPushButton[primary=true]:disabled { color: #899eaf;
    background: #1b2c3c; border-color: #354b5d; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #899eaf;
    background: #1b2c3c; border-color: #354b5d; }
QCheckBox { color: #dbe8f0; spacing: 9px; background: transparent; }
QCheckBox:disabled { color: #899eaf; }
QCheckBox::indicator { width: 18px; height: 18px; }
QGroupBox { background: rgba(19, 38, 54, 100); border: 1px solid #3b5365;
    border-radius: 13px; margin-top: 11px; padding: 14px 11px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #dcecf2; }
QProgressBar { color: #d8eee9; background: #122333; border: 1px solid #3d5a69;
    border-radius: 8px; text-align: center; min-height: 17px; font-size: 11px; }
QProgressBar::chunk { background: #3d897a; border-radius: 7px; }
QProgressBar[textVisible=false] { min-height: 6px; max-height: 8px; border-radius: 4px; }
QProgressBar[textVisible=false]::chunk { border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #4c677c; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #789eae; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; }
QScrollBar::handle:horizontal { background: #4c677c; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenu { color: #e7f0f6; background: #1b2d3f; border: 1px solid #526d7f;
    border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 23px; border-radius: 5px; }
QMenu::item:selected { color: #edfff7; background: #38675f; }
QMenu::item:disabled { color: #899eaf; }
QMenu::separator { height: 1px; background: #40576a; margin: 5px; }
QToolTip { color: #f2f8fc; background: #24394a; border: 1px solid #647f90;
    padding: 6px; }
QStatusBar { color: #aebfcf; background: #0e1b2a; font-size: 11px; }
QStatusBar::item { border: none; }
"""
