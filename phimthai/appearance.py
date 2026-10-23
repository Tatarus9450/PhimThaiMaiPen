"""Native glass surfaces generated from one set of design tokens.

The lens samples only our own painted backdrop. It never captures the desktop,
and both the atmosphere and the panel material are cached between repaints.

Everything visual (palette, QSS, glass material, typography) is derived from
the tokens below, in a light "ice glass" and a dark "deep navy glass" variant.
``token_contrast_report`` composites the translucent tokens over the backdrop
extremes so the tests can prove WCAG AA for every text/surface pairing.
"""
from pathlib import Path
from string import Template

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication,
                          QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
                          QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory, QWidget


_REDUCED = "phimthaiReducedTransparency"
_THEME = "phimthaiTheme"            # requested: "auto" | "light" | "dark"
_RESOLVED = "phimthaiResolvedTheme"  # effective: "light" | "dark"
_MOTION = "phimthaiReducedMotion"
_WATCHING = "phimthaiWatchingColorScheme"

THEMES = ("auto", "light", "dark")

# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------

# Spacing scale (px). Use these for layout margins/spacing as well.
SPACE = {"xxs": 4, "xs": 8, "sm": 12, "md": 16, "lg": 24, "xl": 32}

RADIUS = {"sm": 6, "md": 10, "lg": 14, "xl": 22, "pill": 13}

# Thai first (tall stacked vowels / tone marks need its metrics), then Latin.
FONT_STACK = ("Noto Sans Thai", "IBM Plex Sans Thai", "Noto Sans", "Sarabun")

# Point sizes. Body 10.5pt (~14px at 96 dpi) keeps Thai marks legible.
TYPE = {"caption": 9.0, "small": 9.5, "body": 10.5, "editor": 12.0,
        "title": 12.0, "brand": 13.5, "heading": 19.0}

# Minimum control heights (content box, px). With the paddings in the QSS
# these give >= 40px controls, enough for above-line Thai vowels + tone marks
# and below-line vowels without clipping.
CONTROL = {"button": 24, "input": 24, "item": 22, "chip": 18}

