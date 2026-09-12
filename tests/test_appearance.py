"""Native painting regressions; no microphone, desktop or app singleton."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QStackedWidget

from phimthai.appearance import GlassCanvas, GlassPanel, apply_style


APP = QApplication.instance() or QApplication([])
LINEAR = tuple(value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
               for value in (index / 255 for index in range(256)))


def luminance(color):
    return (.2126 * LINEAR[color.red()] + .7152 * LINEAR[color.green()] +
            .0722 * LINEAR[color.blue()])


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def brightest_body_pixel(image, margin=28):
    """Scan every physical pixel in the text-safe interior, excluding the rim."""
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    pixels = memoryview(image.constBits()).cast("I")
    stride = image.bytesPerLine() // 4
    inset = round(margin * image.devicePixelRatio())
    brightest, result = -1., QColor()
    for y in range(inset, image.height() - inset):
        for pixel in pixels[y * stride + inset:y * stride + image.width() - inset]:
            value = (.2126 * LINEAR[(pixel >> 16) & 255] +
                     .7152 * LINEAR[(pixel >> 8) & 255] + .0722 * LINEAR[pixel & 255])
            if value > brightest:
                brightest, result = value, QColor.fromRgb(pixel)
    return result


def rendered_text_contrast(empty, with_text):
    """Compare core glyph pixels to the exact backdrop under those pixels.

    Antialiased edge pixels intentionally blend into the background; the peak
    measures the actual painted text color, including any unintended Qt alpha.
    """
    empty = empty.convertToFormat(QImage.Format.Format_RGB32)
    with_text = with_text.convertToFormat(QImage.Format.Format_RGB32)
    before = memoryview(empty.constBits()).cast("I")
    after = memoryview(with_text.constBits()).cast("I")
    ratios = [contrast(QColor.fromRgb(old), QColor.fromRgb(new))
              for old, new in zip(before, after) if old != new]
    return max(ratios, default=1.)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        apply_style(APP)
        self.canvas = GlassCanvas()
        self.canvas.resize(820, 600)
        self.panel = GlassPanel(self.canvas)
        self.panel.setObjectName("workspace")
        self.panel.setGeometry(18, 18, 784, 550)
        self.canvas.show()
        APP.processEvents()

    def tearDown(self):
        self.canvas.close()
        self.canvas.deleteLater()
        APP.processEvents()
        APP.styleHints().setColorScheme(Qt.ColorScheme.Unknown)

    def test_palette_survives_light_dark_changes_after_launch(self):
        roles = (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.PlaceholderText, QPalette.ColorRole.ButtonText)
        groups = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled)
        expected = {(group, role): APP.palette().color(group, role).rgba()
                    for group in groups for role in roles}
        for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            APP.styleHints().setColorScheme(scheme)
            APP.processEvents()
            for group in groups:
                for role in roles:
                    with self.subTest(scheme=scheme, group=group, role=role):
                        color = APP.palette().color(group, role)
                        self.assertEqual(color.rgba(), expected[group, role])
                        self.assertEqual(color.alpha(), 255)
                self.assertGreaterEqual(contrast(APP.palette().color(group, QPalette.ColorRole.Text),
                                                 APP.palette().color(group, QPalette.ColorRole.Base)), 4.5)

    def test_real_page_and_scroll_viewport_keep_painted_glass_visible(self):
        from phimthai.app import MainWindow

        # Exercise the real page factory without constructing app services.
        stack = QStackedWidget(self.panel)
        stack.setGeometry(20, 20, 744, 510)
        for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            APP.styleHints().setColorScheme(scheme)
            stack.hide()
            APP.processEvents()
            baseline = self.panel.grab().toImage().pixelColor(390, 450)
            stack.show()
            layout = MainWindow.page(SimpleNamespace(pages=stack), "ทดสอบ", "Readable Thai / English")
            layout.addStretch()
            stack.setCurrentIndex(stack.count() - 1)
            APP.processEvents()
            scroll = stack.currentWidget()
            self.assertFalse(scroll.widget().autoFillBackground())
            self.assertFalse(scroll.viewport().autoFillBackground())
            painted = self.panel.grab().toImage().pixelColor(390, 450)
            self.assertEqual(painted.rgba(), baseline.rgba(), "Opaque page covers the glass")

    def test_body_and_muted_contrast_on_brightest_painted_glass(self):
        muted = QLabel("Readable Thai / English", self.panel)
        muted.setObjectName("muted")
        muted.ensurePolished()
        muted.hide()
        for width, height in ((820, 600), (1040, 760)):
            self.canvas.resize(width, height)
            self.panel.setGeometry(18, 18, width - 36, height - 50)
            APP.processEvents()
            background = brightest_body_pixel(self.panel.grab().toImage())
            for name, color in (("body", APP.palette().color(QPalette.ColorRole.WindowText)),
                                ("muted", muted.palette().color(QPalette.ColorRole.WindowText))):
                with self.subTest(size=(width, height), text=name):
                    self.assertEqual(color.alpha(), 255)
                    self.assertGreaterEqual(contrast(color, background), 4.5,
                                            f"{name} {color.name()} on {background.name()}")

    def test_placeholder_has_opaque_palette_and_readable_rendered_glyphs(self):
        editor = QPlainTextEdit(self.panel)
        editor.setObjectName("editor")
        editor.setGeometry(30, 28, 710, 240)
        editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        editor.show()
        for reduced in (False, True):
            apply_style(APP, reduced_transparency=reduced)
            for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
                APP.styleHints().setColorScheme(scheme)
                editor.setPlaceholderText("")
                APP.processEvents()
                blank = editor.viewport().grab().toImage()
                editor.setPlaceholderText("เริ่มจากเสียงของคุณ · Readable voice")
                APP.processEvents()
                painted = editor.viewport().grab().toImage()
                color = editor.palette().color(QPalette.ColorRole.PlaceholderText)
                with self.subTest(reduced=reduced, scheme=scheme):
                    self.assertEqual(color.alpha(), 255, "QSS made placeholder text translucent")
                    self.assertGreaterEqual(rendered_text_contrast(blank, painted), 4.5)

    def test_reduced_transparency_is_solid_readable_and_invalidates_cache(self):
        glass = self.panel.grab().toImage()
        apply_style(APP, reduced_transparency=True)
        APP.processEvents()
        solid = self.panel.grab().toImage()
        colors = {solid.pixelColor(x, y).rgba() for x in (50, 200, 600)
                  for y in (50, 200, 400)}
        self.assertEqual(len(colors), 1, "Reduced transparency still paints varying glass")
        background = QColor.fromRgba(next(iter(colors)))
        self.assertEqual(background.alpha(), 255)
        self.assertGreaterEqual(contrast(APP.palette().color(QPalette.ColorRole.Text), background), 4.5)
        self.assertNotEqual(glass.pixelColor(50, 50).rgba(), solid.pixelColor(50, 50).rgba())
        apply_style(APP, reduced_transparency=False)
        APP.processEvents()
        restored = self.panel.grab().toImage()
        self.assertEqual(glass.pixelColor(50, 50).rgba(), restored.pixelColor(50, 50).rgba())


if __name__ == "__main__":
    unittest.main()
