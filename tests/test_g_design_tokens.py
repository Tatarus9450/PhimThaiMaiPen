"""Design tokens, theme selection, focus rules and WCAG contrast (agent G)."""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QLabel, QLineEdit, QListWidget,
                               QPushButton)

from phimthai import appearance
from phimthai.appearance import GlassCanvas, GlassPanel, apply_style

APP = QApplication.instance() or QApplication([])

CONTRACT_NAMES = (
    "modelCard", "chip", "betaBadge", "settingsSection", "sectionTitle", "micLevel",
    "savedIndicator", "checkRow", "setupWizard", "stepIndicator", "tryField",
    "betaWarning", "canvas", "sidebar", "workspace", "navigation", "brand", "shortcut",
    "modeSwitch", "muted", "heading", "section", "status", "editor", "onboarding",
    "setupMessage", "recordControl", "pasteAction",
    # Agent F's page names.
    "modelName", "modelStatus", "technicalInfo", "cardMenu", "modelProgress", "pageMessage",
    "fieldError", "fieldLabel", "shortcutStatus", "sectionToggle", "hotkeyEdit", "dictionary",
    "checkIcon", "checkTitle", "checkDetail", "diagnosticSummary", "diagnosticsRaw",
    "stepItem", "wizardStep", "wizardTitle", "stepStatus", "wizardSkip", "tryInstructions",
)
CONTRACT_SELECTORS = (
    "#modelCard[selected=true]", '#checkRow[state="ok"]', '#checkRow[state="fail"]',
    '#checkRow[state="unknown"]', '#recordControl[state="recording"]',
    '#recordControl[state="processing"]', "[primary=true]", "#pageMessage[error=true]",
    '#stepItem[state="current"]', '#stepItem[state="done"]', '#stepItem[state="todo"]',
    '#checkIcon[state="ok"]', '#checkIcon[state="fail"]', '#shortcutStatus[ok=true]',
)
FOCUS_SELECTORS = (
    "QPushButton:focus", "QToolButton:focus", "QComboBox:focus", "QLineEdit:focus",
    "QKeySequenceEdit QLineEdit:focus", "QPlainTextEdit:focus", "QCheckBox:focus",
    "QRadioButton:focus", "QListWidget::item:focus", "QSpinBox:focus",
)
MODES = [(theme, reduced) for theme in ("light", "dark") for reduced in (False, True)]


def restore():
    apply_style(APP, reduced_transparency=False, theme="auto", reduced_motion=False)


class TokenContrastTests(unittest.TestCase):
    def test_every_audited_pair_meets_wcag_aa(self):
        for theme, reduced in MODES:
            for fg, bg, surface, ratio, minimum in appearance.token_contrast_report(theme, reduced):
                with self.subTest(theme=theme, reduced=reduced, fg=fg, bg=bg, surface=surface):
                    self.assertGreaterEqual(ratio, minimum, f"{fg} on {bg}/{surface}: {ratio:.2f}")

    def test_required_pairs_are_audited(self):
        pairs = {(fg, bg) for fg, bg, *_ in appearance.token_contrast_report("light")}
        for pair in (("danger", "glass"), ("muted", "glass"), ("text", "glass"),
                     ("danger", "dangerBg"), ("controlBorder", "glass"), ("focus", "glass"),
                     ("recordText", "record"), ("primaryText", "primaryBottom")):
            self.assertIn(pair, pairs)
        self.assertEqual(appearance.PALETTES["light"]["danger"], "#9b2c39")

    def test_both_palettes_define_the_same_tokens(self):
        self.assertEqual(set(appearance.PALETTES["light"]), set(appearance.PALETTES["dark"]))

    def test_spacing_scale(self):
        self.assertEqual(sorted(appearance.SPACE.values()), [4, 8, 12, 16, 24, 32])
        self.assertTrue(10.5 <= appearance.TYPE["body"] <= 11)

    def test_audit_model_covers_rendered_glass(self):
        """Painted glass never falls outside the composited surfaces in the audit."""
        for theme in ("light", "dark"):
            apply_style(APP, theme=theme)
            canvas = GlassCanvas()
            canvas.resize(1040, 760)
            panel = GlassPanel(canvas)
            panel.setGeometry(18, 18, 1004, 710)
            canvas.show()
            APP.processEvents()
            image = panel.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
            lums = [appearance.luminance(image.pixelColor(x, y))
                    for y in range(28, image.height() - 28, 6)
                    for x in range(28, image.width() - 28, 6)]
            surfaces = [appearance.luminance(c)
                        for c in appearance.glass_surfaces(theme).values()]
            canvas.close()
            with self.subTest(theme=theme):
                self.assertGreaterEqual(min(lums), min(surfaces) - .01)
                self.assertLessEqual(max(lums), max(surfaces) + .01)
        restore()