# Colors. A value is "#rrggbb" or ("#rrggbb", alpha 0-255).
PALETTES = {
    "light": {
        # Atmosphere painted by GlassCanvas.
        "canvas": "#e6f1f8",
        "canvasStops": ("#dceffa", "#cbe5f8", "#edf7fd"),
        "canvasGlows": (("#ffffff", 205), ("#73b7ed", 118), ("#ffffff", 180), ("#90cdf7", 120)),
        "canvasDarkest": "#b4d6f0",   # deepest composited glow (contrast audit)
        "canvasBrightest": "#ffffff",
        "ribbon": "#ffffff",
        # Glass material painted by GlassPanel.
        "glassTint": "#ffffff", "glassTintEnd": "#f3faff",
        "glassAlpha": (118, 82, 130),  # frost gradient alphas; min is the audit worst case
        "glassReflection": 100, "glassShade": "#6096ba",
        "glassShadow": "#386989", "rimDark": "#8caec6", "innerShade": "#739dbb",
        "surfaceSolid": "#f5faff",    # reduced transparency
        # Text.
        "text": "#17212c", "textStrong": "#0f1923", "textSecondary": "#283e50",
        "muted": "#465b6d", "status": "#3a5468", "placeholder": "#4e6275",
        "disabledText": "#566a7a", "link": "#1f5a87",
        # Accent / focus.
        "accent": "#1f6aa0", "focus": "#1f6aa0",
        "selection": "#b9e0fb", "selectionText": "#11283a",
        "hover": "#e0f1fc",
        # Controls.
        "control": ("#ffffff", 215), "controlSolid": "#ffffff",
        "controlBorder": "#637f93", "panelBorder": "#a7c3d7",
        "buttonTop": ("#ffffff", 235), "buttonBottom": ("#ecf7ff", 205),
        "buttonText": "#1d3344", "buttonHover": "#edf8ff", "buttonPressed": "#d4e9f7",
        "disabledBg": "#e5eef5", "disabledBorder": "#b2c5d4",
        "primaryTop": "#c4e7ff", "primaryBottom": "#a9d9fa", "primaryText": "#0f2a3e",
        "primaryBorder": "#467fa8", "primaryHover": "#ccecff", "primaryPressed": "#96c9ed",
        "paste": "#d5edff", "pasteHover": "#bfe4ff", "pasteBorder": "#6c9fc4",
        "navSelected": ("#addaf9", 185), "navSelectedBorder": "#7fb6dc", "navSelectedText": "#10324a",
        "card": ("#ffffff", 165), "cardSelected": ("#e3f3ff", 235),
        "chip": "#e3f1fb", "chipText": "#1d4560", "chipBorder": "#9fc2da",
        "shortcut": ("#ffffff", 150), "shortcutText": "#1f4a68",
        "section": ("#ffffff", 150),
        "track": "#dfeaf3", "meter": "#2f8a5a", "meterHigh": "#b4313f", "progress": "#5a9dcb",
        "scroll": "#88a5ba", "scrollHover": "#607f97",
        "tooltip": "#f5faff", "menu": "#f5faff", "separator": "#b3c9d9",
        # Semantic.
        "danger": "#9b2c39", "dangerBg": ("#fff3f4", 230), "dangerBorder": "#c98a93",
        "record": "#b4313f", "recordHover": "#a12a37", "recordPressed": "#8e2430",
        "recordText": "#ffffff", "recordBorder": "#8e2430",
        "busy": "#fff1d6", "busyText": "#5f3d00", "busyBorder": "#c9a04a",
        "success": "#1a6436", "successBg": "#e5f5ea", "successBorder": "#86c19b",
        "neutralBg": "#eef3f7", "neutralBorder": "#b8c8d5",
        "beta": "#fde9c4", "betaText": "#5f3d00", "betaBorder": "#d7a94e",
        "onboarding": ("#eff8ff", 190), "onboardingBorder": "#a6c8e0",
        "arrow": "#334c61", "arrowDisabled": "#617486",
        "check": "#afdfff", "checkMark": "#152c3c", "checkBorder": "#6e8ba2",
    },
    "dark": {
        "canvas": "#0c1827",
        "canvasStops": ("#0e1d30", "#0b1626", "#11243a"),
        "canvasGlows": (("#3a77ad", 58), ("#2a6aa3", 80), ("#5a8fbf", 42), ("#1f5c8f", 78)),
        "canvasDarkest": "#0b1626",
        "canvasBrightest": "#1f4466",
        "ribbon": "#9fd2ff",
        "glassTint": "#1a2d44", "glassTintEnd": "#13233a",
        "glassAlpha": (190, 170, 205),
        "glassReflection": 20, "glassShade": "#000000",
        "glassShadow": "#000000", "rimDark": "#0a1522", "innerShade": "#000000",
        "surfaceSolid": "#15222f",
        "text": "#e7f0f7", "textStrong": "#f5f9fd", "textSecondary": "#cfdeea",
        "muted": "#b3c7d9", "status": "#b6c8d7", "placeholder": "#93a8ba",
        "disabledText": "#8396a7", "link": "#8cc8f2",
        "accent": "#7cc4f5", "focus": "#7cc4f5",
        "selection": "#2d5d86", "selectionText": "#f2f8fd",
        "hover": ("#ffffff", 22),
        "control": ("#08121e", 150), "controlSolid": "#101b27",
        "controlBorder": "#7ea0bd", "panelBorder": "#36506a",
        "buttonTop": ("#2a3f57", 220), "buttonBottom": ("#1d3046", 220),
        "buttonText": "#e2edf6", "buttonHover": "#2f4863", "buttonPressed": "#1a2b3f",
        "disabledBg": "#1a2633", "disabledBorder": "#33475b",
        "primaryTop": "#a3dbff", "primaryBottom": "#86ccfa", "primaryText": "#06203a",
        "primaryBorder": "#b9e4ff", "primaryHover": "#b4e2ff", "primaryPressed": "#72b9e8",
        "paste": "#22476a", "pasteHover": "#2a5780", "pasteBorder": "#6aa7d6",
        "navSelected": ("#4f9bd6", 70), "navSelectedBorder": "#4f88b5", "navSelectedText": "#f2f8fd",
        "card": ("#0f1f31", 150), "cardSelected": ("#1d3d5c", 225),
        "chip": "#1c3650", "chipText": "#cfe6f8", "chipBorder": "#3f6688",
        "shortcut": ("#0a1626", 140), "shortcutText": "#bfe0f7",
        "section": ("#0d1b2b", 135),
        "track": "#1b2a3a", "meter": "#4fcf8a", "meterHigh": "#ff7f8c", "progress": "#7cc4f5",
        "scroll": "#4b6580", "scrollHover": "#6d8aa3",
        "tooltip": "#15222f", "menu": "#15222f", "separator": "#33475b",
        "danger": "#ffb1b9", "dangerBg": ("#3a1720", 225), "dangerBorder": "#a24f5c",
        "record": "#c23545", "recordHover": "#b02e3d", "recordPressed": "#a52b39",
        "recordText": "#ffffff", "recordBorder": "#ff8c99",
        "busy": "#3b2e10", "busyText": "#ffd98c", "busyBorder": "#8c6d26",
        "success": "#8fe0ad", "successBg": "#123222", "successBorder": "#3c7d55",
        "neutralBg": "#1a2633", "neutralBorder": "#3b5065",
        "beta": "#3b2e10", "betaText": "#ffd98c", "betaBorder": "#8c6d26",
        "onboarding": ("#0d2238", 175), "onboardingBorder": "#36597a",
        "arrow": "#c4d6e5", "arrowDisabled": "#6f8396",
        "check": "#2d6d9e", "checkMark": "#f2f8fd", "checkBorder": "#7f9bb3",
    },
}


def _q(value):
    """Token -> QColor."""
    if isinstance(value, tuple):
        color = QColor(value[0])
        color.setAlpha(value[1])
        return color
    return QColor(value)


def _css(value):
    """Token -> QSS color literal."""
    color = _q(value)
    if color.alpha() == 255:
        return color.name()
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


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


def _app_theme():
    app = QApplication.instance()
    value = app.property(_RESOLVED) if app is not None else None
    return value if value in PALETTES else "light"


def _tokens():
    return PALETTES[_app_theme()]


# --------------------------------------------------------------------------
# Contrast helpers (WCAG 2.x relative luminance)
# --------------------------------------------------------------------------

def _linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4


def luminance(color):
    color = _q(color) if not isinstance(color, QColor) else color
    return (.2126 * _linear(color.red()) + .7152 * _linear(color.green()) +
            .0722 * _linear(color.blue()))


