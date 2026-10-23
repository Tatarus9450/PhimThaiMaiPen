"""Duplicate shortcut detection reads a fake kglobalshortcutsrc and never writes it."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from phimthai import kde

DUPLICATED = """[ActivityManager]
switch-to-activity-x=none,none,Switch
_k_friendly_name=Activity Manager

[io.github.tatarus9450.PhimThaiMaiPen]
_k_friendly_name=PhimThaiMaiPen
cycle-mode=Meta+Shift+H,Meta+Shift+H,Switch dictation mode
record=Meta+H,Meta+H,Start / stop voice typing

[services][io.github.tatarus9450.PhimThaiMaiPen.desktop]
CycleMode=Meta+Shift+H
Record=Meta+H

[services][kitty.desktop]
_launch=Meta+H
"""


class ConflictTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config"),
                                              "XDG_DATA_HOME": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        exports = patch.object(kde, "SYSTEM_FLATPAK_EXPORTS", self.root / "system-flatpak")
        exports.start()
        self.addCleanup(exports.stop)
        self.config = self.root / "config/kglobalshortcutsrc"
        self.config.parent.mkdir()

    def test_portal_and_service_entries_for_same_trigger_conflict(self):
        self.config.write_text(DUPLICATED)
        conflicts = {item["trigger"]: item["bindings"] for item in kde.find_conflicts()}
        self.assertEqual(set(conflicts), {"Meta+H", "Meta+Shift+H"})
        self.assertEqual({(entry["source"], entry["action"]) for entry in conflicts["Meta+H"]},
                         {("portal", "record"), ("service", "Record")})
        # Other applications' bindings are not this app's duplicates.
        self.assertFalse(any(entry["component"] == "kitty.desktop" for entries in conflicts.values() for entry in entries))
        self.assertEqual(self.config.read_text(), DUPLICATED)

    def test_portal_only_and_unbound_entries_are_clean(self):
        self.config.write_text("[io.github.tatarus9450.PhimThaiMaiPen]\nrecord=Meta+H,Meta+H,Start\n"
                               "cycle-mode=none,Meta+Shift+H,Switch\n"
                               "[services][io.github.tatarus9450.PhimThaiMaiPen.desktop]\nRecord=none\n")
        self.assertEqual(kde.find_conflicts(), [])
        self.assertEqual([item["action"] for item in kde.config_bindings()], ["record"])

    def test_legacy_and_multi_key_entries_are_detected(self):
        self.config.write_text("[services][linux-voice-typing-record.desktop]\n_launch=Meta+H\tCtrl+F9\n"
                               "[io.github.tatarus9450.PhimThaiMaiPen]\nrecord=Ctrl+F9,none,Start\n")
        conflicts = kde.find_conflicts()
        self.assertEqual([item["trigger"] for item in conflicts], ["Ctrl+F9"])
        self.assertEqual({entry["source"] for entry in conflicts[0]["bindings"]}, {"legacy", "portal"})

    def test_missing_config_is_not_an_error(self):
        self.config.unlink(missing_ok=True)
        self.assertEqual(kde.find_conflicts(), [])

    def test_doctor_reports_fix_and_cli_exit_code(self):
        self.config.write_text(DUPLICATED)
        with patch.object(kde, "_sync", side_effect=RuntimeError("No session bus")):
            report = kde.doctor()
            self.assertFalse(report["ok"])
            self.assertIn("--remove-service-shortcuts", report["advice"])
            self.assertEqual(report["live_error"], "No session bus")
            self.assertFalse(report["flatpak_installed"])
            output = io.StringIO()
            with patch.object(sys, "argv", ["phimthai.kde", "--doctor"]), redirect_stdout(output):
                self.assertEqual(kde.main(), 2)
        self.assertEqual(len(json.loads(output.getvalue())["conflicts"]), 2)

    def test_doctor_uses_live_kde_bindings(self):
        self.config.write_text("")
        live = [{"source": "portal", "component": kde.APP_ID, "action": "record", "keys": ["Meta+H"]},
                {"source": "service", "component": kde.COMPONENT, "action": "Record", "keys": ["Meta+H"]}]
        with patch.object(kde, "_sync", return_value=live):
            report = kde.doctor()
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(report["live_conflicts"][0]["trigger"], "Meta+H")
        self.assertFalse(report["ok"])

    def test_flatpak_export_is_detected(self):
        export = self.root / "data/flatpak/exports/share/applications" / kde.COMPONENT
        export.parent.mkdir(parents=True)
        export.write_text("[Desktop Entry]\n")
        self.assertTrue(kde.flatpak_installed())

    def test_remove_cli_reports_errors_as_json(self):
        output = io.StringIO()
        with patch.object(kde, "_sync", side_effect=RuntimeError("No session bus")), \
             patch.object(sys, "argv", ["phimthai.kde", "--remove-service-shortcuts"]), redirect_stdout(output):
            self.assertEqual(kde.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"removed": [], "error": "No session bus"})


if __name__ == "__main__":
    unittest.main()