class ApplyStyleTests(unittest.TestCase):
    def tearDown(self):
        restore()

    def test_each_mode_applies_and_has_focus_and_contract_rules(self):
        for theme in ("auto", "light", "dark"):
            for reduced in (False, True):
                for motion in (False, True):
                    apply_style(APP, reduced_transparency=reduced, theme=theme,
                                reduced_motion=motion)
                    sheet = APP.styleSheet()
                    with self.subTest(theme=theme, reduced=reduced, motion=motion):
                        self.assertNotIn("$", sheet)
                        for name in CONTRACT_NAMES:
                            self.assertIn("#" + name, sheet)
                        for selector in CONTRACT_SELECTORS + FOCUS_SELECTORS:
                            self.assertIn(selector, sheet)
                        self.assertIn("border: 2px solid " + QColor(
                            appearance.PALETTES[appearance.current_theme()]["focus"]).name(), sheet)

    def test_positional_legacy_call_still_works(self):
        apply_style(APP, True)
        self.assertTrue(APP.property("phimthaiReducedTransparency"))
        apply_style(APP)
        self.assertFalse(APP.property("phimthaiReducedTransparency"))

    def test_invalid_theme_rejected(self):
        with self.assertRaises(ValueError):
            apply_style(APP, theme="sepia")

    def test_auto_follows_mocked_system_scheme(self):
        with mock.patch.object(appearance, "_system_scheme", return_value=Qt.ColorScheme.Dark):
            apply_style(APP, theme="auto")
            self.assertEqual(appearance.current_theme(), "dark")
            window = APP.palette().color(QPalette.ColorRole.Window)
            self.assertLess(appearance.luminance(window), .05)
        with mock.patch.object(appearance, "_system_scheme", return_value=Qt.ColorScheme.Light):
            apply_style(APP, theme="auto")
            self.assertEqual(appearance.current_theme(), "light")
        with mock.patch.object(appearance, "_system_scheme", return_value=Qt.ColorScheme.Unknown):
            apply_style(APP, theme="auto")
            self.assertEqual(appearance.current_theme(), "light")

    def test_live_scheme_change_only_affects_auto(self):
        with mock.patch.object(appearance, "_system_scheme", return_value=Qt.ColorScheme.Light):
            apply_style(APP, theme="auto")
        with mock.patch.object(appearance, "_system_scheme", return_value=Qt.ColorScheme.Dark):
            appearance._on_scheme_changed(Qt.ColorScheme.Dark)
            self.assertEqual(appearance.current_theme(), "dark")
            apply_style(APP, theme="light")   # forced light ignores the desktop
            appearance._on_scheme_changed(Qt.ColorScheme.Dark)
            self.assertEqual(appearance.current_theme(), "light")

    def test_theme_and_motion_are_sticky_across_legacy_calls(self):
        apply_style(APP, theme="dark", reduced_motion=True)
        apply_style(APP, reduced_transparency=True)  # e.g. the settings checkbox
        self.assertEqual(appearance.current_theme(), "dark")
        self.assertTrue(APP.property("phimthaiReducedMotion"))

    def test_reduced_motion_disables_ui_effects(self):
        apply_style(APP, reduced_motion=True)
        for effect in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu,
                       Qt.UIEffect.UI_AnimateCombo, Qt.UIEffect.UI_AnimateTooltip):
            self.assertFalse(APP.isEffectEnabled(effect))
        self.assertEqual(APP.style().styleHint(
            appearance.QStyle.StyleHint.SH_Widget_Animation_Duration), 0)

    def test_dark_glass_is_dark_and_cache_invalidates(self):
        apply_style(APP, theme="light")
        canvas = GlassCanvas()
        canvas.resize(500, 400)
        panel = GlassPanel(canvas)
        panel.setGeometry(18, 18, 464, 360)
        canvas.show()
        APP.processEvents()
        light = panel.grab().toImage().pixelColor(200, 200)
        apply_style(APP, theme="dark")
        APP.processEvents()
        dark = panel.grab().toImage().pixelColor(200, 200)
        canvas.close()
        self.assertGreater(appearance.luminance(light), .6)
        self.assertLess(appearance.luminance(dark), .05)
        text = APP.palette().color(QPalette.ColorRole.WindowText)
        self.assertGreaterEqual(appearance.contrast_ratio(text, dark), 7)


class TypographyTests(unittest.TestCase):
    def tearDown(self):
        restore()

    def test_font_stack_prefers_installed_thai_family(self):
        families = appearance.font_families()
        self.assertTrue(families)
        self.assertTrue(set(families) <= set(appearance.FONT_STACK) | {"Noto Sans"})
        apply_style(APP)
        self.assertEqual(APP.font().families()[0], families[0])
        self.assertAlmostEqual(APP.font().pointSizeF(), appearance.TYPE["body"])

    def test_thai_marks_fit_in_controls(self):
        apply_style(APP, theme="light")
        sample = "ญี่ปุ่น ปั้นน้ำ ฎีกา ฤทธิ์"
        for widget in (QPushButton(sample), QLineEdit(sample), QComboBox(), QListWidget()):
            if isinstance(widget, QComboBox):
                widget.addItem(sample)
            if isinstance(widget, QListWidget):
                widget.addItem(sample)
            widget.ensurePolished()
            metrics = QFontMetrics(widget.font())
            ink = metrics.tightBoundingRect(sample).height()
            with self.subTest(widget=type(widget).__name__):
                if isinstance(widget, QListWidget):
                    height = widget.sizeHintForRow(0)
                else:
                    height = widget.sizeHint().height()
                self.assertGreaterEqual(height, max(ink, metrics.height()) + 12)
                self.assertGreaterEqual(height, 36)


if __name__ == "__main__":
    unittest.main()