def contrast_ratio(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def composite(top, bottom):
    """Source-over composite of a (possibly translucent) token on an opaque color."""
    top, bottom = _q(top), _q(bottom)
    alpha = top.alphaF()
    return QColor(round(top.red() * alpha + bottom.red() * (1 - alpha)),
                  round(top.green() * alpha + bottom.green() * (1 - alpha)),
                  round(top.blue() * alpha + bottom.blue() * (1 - alpha)))


def glass_surfaces(theme, reduced=False):
    """Approximate effective opaque colors a widget can sit on, per mode.

    Glass mode uses the thinnest frost layer over both canvas extremes, plus
    the specular highlight on the bright extreme. Reduced transparency is a
    single solid surface.
    """
    tokens = PALETTES[theme]
    if reduced:
        return {"surface": QColor(tokens["surfaceSolid"])}
    alpha = min(tokens["glassAlpha"])
    bright = composite((tokens["glassTint"], alpha), tokens["canvasBrightest"])
    bright = composite(("#ffffff", tokens["glassReflection"]), bright)
    dark = composite((tokens["glassTintEnd"], alpha), tokens["canvasDarkest"])
    return {"glassBright": bright, "glassDark": dark}


# (foreground token, background token or None for the glass surface, minimum)
_TEXT_PAIRS = (
    ("text", None, 4.5), ("textStrong", None, 4.5), ("textSecondary", None, 4.5),
    ("muted", None, 4.5), ("status", None, 4.5), ("danger", None, 4.5),
    ("link", None, 4.5), ("placeholder", "control", 4.5), ("text", "control", 4.5),
    ("disabledText", "disabledBg", 4.5),
    ("buttonText", "buttonBottom", 4.5), ("buttonText", "buttonHover", 4.5),
    ("primaryText", "primaryBottom", 4.5), ("primaryText", "primaryTop", 4.5),
    ("text", "paste", 4.5), ("navSelectedText", "navSelected", 4.5),
    ("selectionText", "selection", 4.5), ("text", "cardSelected", 4.5),
    ("muted", "card", 4.5), ("muted", "section", 4.5),
    ("chipText", "chip", 4.5), ("betaText", "beta", 4.5),
    ("danger", "dangerBg", 4.5), ("recordText", "record", 4.5),
    ("recordText", "recordHover", 4.5), ("busyText", "busy", 4.5),
    ("success", "successBg", 4.5), ("muted", "neutralBg", 4.5),
    ("shortcutText", "shortcut", 4.5), ("text", "onboarding", 4.5),
    ("text", "tooltip", 4.5), ("text", "menu", 4.5),
    # Non-text UI (WCAG 1.4.11): component boundaries and focus indicators.
    ("controlBorder", None, 3.0), ("focus", None, 3.0), ("focus", "control", 3.0),
    ("primaryBorder", None, 3.0), ("recordBorder", None, 3.0), ("meter", "track", 3.0),
    ("checkBorder", "controlSolid", 3.0),
)


def token_contrast_report(theme, reduced=False):
    """Return [(fg, bg, surface, ratio, minimum)] for every audited pair.

    Translucent backgrounds are composited onto every effective glass surface
    for the given mode; the worst case is reported per pair.
    """
    tokens = PALETTES[theme]
    rows = []
    for fg, bg, minimum in _TEXT_PAIRS:
        worst = None
        for surface_name, surface in glass_surfaces(theme, reduced).items():
            backdrop = surface if bg is None else composite(tokens[bg], surface)
            ratio = contrast_ratio(composite(tokens[fg], backdrop), backdrop)
            if worst is None or ratio < worst[3]:
                worst = (fg, bg or "glass", surface_name, ratio, minimum)
        rows.append(worst)
    return rows


# --------------------------------------------------------------------------
# Typography
# --------------------------------------------------------------------------

def font_families():
    """The installed members of FONT_STACK, in preference order."""
    try:
        installed = set(QFontDatabase.families())
    except Exception:  # pragma: no cover - no font database (no app)
        installed = set()
    found = [family for family in FONT_STACK if family in installed]
    return found or ["Noto Sans"]


def _qss_font_stack():
    return ", ".join(f'"{family}"' for family in font_families()) + ", sans-serif"


def _app_font():
    font = QFont()
    font.setFamilies(font_families())
    font.setPointSizeF(TYPE["body"])
    font.setStyleHint(QFont.StyleHint.SansSerif)
    return font


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------

class _GlassStyle(QProxyStyle):
    """Keep native control behavior, with legible arrows and checked states."""

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def styleHint(self, hint, option=None, widget=None, data=None):
        if (hint == QStyle.StyleHint.SH_Widget_Animation_Duration and
                QApplication.instance() is not None and
                QApplication.instance().property(_MOTION)):
            return 0
        return super().styleHint(hint, option, widget, data)

    def drawPrimitive(self, element, option, painter, widget=None):
        tokens = _tokens()
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
            painter.setPen(QPen(_q(tokens["arrow"] if enabled else tokens["arrowDisabled"]),
                                1.6, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(QPolygonF([QPointF(-3, -1.5), QPointF(0, 1.5),
                                            QPointF(3, -1.5)]))
            painter.restore()
            return
        if element in (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                       QStyle.PrimitiveElement.PE_IndicatorRadioButton):
            radio = element == QStyle.PrimitiveElement.PE_IndicatorRadioButton
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
            checked = bool(option.state & (QStyle.StateFlag.State_On |
                                          QStyle.StateFlag.State_NoChange))
            fill = (tokens["check"] if enabled else tokens["disabledBg"]) if checked \
                else tokens["controlSolid"]
            painter.setBrush(_q(fill))
            focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
            painter.setPen(QPen(_q(tokens["focus"] if focused else tokens["checkBorder"]),
                                2 if focused else 1.2))
            if radio:
                painter.drawEllipse(rect)
            else:
                painter.drawRoundedRect(rect, 4, 4)
            if checked:
                mark = _q(tokens["checkMark"] if enabled else tokens["disabledText"])
                left, top, width, height = rect.x(), rect.y(), rect.width(), rect.height()
                if radio:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(mark)
                    painter.drawEllipse(rect.center(), width * .22, height * .22)
                else:
                    painter.setPen(QPen(mark, 2, Qt.PenStyle.SolidLine,
                                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
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
    """A light field with diffuse ribbons (ice or deep navy), drawn once per size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._backdrop = None
        self._backdrop_key = None

    def backdrop(self):
        ratio = self.devicePixelRatioF()
        reduced = bool(QApplication.instance().property(_REDUCED))
        theme = _app_theme()
        key = (self.width(), self.height(), ratio, reduced, theme)
        if key == self._backdrop_key:
            return self._backdrop
        tokens = PALETTES[theme]
        pixmap = QPixmap(max(1, round(self.width() * ratio)),
                         max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(tokens["canvas"]))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not reduced:
            base = QLinearGradient(0, 0, width, height)
            for stop, color in zip((0, .52, 1), tokens["canvasStops"]):
                base.setColorAt(stop, QColor(color))
            painter.fillRect(self.rect(), base)
            for (x, y, radius), (tint, strength) in zip(
                    ((0.02, 0.04, 0.70), (0.86, 0.08, 0.58),
                     (1.00, 0.90, 0.57), (0.18, 1.00, 0.50)),
                    tokens["canvasGlows"]):
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
                painter.setPen(QPen(_color(tokens["ribbon"], alpha), thickness))
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
        theme = _app_theme()
        tokens = PALETTES[theme]
        canvas = self._canvas()
        backdrop = canvas.backdrop() if canvas else None
        origin = self.mapTo(canvas, QPoint(0, 0)) if canvas else QPoint()
        key = (self.width(), self.height(), ratio, reduced, theme,
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
        dark = theme == "dark"
        if not reduced:
            # Offset rings stay inside the widget, avoiding heavyweight effects.
            for spread, alpha in ((5, 5), (3, 8), (1, 13)):
                shadow = rect.adjusted(-spread, -spread + 3, spread, spread + 3)
                painter.fillPath(_rounded(shadow, RADIUS["xl"] + 1 + spread),
                                 _color(tokens["glassShadow"], alpha * (3 if dark else 1)))
        path = _rounded(rect, RADIUS["xl"])
        painter.save()
        painter.setClipPath(path)
        if reduced:
            painter.fillRect(rect, QColor(tokens["surfaceSolid"]))
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
            first, middle, last = tokens["glassAlpha"]
            frost = QLinearGradient(rect.topLeft(), rect.bottomRight())
            frost.setColorAt(0, _color(tokens["glassTint"], first))
            frost.setColorAt(.36, _color(tokens["glassTint"], middle))
            frost.setColorAt(1, _color(tokens["glassTintEnd"], last))
            painter.fillRect(rect, frost)
            reflection = QRadialGradient(rect.topLeft(), max(180, rect.width() * .85))
            reflection.setColorAt(0, _color("#ffffff", tokens["glassReflection"]))
            reflection.setColorAt(.42, _color("#ffffff", tokens["glassReflection"] // 5))
            reflection.setColorAt(1, _color("#ffffff", 0))
            painter.fillRect(rect, reflection)
            shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            shade.setColorAt(0, _color("#ffffff", 4 if dark else 12))
            shade.setColorAt(.80, _color(tokens["glassShade"], 0))
            shade.setColorAt(1, _color(tokens["glassShade"], 30 if dark else 13))
            painter.fillRect(rect, shade)
        painter.restore()
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if dark:
            rim.setColorAt(0, _color("#cfe9ff", 120 if not reduced else 70))
            rim.setColorAt(.28, _color("#9fc8ec", 55))
            rim.setColorAt(.70, _color(tokens["rimDark"], 120))
            rim.setColorAt(1, _color("#9fc8ec", 70))
        else:
            rim.setColorAt(0, _color("#ffffff", 240 if not reduced else 180))
            rim.setColorAt(.28, _color("#ffffff", 155))
            rim.setColorAt(.70, _color(tokens["rimDark"], 62))
            rim.setColorAt(1, _color("#ffffff", 180))
        painter.setPen(QPen(rim, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if not reduced:
            inset = rect.adjusted(1.2, 1.2, -1.2, -1.2)
            inner = QLinearGradient(inset.topLeft(), inset.bottomLeft())
            inner.setColorAt(0, _color("#ffffff", 40 if dark else 115))
            inner.setColorAt(.16, _color("#ffffff", 0))
            inner.setColorAt(1, _color(tokens["innerShade"], 60 if dark else 31))
            painter.setPen(QPen(inner, .8))
            painter.drawPath(_rounded(inset, RADIUS["xl"] - 1))
        painter.end()
        self._material_key, self._material = key, pixmap
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._surface())


# --------------------------------------------------------------------------
# Theme selection
# --------------------------------------------------------------------------

def _system_scheme():
    """Desktop color scheme via Qt 6.5+ style hints; Unknown if unavailable."""
    try:
        return QGuiApplication.styleHints().colorScheme()
    except Exception:  # pragma: no cover - very old Qt / no app
        return Qt.ColorScheme.Unknown


def resolve_theme(theme="auto"):
    """Map "auto" | "light" | "dark" to the effective "light" | "dark"."""
    if theme not in THEMES:
        raise ValueError(f"theme must be one of {THEMES}, not {theme!r}")
    if theme == "auto":
        return "dark" if _system_scheme() == Qt.ColorScheme.Dark else "light"
    return theme


def current_theme(app=None):
    """The effective theme ("light" / "dark") last applied to ``app``."""
    app = app or QApplication.instance()
    value = app.property(_RESOLVED) if app is not None else None
    return value if value in PALETTES else "light"


def _on_scheme_changed(*_):
    app = QApplication.instance()
    if app is not None and (app.property(_THEME) or "auto") == "auto":
        if resolve_theme("auto") != current_theme(app):
            apply_style(app)


def _palette(tokens):
    palette = QPalette()
    colors = {
        "Window": tokens["canvas"], "WindowText": tokens["text"],
        "Base": tokens["controlSolid"], "AlternateBase": tokens["surfaceSolid"],
        "Text": tokens["text"], "Button": tokens["surfaceSolid"],
        "ButtonText": tokens["buttonText"], "BrightText": "#ffffff",
        "ToolTipBase": tokens["tooltip"], "ToolTipText": tokens["text"],
        "PlaceholderText": tokens["placeholder"], "Highlight": tokens["selection"],
        "HighlightedText": tokens["selectionText"], "Light": tokens["controlSolid"],
        "Midlight": tokens["neutralBg"], "Mid": tokens["controlBorder"],
        "Dark": tokens["scrollHover"], "Shadow": tokens["glassShadow"],
        "Link": tokens["link"], "LinkVisited": tokens["link"], "Accent": tokens["accent"],
    }
    disabled = {"WindowText": tokens["disabledText"], "Text": tokens["disabledText"],
                "ButtonText": tokens["disabledText"], "Button": tokens["disabledBg"],
                "Highlight": tokens["neutralBg"], "HighlightedText": tokens["disabledText"],
                "PlaceholderText": tokens["disabledText"]}
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, color in colors.items():
            if group == QPalette.ColorGroup.Disabled:
                color = disabled.get(role, color)
            palette.setColor(group, getattr(QPalette.ColorRole, role), _q(color))
    return palette


def apply_style(app, reduced_transparency=False, theme=None, reduced_motion=None):
    """Apply the glass theme, independent of KDE/GNOME's current palette.

    theme: "auto" (follow the desktop light/dark scheme, live), "light" or
        "dark". None keeps the previously requested theme ("auto" initially),
        so existing ``apply_style(app, reduced_transparency=...)`` calls do not
        reset a user's choice.
    reduced_motion: disable Qt UI animations (combo/menu/tooltip fades and
        style animations). None keeps the previous value (False initially).
    """
    if theme is None:
        theme = app.property(_THEME) or "auto"
    resolved = resolve_theme(theme)
    if reduced_motion is None:
        reduced_motion = bool(app.property(_MOTION))
    app.setProperty(_THEME, theme)
    app.setProperty(_RESOLVED, resolved)
    app.setProperty(_REDUCED, bool(reduced_transparency))
    app.setProperty(_MOTION, bool(reduced_motion))
    tokens = PALETTES[resolved]
    for effect in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu,
                   Qt.UIEffect.UI_AnimateCombo, Qt.UIEffect.UI_AnimateTooltip,
                   Qt.UIEffect.UI_FadeTooltip, Qt.UIEffect.UI_AnimateToolBox):
        app.setEffectEnabled(effect, not reduced_motion)
    if not app.property(_WATCHING):
        try:
            app.styleHints().colorSchemeChanged.connect(_on_scheme_changed)
            app.setProperty(_WATCHING, True)
        except (AttributeError, RuntimeError):  # pragma: no cover - Qt < 6.5
            pass
    # Re-styling repolishes every widget; skip it when nothing changed.
    sheet = build_stylesheet(resolved, bool(reduced_transparency))
    if app.styleSheet() == sheet and isinstance(app.style(), _GlassStyle):
        return
    app.setStyle(_GlassStyle())
    app.setFont(_app_font())
    # standardPalette() follows the system color scheme on native Wayland.
    # Explicit entries survive subsequent Qt system palette/theme updates.
    app.setPalette(_palette(tokens))
    app.setStyleSheet(sheet)
    for widget in app.allWidgets():
        if isinstance(widget, (GlassCanvas, GlassPanel)):
            widget.update()


# --------------------------------------------------------------------------
# Stylesheet
# --------------------------------------------------------------------------

def build_stylesheet(theme="light", reduced=False):
    """Render the QSS for a resolved theme from the tokens."""
    tokens = dict(PALETTES[theme])
    if reduced:
        # Solid surfaces: translucent fills become opaque over the solid panel.
        for name, value in list(tokens.items()):
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], int) \
                    and isinstance(value[0], str):
                tokens[name] = composite(value, tokens["surfaceSolid"]).name()
    values = {name: _css(value) for name, value in tokens.items()
              if isinstance(value, str) or (isinstance(value, tuple) and len(value) == 2
                                             and isinstance(value[0], str)
                                             and isinstance(value[1], int))}
    values.update({f"s{size}": f"{size}px" for size in SPACE.values()})
    values.update({f"r_{name}": f"{size}px" for name, size in RADIUS.items()})
    values.update({f"t_{name}": f"{size}pt" for name, size in TYPE.items()})
    values.update({f"h_{name}": f"{size}px" for name, size in CONTROL.items()})
    values["fonts"] = _qss_font_stack()
    suffix = "-dark" if theme == "dark" else ""
    values["down"] = _asset_url(f"glass-chevron-down{suffix}.svg")
    values["up"] = _asset_url(f"glass-chevron-up{suffix}.svg")
    return Template(_STYLESHEET).substitute(values)


# Focus: QSS has no outline; a 2px accent border with 1px less padding keeps
# geometry stable between focused and unfocused states.
_STYLESHEET = """
QWidget { color: $text; font-family: $fonts; font-size: $t_body; }
QMainWindow, QDialog { background: $canvas; }
QWidget#canvas, QWidget#sidebar, QWidget#workspace, QWidget#page, QWidget#modelsPage,
QWidget#settingsPage, QWidget#diagnosticsPage, QWidget#wizardSteps, QWidget#advancedBody,
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea { border: none; }
QLabel { background: transparent; border: none; }
QLabel#brand { color: $textStrong; font-size: $t_brand; font-weight: 700; }
QLabel#heading { color: $textStrong; font-size: $t_heading; font-weight: 600; padding: 2px 0; }
QLabel#muted, QLabel#technicalInfo { color: $muted; }
QLabel#section, QLabel#sectionTitle { color: $textSecondary; font-size: $t_body; font-weight: 700;
    padding: 2px 0; }
QLabel#modelName { color: $textStrong; font-weight: 700; }
QLabel#modelStatus { color: $status; }
QLabel#shortcut { color: $shortcutText; background: $shortcut;
    border: 1px solid $panelBorder; border-radius: $r_md; padding: 6px $s12; }
QLabel#status { color: $status; padding: 2px 0; }
QLabel#recording { color: $danger; }
QLabel#savedIndicator { color: $success; font-size: $t_small; padding: 2px $s8; }
QLabel#pageMessage { color: $text; background: $neutralBg; border: 1px solid $neutralBorder;
    border-radius: $r_md; padding: $s8 $s12; }
QLabel#pageMessage[error=true] { color: $danger; background: $dangerBg; border-color: $dangerBorder; }
QWidget#onboarding { background: $onboarding; border: 1px solid $onboardingBorder; border-radius: $r_lg; }
QLabel#setupMessage { color: $textSecondary; }
QLabel#betaWarning { color: $danger; background: $dangerBg;
    border: 1px solid $dangerBorder; border-radius: $r_md; padding: $s8 $s12; }
QLabel#chip { color: $chipText; background: $chip; border: 1px solid $chipBorder;
    border-radius: $r_pill; padding: 3px $s8; min-height: $h_chip; font-size: $t_small; }
