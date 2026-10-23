"""Settings repair, private logging, and the diagnostic report."""
import json
import logging
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phimthai import APP_ID, logs
from phimthai.settings import DEFAULT_MODEL, config_path, load_settings, load_settings_with_report


class TempXdg(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = {"HOME": str(self.tmp / "home"), "XDG_CONFIG_HOME": str(self.tmp / "config"),
               "XDG_DATA_HOME": str(self.tmp / "home/.local/share"), "XDG_STATE_HOME": str(self.tmp / "state")}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, text):
        config_path().parent.mkdir(parents=True, exist_ok=True)
        config_path().write_text(text, encoding="utf-8")

    def backups(self):
        return list(config_path().parent.glob("settings.json.bak-*"))


class SettingsRepairTests(TempXdg):
    def test_valid_file_loads_without_warnings_or_backup(self):
        self.write(json.dumps({"version": 2, "model": "qwen-1.7b", "paste_mode": "immediate"}))
        settings, warnings = load_settings_with_report()
        self.assertEqual((settings.model, settings.paste_mode, settings.model_setup), ("qwen-1.7b", "immediate", "skipped"))
        self.assertEqual(warnings, [])
        self.assertEqual(self.backups(), [])

    def test_threads_too_high_are_clamped(self):
        self.write(json.dumps({"version": 2, "cpu_threads": (os.cpu_count() or 1) + 64, "profile": "raw"}))
        settings, warnings = load_settings_with_report()
        self.assertEqual(settings.cpu_threads, os.cpu_count() or 1)
        self.assertEqual(settings.profile, "raw")
        self.assertTrue(any("cpu_threads" in w for w in warnings))
        backup, = self.backups()
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertIn('"cpu_threads"', backup.read_text())

    def test_threads_zero_clamped_to_one(self):
        self.write(json.dumps({"version": 2, "cpu_threads": 0}))
        self.assertEqual(load_settings().cpu_threads, 1)

    def test_unknown_model_and_wrong_types_use_defaults(self):
        self.write(json.dumps({"version": 2, "model": "gone-model", "keep_history": "yes",
                               "device": "tpu", "hotkey": 5, "cpu_threads": True, "language": "Thai"}))
        settings, warnings = load_settings_with_report()
        self.assertEqual(settings.model, DEFAULT_MODEL)
        self.assertFalse(settings.keep_history)
        self.assertEqual((settings.device, settings.hotkey, settings.language), ("auto", "Meta+H", "Thai"))
        self.assertEqual(settings.cpu_threads, os.cpu_count() or 1)
        for key in ("model", "keep_history", "device", "hotkey", "cpu_threads"):
            self.assertIn(f"ตั้งค่า {key} ไม่ถูกต้อง ใช้ค่าเริ่มต้นแทน", warnings)
        self.assertEqual(len(self.backups()), 1)
        load_settings_with_report()
        self.assertEqual(len(self.backups()), 1)  # Repeated loads do not pile up identical backups.

    def test_corrupt_json_is_backed_up_and_treated_as_upgrade(self):
        self.write("{not json")
        settings, warnings = load_settings_with_report()
        self.assertEqual(len(warnings), 1)
        self.assertEqual((settings.model_setup, settings.desktop_setup_done, settings.paste_mode), ("skipped", True, "review"))
        self.assertFalse(settings.remember_desktop)
        backup, = self.backups()
        self.assertEqual(backup.read_text(), "{not json")
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_non_object_json_is_corrupt(self):
        self.write("[1, 2]")
        self.assertEqual(len(load_settings_with_report()[1]), 1)

    def test_unsupported_version_still_raises(self):
        self.write(json.dumps({"version": 3}))
        with self.assertRaises(ValueError):
            load_settings_with_report()

    def test_missing_file_is_new_installation(self):
        settings, warnings = load_settings_with_report()
        self.assertEqual((settings.model_setup, warnings), ("pending", []))


