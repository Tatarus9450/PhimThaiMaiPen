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
            painter.setPen(QPen(QColor("#334c61" if enabled else "#617486"),
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
            painter.setBrush(QColor(("#afdfff" if enabled else "#d6e4ee")
                                    if checked else "#f8fcff"))
            focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
            painter.setPen(QPen(QColor("#276f9f" if focused else "#6e8ba2"),
                                1.8 if focused else 1))
            painter.drawRoundedRect(rect, 4, 4)
            if checked:
                painter.setPen(QPen(QColor("#152c3c"), 2, Qt.PenStyle.SolidLine,
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
    """A pale blue light field with diffuse ribbons, drawn once per size."""

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
        pixmap.fill(QColor("#e6f1f8"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not reduced:
            base = QLinearGradient(0, 0, width, height)
            base.setColorAt(0, QColor("#dceffa"))
            base.setColorAt(0.52, QColor("#cbe5f8"))
            base.setColorAt(1, QColor("#edf7fd"))
            painter.fillRect(self.rect(), base)
            for x, y, radius, tint, strength in (
                (0.02, 0.04, 0.70, "#ffffff", 205),
                (0.86, 0.08, 0.58, "#73b7ed", 118),
                (1.00, 0.90, 0.57, "#ffffff", 180),
                (0.18, 1.00, 0.50, "#90cdf7", 120),
            ):
                glow = QRadialGradient(width * x, height * y,
                                       max(width, height) * radius)
                glow.setColorAt(0, _color(tint, strength))
                glow.setColorAt(0.42, _color(tint, strength // 3))
                glow.setColorAt(1, _color(tint, 0))
                painter.fillRect(self.rect(), glow)
            # Broad light ribbons remain visible through the frosted lenses.
            ribbon = QPainterPath()
            ribbon.moveTo(width * 0.18, -height * 0.1)
            ribbon.cubicTo(width * 0.95, height * 0.10, width * 0.26,
                           height * 0.63, width * 1.15, height * 0.90)
            for thickness, alpha in ((150, 9), (110, 14), (72, 19), (38, 16)):
                painter.setPen(QPen(_color("#ffffff", alpha), thickness))
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
            for spread, alpha in ((5, 5), (3, 8), (1, 13)):
                shadow = rect.adjusted(-spread, -spread + 3, spread, spread + 3)
                painter.fillPath(_rounded(shadow, 23 + spread), _color("#386989", alpha))
        path = _rounded(rect, 22)
        painter.save()
        painter.setClipPath(path)
        if reduced:
            painter.fillRect(rect, QColor("#f5faff"))
        else:
            if backdrop:
                # A slight magnification bends the diffuse light across the rim.
                source = QRectF(origin.x() + rect.x(), origin.y() + rect.y(),
                                rect.width(), rect.height())
                source.adjust(source.width() * .018, source.height() * .018,
                              -source.width() * .018, -source.height() * .018)
                source = QRectF(source.x() * ratio, source.y() * ratio,
                                source.width() * ratio, source.height() * ratio)
                painter.drawPixmap(rect, backdrop, source)
            frost = QLinearGradient(rect.topLeft(), rect.bottomRight())
            frost.setColorAt(0, _color("#ffffff", 118))
            frost.setColorAt(.36, _color("#ffffff", 82))
            frost.setColorAt(1, _color("#f3faff", 130))
            painter.fillRect(rect, frost)
            reflection = QRadialGradient(rect.topLeft(), max(180, rect.width() * .85))
            reflection.setColorAt(0, _color("#ffffff", 100))
            reflection.setColorAt(.42, _color("#ffffff", 20))
            reflection.setColorAt(1, _color("#ffffff", 0))
            painter.fillRect(rect, reflection)
            shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            shade.setColorAt(0, _color("#ffffff", 12))
            shade.setColorAt(.80, _color("#6096ba", 0))
            shade.setColorAt(1, _color("#6096ba", 13))
            painter.fillRect(rect, shade)
        painter.restore()
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, _color("#ffffff", 240 if not reduced else 180))
        rim.setColorAt(.28, _color("#ffffff", 155))
        rim.setColorAt(.70, _color("#8caec6", 62))
        rim.setColorAt(1, _color("#ffffff", 180))
        painter.setPen(QPen(rim, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if not reduced:
            inset = rect.adjusted(1.2, 1.2, -1.2, -1.2)
            inner = QLinearGradient(inset.topLeft(), inset.bottomLeft())
            inner.setColorAt(0, _color("#ffffff", 115))
            inner.setColorAt(.16, _color("#ffffff", 0))
            inner.setColorAt(1, _color("#739dbb", 31))
            painter.setPen(QPen(inner, .8))
            painter.drawPath(_rounded(inset, 21))
        painter.end()
        self._material_key, self._material = key, pixmap
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._surface())


def apply_style(app, reduced_transparency=False):
    """Apply light blue glass, independent of KDE/GNOME's current palette."""
    app.setProperty(_REDUCED, bool(reduced_transparency))
    app.setStyle(_GlassStyle())
    palette = QPalette()
    colors = {
        "Window": "#e6f1f8", "WindowText": "#17212c", "Base": "#f8fcff",
        "AlternateBase": "#edf5fb", "Text": "#17212c", "Button": "#edf6fc",
        "ButtonText": "#17212c", "BrightText": "#ffffff", "ToolTipBase": "#f5faff",
        "ToolTipText": "#233849", "PlaceholderText": "#526678", "Highlight": "#b9e0fb",
        "HighlightedText": "#172b3b", "Light": "#ffffff", "Midlight": "#e2eef7",
        "Mid": "#a2bbce", "Dark": "#7191a9", "Shadow": "#57788e",
        "Link": "#245f8c", "LinkVisited": "#425f80", "Accent": "#a9d9fa",
    }
    disabled = {"WindowText": "#596c7c", "Text": "#596c7c", "ButtonText": "#596c7c",
                "Button": "#e5eef5", "Highlight": "#d5e7f4", "HighlightedText": "#526678",
                "PlaceholderText": "#596c7c"}
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
QWidget { color: #17212c; font-size: 13px; }
QMainWindow, QDialog { background: #e6f1f8; }
QWidget#canvas, QWidget#sidebar, QWidget#workspace, QWidget#page,
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { background: transparent; border: none; }
QLabel#brand { color: #121c26; font-size: 18px; font-weight: 700; }
QLabel#heading { color: #121c26; font-size: 26px; font-weight: 600; }
QLabel#muted { color: #4b6072; }
QLabel#section { color: #283e50; font-size: 13px; font-weight: 600; }
QLabel#shortcut { color: #264d69; background: rgba(255, 255, 255, 145);
    border: 1px solid rgba(255, 255, 255, 230); border-radius: 9px; padding: 6px 10px; }
QLabel#status { color: #3e586d; padding: 2px 0; }
QLabel#recording { color: #9b2c39; }
QWidget#onboarding { background: rgba(239, 248, 255, 188); border: 1px solid #accde4; border-radius: 14px; }
QLabel#setupMessage { color: #294b64; }
QLabel#betaWarning { color: #9b2c39; background: rgba(255, 243, 244, 222);
    border: 1px solid #d9a9b0; border-radius: 10px; padding: 9px 11px; }
QListWidget { background: rgba(255, 255, 255, 180); border: 1px solid #9db9ce;
    border-radius: 12px; padding: 5px; outline: none; }
QListWidget::item { color: #273c4e; padding: 12px; border-radius: 9px; }
QListWidget::item:hover { background: #e0f1fc; }
QListWidget::item:selected { color: #142b3c; background: #bde2fc; }
QListWidget#navigation { background: transparent; border: none; padding: 0; }
QListWidget#navigation::item { margin: 3px 0; padding: 13px 10px; border: 1px solid transparent; }
QListWidget#navigation::item:selected { background: rgba(173, 218, 249, 175); border: 1px solid #9ac9e8; color: #16354b; }
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: rgba(255, 255, 255, 210); color: #17212c; border: 1px solid #8eaabe;
    border-radius: 10px; padding: 7px 10px; selection-background-color: #b9e0fb;
    selection-color: #172b3b; placeholder-text-color: #526678;
}
QPlainTextEdit#editor { background: rgba(255, 255, 255, 203); color: #17212c; border-radius: 14px;
    border: 1px solid #a0bed3; padding: 16px; font-size: 16px;
    placeholder-text-color: #526678; selection-background-color: #b9e0fb; selection-color: #172b3b; }
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit#editor:focus { border: 1px solid #276f9f; }
QComboBox { padding-right: 29px; min-height: 20px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: none; border-top-right-radius: 7px;
    border-bottom-right-radius: 7px; background: transparent; }
QComboBox::down-arrow { image: @DOWN_ARROW@; width: 16px; height: 16px; }
QComboBox QAbstractItemView { background: #f8fcff; color: #17212c;
    selection-background-color: #b9e0fb; selection-color: #172b3b;
    border: 1px solid #8eaabe; padding: 5px; outline: none; }
QSpinBox { padding-right: 32px; min-height: 20px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 29px; height: 19px; border: none; border-top-right-radius: 7px;
    background: transparent; margin: 1px 1px 0 0; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 29px; height: 19px; border: none; border-bottom-right-radius: 7px;
    background: transparent; margin: 0 1px 1px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #c8e7fb; }
QSpinBox::up-arrow { image: @UP_ARROW@; width: 14px; height: 14px; }
QSpinBox::down-arrow { image: @DOWN_ARROW@; width: 14px; height: 14px; }
QPushButton { color: #23394a; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 rgba(255,255,255,230), stop:1 rgba(236,247,255,195));
    border: 1px solid #96b3c8; border-radius: 11px;
    padding: 8px 13px; min-height: 18px; font-weight: 500; }
QPushButton:hover { background: #edf8ff; border-color: #6498bd; }
QPushButton:pressed { background: #d4e9f7; }
QPushButton:focus { border: 2px solid #276f9f; padding: 7px 12px; }
QPushButton[primary=true] { color: #142e42; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #c4e7ff, stop:1 #a9d9fa);
    border: 1px solid #73afd7; font-weight: 700; }
QPushButton[primary=true]:hover { background: #ccecff; border-color: #518cb4; }
QPushButton[primary=true]:pressed { background: #96c9ed; }
QPushButton#recordControl { font-size: 15px; }
QPushButton#modeSwitch { color: #264d69; background: rgba(255, 255, 255, 158); border-color: #a1c3db; }
QPushButton#modeSwitch:hover { background: #e4f4ff; border-color: #79aacc; }
QPushButton#modeSwitch:pressed { background: #cde5f6; }
QPushButton#pasteAction { color: #17384f; background: #d5edff; border-color: #93bedc; }
QPushButton#pasteAction:hover { background: #bfe4ff; }
QPushButton#pasteAction:pressed { background: #afd8f5; }
QPushButton:disabled, QPushButton[primary=true]:disabled { color: #596c7c;
    background: #e5eef5; border-color: #b2c5d4; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #596c7c;
    background: #e5eef5; border-color: #b2c5d4; }
QCheckBox { color: #273c4e; spacing: 9px; background: transparent; }
QCheckBox:disabled { color: #596c7c; }
QCheckBox::indicator { width: 18px; height: 18px; }
QGroupBox { background: rgba(255, 255, 255, 175); border: 1px solid #9db9ce;
    border-radius: 10px; margin-top: 11px; padding: 14px 11px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #273c4e; }
QProgressBar { color: #17384f; background: #edf5fb; border: 1px solid #9bb9cf;
    border-radius: 7px; text-align: center; min-height: 17px; font-size: 11px; }
QProgressBar::chunk { background: #a9d9fa; border-radius: 6px; }
QProgressBar[textVisible=false] { min-height: 6px; max-height: 8px; border-radius: 4px; }
QProgressBar[textVisible=false]::chunk { background: #5a9dcb; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #88a5ba; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #607f97; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; }
QScrollBar::handle:horizontal { background: #88a5ba; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenuBar { background: #e6f1f8; color: #273c4e; }
QMenuBar::item:selected { background: #bde2fc; }
QMenu { color: #17212c; background: #f5faff; border: 1px solid #8eaabe;
    border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 23px; border-radius: 5px; }
QMenu::item:selected { color: #172b3b; background: #b9e0fb; }
QMenu::item:disabled { color: #596c7c; }
QMenu::separator { height: 1px; background: #b3c9d9; margin: 5px; }
QToolTip { color: #233849; background: #f5faff; border: 1px solid #8eaabe; padding: 6px; }
QStatusBar { color: #526678; background: #e6f1f8; font-size: 11px; }
QStatusBar::item { border: none; }
"""