QLabel#betaBadge { color: $betaText; background: $beta; border: 1px solid $betaBorder;
    border-radius: $r_pill; padding: 3px $s8; min-height: $h_chip; font-size: $t_small; font-weight: 600; }

QFrame#modelCard { background: $card; border: 1px solid $panelBorder; border-radius: $r_lg; }
QFrame#modelCard:hover { border-color: $controlBorder; }
QFrame#modelCard[selected=true] { background: $cardSelected; border: 2px solid $accent; }
QFrame#settingsSection { background: $section; border: 1px solid $panelBorder; border-radius: $r_lg; }
QWidget#setupWizard { background: transparent; }
QLabel#stepIndicator { color: $accent; font-size: $t_small; font-weight: 700; padding: 2px 0; }
QWidget#stepIndicator { background: transparent; }

QWidget#checkRow, QLabel#checkRow { background: $neutralBg; border: 1px solid $neutralBorder;
    border-radius: $r_md; padding: $s8 $s12; color: $muted; }
QWidget#checkRow[state="ok"], QLabel#checkRow[state="ok"] { background: $successBg;
    border-color: $successBorder; color: $success; }
QWidget#checkRow[state="fail"], QLabel#checkRow[state="fail"] { background: $dangerBg;
    border-color: $dangerBorder; color: $danger; }