class LoggingTests(TempXdg):
    def setUp(self):
        super().setUp()
        root = logging.getLogger()
        saved = (root.level, list(root.handlers), sys.excepthook, logs._handler)

        def restore():
            for h in root.handlers[:]:
                if h not in saved[1]:
                    root.removeHandler(h)
                    h.close()
            root.setLevel(saved[0])
            sys.excepthook, logs._handler = saved[2], saved[3]
        self.addCleanup(restore)

    def test_setup_is_idempotent_and_private(self):
        first = logs.setup_logging()
        hook = sys.excepthook
        self.assertIs(logs.setup_logging(), first)
        self.assertIs(sys.excepthook, hook)
        self.assertEqual(sum(h is first for h in logging.getLogger().handlers), 1)
        self.assertEqual(logs.log_path(), self.tmp / "state/phimthai/logs/phimthai.log")
        self.assertEqual(stat.S_IMODE(logs.state_dir().stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(logs.log_path().parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(logs.log_path().stat().st_mode), 0o600)
        logging.getLogger("phimthai.test").warning("hello log")
        first.flush()
        self.assertIn("WARNING phimthai.test: hello log", logs.tail())

    def test_uncaught_exception_is_logged_and_chained(self):
        calls = []
        sys.excepthook = lambda *a: calls.append(a)
        handler = logs.setup_logging()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        handler.flush()
        self.assertEqual(len(calls), 1)
        self.assertIn("RuntimeError: boom", logs.tail())

    def test_unwritable_state_falls_back_to_stderr(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("")
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(blocker)}):
            handler = logs.setup_logging()
        self.assertIsInstance(handler, logging.StreamHandler)
        self.assertNotIsInstance(handler, logging.FileHandler)

    def test_tail_without_log(self):
        self.assertEqual(logs.tail(), "")


class ReportTests(TempXdg):
    def test_report_redacts_dictionary_and_tokens(self):
        self.write(json.dumps({"version": 2, "dictionary": "ชื่อลับมาก\nSecretWord", "microphone": "alsa_input.usb-Mic"}))
        logs.log_path().parent.mkdir(parents=True)
        logs.log_path().write_text("paste_token=deadbeefcafe restore_token: s3cr3t\n"
                                   "transaction 0123456789abcdef0123456789abcdef\n")
        report = logs.diagnostic_report({"backend": "openvino", "paste_token": "xyz789"})
        for secret in ("ชื่อลับมาก", "SecretWord", "deadbeefcafe", "s3cr3t", "xyz789",
                       "0123456789abcdef0123456789abcdef", "alsa_input"):
            self.assertNotIn(secret, report)
        for expected in ("version: ", "python: ", "XDG_SESSION_TYPE", "settings.version=2",
                         "settings.dictionary=<redacted", "backend: openvino", "log tail"):
            self.assertIn(expected, report)

    def test_report_survives_unreadable_settings(self):
        self.write("{bad")
        self.assertIn("settings: unreadable", logs.diagnostic_report())


class DuplicateInstallTests(TempXdg):
    def make_flatpak(self, base, branch, version):
        site = base / APP_ID / "x86_64" / branch / "active/files/lib/python3.13/site-packages/phimthai"
        site.mkdir(parents=True)
        (site / "__init__.py").write_text(f'__version__ = "{version}"\n')

    def test_reports_flatpaks_launcher_and_desktop_override(self):
        home = Path(os.environ["HOME"])
        system = self.tmp / "system"
        self.make_flatpak(system, "beta", "2.0.0b4")
        self.make_flatpak(home / ".local/share/flatpak/app", "beta", "2.0.0b5")
        launcher = home / ".local/share/phimthai/bin/phimthai"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("")
        desktop = home / ".local/share/applications" / f"{APP_ID}.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text("")
        with patch.object(logs, "_SYSTEM_FLATPAK", system):
            found = logs.detect_duplicate_installs()
            self.assertIn("2.0.0b5", logs.diagnostic_report())
        self.assertEqual(len(found), 4)
        self.assertIn("Flatpak (system) x86_64/beta: 2.0.0b4", found)
        self.assertIn("Flatpak (user) x86_64/beta: 2.0.0b5", found)
        self.assertTrue(any("Native launcher" in f for f in found))
        self.assertTrue(any("overrides" in f for f in found))

    def test_nothing_visible(self):
        with patch.object(logs, "_SYSTEM_FLATPAK", self.tmp / "missing"):
            self.assertEqual(logs.detect_duplicate_installs(), [])

    def test_never_raises(self):
        with patch.object(logs.Path, "home", side_effect=RuntimeError):
            self.assertEqual(logs.detect_duplicate_installs(), [])


if __name__ == "__main__":
    unittest.main()
