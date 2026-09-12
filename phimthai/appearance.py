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
            painter.setPen(QPen(QColor("#d1d6e0" if enabled else "#a4acbc"),
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
            painter.setBrush(QColor(("#9bbaff" if enabled else "#566987")
                                    if checked else "#252a34"))
            focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
            painter.setPen(QPen(QColor("#dfe9ff" if focused else "#818a9c"),
                                1.8 if focused else 1))
            painter.drawRoundedRect(rect, 4, 4)
            if checked:
                painter.setPen(QPen(QColor("#182542"), 2, Qt.PenStyle.SolidLine,
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
        pixmap.fill(QColor("#13151b"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not reduced:
            base = QLinearGradient(0, 0, width, height)
            base.setColorAt(0, QColor("#272a33"))
            base.setColorAt(0.52, QColor("#191c25"))
            base.setColorAt(1, QColor("#202027"))
            painter.fillRect(self.rect(), base)
            for x, y, radius, tint, strength in (
                (0.02, 0.04, 0.65, "#d2ab69", 46),
                (0.80, 0.10, 0.52, "#4776db", 74),
                (1.00, 0.92, 0.57, "#9b8a76", 26),
                (0.36, 1.00, 0.47, "#40538c", 28),
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
                painter.setPen(QPen(_color("#b3c8ed", alpha), thickness))
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
            painter.fillRect(rect, QColor("#242730"))
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
            frost.setColorAt(0, _color("#393c46", 160))
            frost.setColorAt(.36, _color("#242730", 183))
            frost.setColorAt(1, _color("#1c2029", 208))
            painter.fillRect(rect, frost)
            reflection = QRadialGradient(rect.topLeft(), max(180, rect.width() * .85))
            reflection.setColorAt(0, _color("#fff3dc", 17))
            reflection.setColorAt(.42, _color("#cad7f2", 5))
            reflection.setColorAt(1, _color("#cad7f2", 0))
            painter.fillRect(rect, reflection)
            shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            shade.setColorAt(0, _color("#ffffff", 3))
            shade.setColorAt(.80, _color("#000613", 0))
            shade.setColorAt(1, _color("#000613", 32))
            painter.fillRect(rect, shade)
        painter.restore()
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, _color("#fff4de", 108 if not reduced else 42))
        rim.setColorAt(.28, _color("#c0d9ed", 38))
        rim.setColorAt(.70, _color("#b3ccec", 14))
        rim.setColorAt(1, _color("#b9c8ea", 44))
        painter.setPen(QPen(rim, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if not reduced:
            inset = rect.adjusted(1.2, 1.2, -1.2, -1.2)
            inner = QLinearGradient(inset.topLeft(), inset.bottomLeft())
            inner.setColorAt(0, _color("#fff7e9", 24))
            inner.setColorAt(.16, _color("#fff7e9", 0))
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
        "Window": "#1d2028", "WindowText": "#f0f1f5", "Base": "#1c1f27",
        "AlternateBase": "#2c303b", "Text": "#f0f1f5", "Button": "#353a46",
        "ButtonText": "#f0f1f5", "BrightText": "#ffffff", "ToolTipBase": "#303642",
        "ToolTipText": "#f2f8fc", "PlaceholderText": "#aeb4c2", "Highlight": "#315ab4",
        "HighlightedText": "#ffffff", "Light": "#536b7e", "Midlight": "#3c5367",
        "Mid": "#2b4055", "Dark": "#13151b", "Shadow": "#050c16",
        "Link": "#aec8ff", "LinkVisited": "#c6c1ff", "Accent": "#93b6ff",
    }
    disabled = {"WindowText": "#a0a7b5", "Text": "#a0a7b5", "ButtonText": "#a0a7b5",
                "Button": "#292d37", "Highlight": "#394659", "HighlightedText": "#bcc4d0",
                "PlaceholderText": "#a0a7b5"}
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
QWidget { color: #f0f1f5; font-size: 13px; }
QMainWindow, QDialog { background: #1d2028; }
QWidget#canvas, QWidget#sidebar, QWidget#workspace, QWidget#page,
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { background: transparent; border: none; }
QLabel#brand { color: #faf7f0; font-size: 18px; font-weight: 700; }
QLabel#heading { color: #faf7f0; font-size: 26px; font-weight: 600; }
QLabel#muted { color: #bec3cf; }
QLabel#section { color: #e2e5ed; font-size: 13px; font-weight: 600; }
QLabel#shortcut { color: #d7e4ff; background: rgba(79, 119, 202, 28);
    border: 1px solid #5c6e94; border-radius: 8px; padding: 6px 10px; }
QLabel#status { color: #cbd1dd; padding: 2px 0; }
QLabel#recording { color: #ffb8ad; }
QWidget#onboarding { background: #343027; border: 1px solid #887149; border-radius: 12px; }
QLabel#setupMessage { color: #ffe1a6; }
QLabel#betaWarning { color: #ff9b9b; background: rgba(130, 24, 38, 38);
    border: 1px solid rgba(255, 130, 140, 85); border-radius: 10px; padding: 9px 11px; }
QListWidget { background: #20242d; border: 1px solid #646d7f;
    border-radius: 12px; padding: 5px; outline: none; }
QListWidget::item { color: #d7dce7; padding: 12px; border-radius: 8px; }
QListWidget::item:hover { background: #333b4d; }
QListWidget::item:selected { color: #ffffff; background: #304c88; }
QListWidget#navigation { background: transparent; border: none; padding: 0; }
QListWidget#navigation::item { margin: 3px 0; padding: 13px 10px; border: 1px solid transparent; }
QListWidget#navigation::item:selected { background: #304c88; border: 1px solid #789de1; color: #ffffff; }
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #1e222b; color: #f0f1f5; border: 1px solid #697386;
    border-radius: 8px; padding: 7px 10px; selection-background-color: #315ab4;
    selection-color: #ffffff; placeholder-text-color: #b6becc;
}
QPlainTextEdit#editor { background: #f8f5ef; color: #252a35; border-radius: 12px;
    border: 1px solid #c6c3bc; padding: 16px; font-size: 16px;
    placeholder-text-color: #646978; selection-background-color: #315ab4; selection-color: #ffffff; }
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit#editor:focus { border: 1px solid #9dbbff; }
QComboBox { padding-right: 29px; min-height: 20px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: none; border-top-right-radius: 7px;
    border-bottom-right-radius: 7px; background: transparent; }
QComboBox::down-arrow { image: @DOWN_ARROW@; width: 16px; height: 16px; }
QComboBox QAbstractItemView { background: #252b36; color: #f0f1f5;
    selection-background-color: #315ab4; selection-color: #ffffff;
    border: 1px solid #7b8598; padding: 5px; outline: none; }
QSpinBox { padding-right: 32px; min-height: 20px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 29px; height: 19px; border: none; border-top-right-radius: 7px;
    background: transparent; margin: 1px 1px 0 0; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 29px; height: 19px; border: none; border-bottom-right-radius: 7px;
    background: transparent; margin: 0 1px 1px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #3c465a; }
QSpinBox::up-arrow { image: @UP_ARROW@; width: 14px; height: 14px; }
QSpinBox::down-arrow { image: @DOWN_ARROW@; width: 14px; height: 14px; }
QPushButton { color: #e9edf5; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #3d424f, stop:1 #303641);
    border: 1px solid #768195; border-radius: 9px;
    padding: 8px 13px; min-height: 18px; font-weight: 500; }
QPushButton:hover { background: #464f61; border-color: #a3b5d4; }
QPushButton:pressed { background: #292f3b; }
QPushButton:focus { border: 2px solid #c2d5ff; padding: 7px 12px; }
QPushButton[primary=true] { color: #ffffff; background: #3159b2;
    border: 1px solid #91b2fc; font-weight: 700; }
QPushButton[primary=true]:hover { background: #3a65c2; border-color: #d5e1ff; }
QPushButton[primary=true]:pressed { background: #254792; }
QPushButton#recordControl { font-size: 15px; }
QPushButton#modeSwitch { color: #ffe0a0; background: #423825; border-color: #b19a67; }
QPushButton#modeSwitch:hover { background: #514329; border-color: #ffe0a0; }
QPushButton#modeSwitch:pressed { background: #352e22; }
QPushButton#pasteAction { color: #d6e4ff; background: #283b61; border-color: #8aa7dd; }
QPushButton#pasteAction:hover { background: #354e7f; }
QPushButton#pasteAction:pressed { background: #213151; }
QPushButton:disabled, QPushButton[primary=true]:disabled { color: #a4acbc;
    background: #292e38; border-color: #4d5668; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #a4acbc;
    background: #292e38; border-color: #4d5668; }
QCheckBox { color: #e0e4ed; spacing: 9px; background: transparent; }
QCheckBox:disabled { color: #a4acbc; }
QCheckBox::indicator { width: 18px; height: 18px; }
QGroupBox { background: #252a34; border: 1px solid #697386;
    border-radius: 10px; margin-top: 11px; padding: 14px 11px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #e0e4ed; }
QProgressBar { color: #ffffff; background: #202630; border: 1px solid #647289;
    border-radius: 7px; text-align: center; min-height: 17px; font-size: 11px; }
QProgressBar::chunk { background: #3159a6; border-radius: 6px; }
QProgressBar[textVisible=false] { min-height: 6px; max-height: 8px; border-radius: 4px; }
QProgressBar[textVisible=false]::chunk { background: #ddbb6c; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #788296; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #9eabc2; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; }
QScrollBar::handle:horizontal { background: #788296; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenuBar { background: #191d25; color: #ced5e2; }
QMenuBar::item:selected { background: #304c88; }
QMenu { color: #f0f1f5; background: #252b36; border: 1px solid #7b8598;
    border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 23px; border-radius: 5px; }
QMenu::item:selected { color: #ffffff; background: #315ab4; }
QMenu::item:disabled { color: #a4acbc; }
QMenu::separator { height: 1px; background: #646d7f; margin: 5px; }
QToolTip { color: #f2f8fc; background: #303642; border: 1px solid #7b8598; padding: 6px; }
QStatusBar { color: #aeb8ca; background: #191d25; font-size: 11px; }
QStatusBar::item { border: none; }
"""