QWidget#checkRow[state="unknown"], QLabel#checkRow[state="unknown"] { background: $neutralBg;
    border-color: $neutralBorder; color: $muted; }
QWidget#checkRow QLabel { background: transparent; border: none; padding: 0; color: $text; }
QWidget#checkRow QLabel#checkDetail { color: $muted; }
QLabel#checkTitle { color: $textStrong; font-weight: 600; }
QLabel#checkDetail { color: $muted; }
QLabel#checkIcon { font-weight: 700; min-width: 22px; qproperty-alignment: AlignCenter; }
QLabel#checkIcon[state="ok"], QWidget#checkRow QLabel#checkIcon[state="ok"] { color: $success; }
QLabel#checkIcon[state="fail"], QWidget#checkRow QLabel#checkIcon[state="fail"] { color: $danger; }
QLabel#checkIcon[state="unknown"], QWidget#checkRow QLabel#checkIcon[state="unknown"] { color: $muted; }
QLabel#diagnosticSummary { color: $textStrong; font-size: $t_title; font-weight: 600; padding: 2px 0; }
QPlainTextEdit#diagnosticsRaw, QTextEdit#diagnosticsRaw { font-family: "Noto Sans Mono", monospace;
    font-size: $t_small; }

QLabel#fieldLabel { color: $textSecondary; font-weight: 600; padding: 2px 0; }
QLabel#fieldError { color: $danger; font-size: $t_small; padding: 2px 0; }
QLabel#shortcutStatus { color: $muted; padding: 2px 0; }
QLabel#shortcutStatus[ok=true], QLabel#shortcutStatus[ok="true"] { color: $success; }
QLabel#shortcutStatus[ok=false], QLabel#shortcutStatus[ok="false"] { color: $danger; }
QPushButton#sectionToggle, QToolButton#sectionToggle { color: $textSecondary; background: transparent;
    border: 2px solid transparent; font-weight: 700; text-align: left; padding: 6px $s8; }
QPushButton#sectionToggle:hover, QToolButton#sectionToggle:hover { background: $hover; }
QPushButton#sectionToggle:focus, QToolButton#sectionToggle:focus { border: 2px solid $focus; }
QKeySequenceEdit#hotkeyEdit QLineEdit { font-weight: 600; }
QPlainTextEdit#dictionary, QTextEdit#dictionary { font-size: $t_body; }

QWidget#wizardStep { background: transparent; }
QLabel#wizardTitle { color: $textStrong; font-size: $t_heading; font-weight: 600; padding: 2px 0; }
QLabel#stepStatus { color: $status; padding: 2px 0; }
QLabel#tryInstructions { color: $textSecondary; padding: 2px 0; }
QLabel#stepItem { color: $muted; background: transparent; border: 1px solid $neutralBorder;
    border-radius: $r_pill; padding: 3px $s12; min-height: $h_chip; font-size: $t_small; }
QLabel#stepItem[state="current"] { color: $primaryText; background: $primaryBottom;
    border-color: $primaryBorder; font-weight: 700; }
QLabel#stepItem[state="done"] { color: $success; background: $successBg; border-color: $successBorder; }
QLabel#stepItem[state="todo"] { color: $muted; background: $neutralBg; border-color: $neutralBorder; }
QPushButton#wizardSkip { color: $link; background: transparent; border: 2px solid transparent; }
QPushButton#wizardSkip:hover { background: $hover; }
QPushButton#wizardSkip:focus { border: 2px solid $focus; }

QListWidget { background: $control; border: 1px solid $controlBorder;
    border-radius: $r_lg; padding: 5px; outline: none; }
QListWidget::item { color: $text; padding: $s12; min-height: $h_item; border-radius: $r_md;
    border: 2px solid transparent; }
QListWidget::item:hover { background: $hover; }
QListWidget::item:selected { color: $selectionText; background: $selection; }
QListWidget::item:focus { border: 2px solid $focus; }
QListWidget#navigation { background: transparent; border: none; padding: 0; }
QListWidget#navigation::item { margin: 3px 0; padding: $s12 $s8; border: 2px solid transparent; }
QListWidget#navigation::item:selected { background: $navSelected; border: 2px solid $navSelectedBorder;
    color: $navSelectedText; }
QListWidget#navigation::item:focus { border: 2px solid $focus; }

QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit QLineEdit {
    background: $control; color: $text; border: 1px solid $controlBorder;
    border-radius: $r_md; padding: 7px 11px; selection-background-color: $selection;
    selection-color: $selectionText; placeholder-text-color: $placeholder;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: $h_input; }
QPlainTextEdit#editor, QPlainTextEdit#tryField, QLineEdit#tryField, QTextEdit#tryField {
    background: $control; color: $text; border-radius: $r_lg;
    border: 1px solid $controlBorder; padding: $s16; font-size: $t_editor;
    placeholder-text-color: $placeholder; selection-background-color: $selection;
    selection-color: $selectionText; }
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QKeySequenceEdit QLineEdit:focus {
    border: 2px solid $focus; padding: 6px 10px; }
QPlainTextEdit#editor:focus, QPlainTextEdit#tryField:focus, QLineEdit#tryField:focus,
QTextEdit#tryField:focus { border: 2px solid $focus; padding: 15px; }
QKeySequenceEdit { background: transparent; }
QComboBox { padding-right: 30px; }
QComboBox:focus { padding-right: 29px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: none; border-top-right-radius: 7px;
    border-bottom-right-radius: 7px; background: transparent; }
QComboBox::down-arrow { image: $down; width: 16px; height: 16px; }
QComboBox QAbstractItemView { background: $menu; color: $text;
    selection-background-color: $selection; selection-color: $selectionText;
    border: 1px solid $controlBorder; padding: 5px; outline: none; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 4px $s8; }
QSpinBox, QDoubleSpinBox { padding-right: 32px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border;
    subcontrol-position: top right; width: 29px; height: 19px; border: none;
    border-top-right-radius: 7px; background: transparent; margin: 1px 1px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border;
    subcontrol-position: bottom right; width: 29px; height: 19px; border: none;
    border-bottom-right-radius: 7px; background: transparent; margin: 0 1px 1px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: $up; width: 14px; height: 14px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: $down; width: 14px; height: 14px; }

QPushButton, QToolButton { color: $buttonText; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 $buttonTop, stop:1 $buttonBottom);
    border: 1px solid $controlBorder; border-radius: $r_md;
    padding: 7px $s16; min-height: $h_button; font-weight: 500; }
QToolButton { padding: 7px $s8; }
QPushButton:hover, QToolButton:hover { background: $buttonHover; border-color: $accent; }
QPushButton:pressed, QToolButton:pressed { background: $buttonPressed; }
QPushButton:focus, QToolButton:focus { border: 2px solid $focus; padding: 6px 15px; }
QToolButton:focus { padding: 6px 7px; }
QToolButton::menu-indicator { image: none; width: 0; }
QPushButton[primary=true] { color: $primaryText; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 $primaryTop, stop:1 $primaryBottom);
    border: 1px solid $primaryBorder; font-weight: 700; }
QPushButton[primary=true]:hover { background: $primaryHover; border-color: $accent; }
QPushButton[primary=true]:pressed { background: $primaryPressed; }
QPushButton[primary=true]:focus { border: 2px solid $focus; }
QPushButton#recordControl { font-size: $t_title; font-weight: 700; min-height: 28px; padding: 8px $s24; }
QPushButton#recordControl:focus { padding: 7px 23px; }
QPushButton#recordControl[state="recording"] { color: $recordText; background: $record;
    border: 1px solid $recordBorder; }
QPushButton#recordControl[state="recording"]:hover { background: $recordHover; }
QPushButton#recordControl[state="recording"]:pressed { background: $recordPressed; }
QPushButton#recordControl[state="recording"]:focus { border: 2px solid $focus; }
QPushButton#recordControl[state="processing"] { color: $busyText; background: $busy;
    border: 1px solid $busyBorder; }
QPushButton#recordControl[state="processing"]:focus { border: 2px solid $focus; }
QPushButton#modeSwitch { color: $shortcutText; background: $shortcut; border-color: $controlBorder; }
QPushButton#modeSwitch:hover { background: $buttonHover; border-color: $accent; }
QPushButton#modeSwitch:pressed { background: $buttonPressed; }
QPushButton#modeSwitch:focus { border: 2px solid $focus; }
QPushButton#pasteAction { color: $text; background: $paste; border-color: $pasteBorder; }
QPushButton#pasteAction:hover { background: $pasteHover; }
QPushButton#pasteAction:pressed { background: $primaryPressed; }
QPushButton#pasteAction:focus { border: 2px solid $focus; }
QToolButton#cardMenu { min-width: 22px; font-size: $t_title; }
QPushButton:disabled, QPushButton[primary=true]:disabled, QToolButton:disabled { color: $disabledText;
    background: $disabledBg; border-color: $disabledBorder; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QPlainTextEdit:disabled { color: $disabledText;
    background: $disabledBg; border-color: $disabledBorder; }

QCheckBox, QRadioButton { color: $text; spacing: 10px; background: transparent;
    border: 2px solid transparent; border-radius: $r_sm; padding: 4px 6px; min-height: $h_item; }
QCheckBox:focus, QRadioButton:focus { border: 2px solid $focus; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabledText; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px; }

QGroupBox { background: $section; border: 1px solid $panelBorder;
    border-radius: $r_md; margin-top: 14px; padding: $s16 $s12 $s12; }
QGroupBox::title { subcontrol-origin: margin; left: $s12; padding: 0 5px; color: $textSecondary; }
QProgressBar { color: $text; background: $track; border: 1px solid $controlBorder;
    border-radius: 7px; text-align: center; min-height: 18px; font-size: $t_caption; }
QProgressBar::chunk { background: $primaryBottom; border-radius: 6px; }
QProgressBar[textVisible=false] { min-height: 6px; max-height: 8px; border-radius: 4px; }
QProgressBar[textVisible=false]::chunk { background: $progress; border-radius: 3px; }
QProgressBar#micLevel { background: $track; border: 1px solid $controlBorder; border-radius: 5px;
    min-height: 10px; max-height: 10px; }
QProgressBar#micLevel::chunk { border-radius: 4px; background: $meter; }
QProgressBar#micLevel[level="high"]::chunk { background: $meterHigh; }
QProgressBar#modelProgress { min-height: 8px; max-height: 8px; border-radius: 4px; }
QProgressBar#modelProgress::chunk { background: $progress; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: $scroll; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: $scrollHover; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; }
QScrollBar::handle:horizontal { background: $scroll; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenuBar { background: $canvas; color: $text; }
QMenuBar::item:selected { background: $selection; color: $selectionText; }
QMenu { color: $text; background: $menu; border: 1px solid $controlBorder;
    border-radius: $r_sm; padding: 6px; }
QMenu::item { padding: $s8 $s24; border-radius: 5px; }
QMenu::item:selected { color: $selectionText; background: $selection; }
QMenu::item:disabled { color: $disabledText; }
QMenu::separator { height: 1px; background: $separator; margin: 5px; }
QToolTip { color: $text; background: $tooltip; border: 1px solid $controlBorder; padding: 6px; }
QStatusBar { color: $muted; background: $canvas; font-size: $t_caption; }
QStatusBar::item { border: none; }
"""
