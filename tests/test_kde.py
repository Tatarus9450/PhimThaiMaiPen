"""Native KDE shortcut ownership and transaction rollback without a real bus."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phimthai import kde


class KDETests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config")})
        environment.start()
        self.addCleanup(environment.stop)
        self.launcher = self.root / "data/phimthai/bin/phimthai"
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.launcher.chmod(0o755)
        self.key = kde._key("Meta+H")[0]
        self.bindings = {(kde.APP_ID, "record"): [self.key],
                         ("unrelated", "Keep"): [123456]}
        self.present = {kde.APP_ID: False}
        self.owners = [["record", "Record", kde.APP_ID, "PhimThaiMaiPen"]]
        self.calls = []
        self.reject = False
        self.reject_action = kde.ACTION
        call_patch = patch.object(kde, "_call", self.call)
        call_patch.start()
        self.addCleanup(call_patch.stop)
        programs = patch.object(kde.shutil, "which", return_value=None)
        programs.start()
        self.addCleanup(programs.stop)

    async def call(self, bus, member, signature="", body=None, path=kde.PATH, interface=kde.INTERFACE):
        body = body or []
        self.calls.append((member, body))
        if member == "getGlobalShortcutsByKey":
            return [self.owners]
        if member == "shortcut":
            return [self.bindings.get(tuple(body[0][:2]), []).copy()]
        if member == "allActionsForComponent":
            return [[[component, action, "PhimThaiMaiPen", action]
                     for component, action in self.bindings if component == body[0][0]]]
        if member == "getComponent":
            return ["/test/" + body[0]]
        if member == "isActive":
            return [self.present.get(path.removeprefix("/test/"), False)]
        if member == "cleanUp":
            component = path.removeprefix("/test/")
            self.bindings = {action: keys for action, keys in self.bindings.items() if action[0] != component}
            self.present[component] = False
            return [True]
        if member == "unregister":
            self.bindings.pop(tuple(body), None)
            return [True]
        if member == "doRegister":
            self.bindings.setdefault(tuple(body[0][:2]), [])
            return []
        if member == "setShortcut":
            action, keys, flags = body
            if self.reject and action == self.reject_action and keys:
                return [[]]
            self.bindings[tuple(action[:2])] = keys.copy()
            if flags & 2:
                self.present[action[0]] = True
            return [keys.copy()]
        if member == "setInactive":
            self.present[body[0][0]] = False
            return []
        raise AssertionError(member)

    async def test_migration_is_persistent_scoped_and_backs_up_removed_files(self):
        old = self.root / "data/kglobalaccel" / kde.LEGACY[0]
        old.parent.mkdir(parents=True)
        old.write_text("legacy command\n")
        config = self.root / "config/kglobalshortcutsrc"
        config.parent.mkdir()
        config.write_text("[Unrelated]\nKeep=hello\n")
        result = await kde._install(None, "Meta+H", self.launcher)
        self.assertTrue(result["active"])
        self.assertTrue(result["persistent"])
        self.assertTrue(result["mode_active"])
        self.assertEqual(result["mode_trigger"], "Meta+Shift+H")
        self.assertEqual(self.bindings[(kde.COMPONENT, "Record")], [self.key])
        self.assertEqual(self.bindings[("unrelated", "Keep")], [123456])
        self.assertEqual(config.read_text(), "[Unrelated]\nKeep=hello\n")
        self.assertFalse(old.exists())
        backup = Path(result["backup"])
        saved = json.loads((backup / "manifest.json").read_text())
        self.assertTrue(any(item["path"] == str(old) for item in saved["files"]))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        desktop = (self.root / "data/kglobalaccel" / kde.COMPONENT).read_text()
        self.assertIn("[Desktop Action Record]", desktop)
        self.assertIn("--toggle", desktop)
        self.assertNotIn("NoDisplay=true", desktop)
        unregistered = [tuple(body) for method, body in self.calls if method == "unregister"]
        self.assertEqual(set(unregistered), {(kde.APP_ID, "record"), *((name, "_launch") for name in kde.LEGACY)})

    async def test_external_owner_conflict_changes_nothing(self):
        self.owners = [["Action", "External action", "some.other.app", "Other app"]]
        before = self.bindings.copy()
        with self.assertRaisesRegex(RuntimeError, "belongs to Other app"):
            await kde._install(None, "Meta+H", self.launcher)
        self.assertEqual(before, self.bindings)
        self.assertFalse((self.root / "data/phimthai/backups").exists())
        self.assertEqual([method for method, _ in self.calls], ["shortcut", "getGlobalShortcutsByKey"])

    async def test_rejected_registration_restores_dormant_portal_and_desktop(self):
        desktop = self.root / "data/applications" / kde.COMPONENT
        desktop.parent.mkdir(parents=True)
        desktop.write_text("original application content\n")
        self.reject = True
        with self.assertRaisesRegex(RuntimeError, "did not activate"):
            await kde._install(None, "Meta+H", self.launcher)
        self.assertEqual(self.bindings[(kde.APP_ID, "record")], [self.key])
        self.assertFalse(self.present[kde.APP_ID])
        self.assertEqual(self.bindings[("unrelated", "Keep")], [123456])
        self.assertEqual(desktop.read_text(), "original application content\n")
        self.assertFalse((self.root / "data/kglobalaccel" / kde.COMPONENT).exists())

    async def test_missing_launcher_never_releases_shortcut(self):
        self.launcher.unlink()
        with self.assertRaisesRegex(RuntimeError, "launcher"):
            await kde._install(None, "Meta+H", self.launcher)
        self.assertEqual(self.calls, [])

    async def test_inactive_component_is_not_reported_as_ready(self):
        self.bindings[(kde.COMPONENT, "Record")] = [self.key]
        self.present[kde.COMPONENT] = False
        result = await kde._status(None)
        self.assertFalse(result["active"])
        self.assertEqual(result["trigger"], "Meta+H")

    async def test_invalid_multistep_shortcut_cannot_change_binding(self):
        for trigger in ("Ctrl+A, Ctrl+B", "nonsense", "Ctrl", "Meta+", ""):
            with self.subTest(trigger=trigger), self.assertRaises(ValueError):
                await kde._install(None, trigger, self.launcher)
        self.assertEqual(self.calls, [])

    async def test_sync_probe_in_async_loop_returns_error_without_opening_bus(self):
        with patch.object(kde, "MessageBus") as bus:
            result = kde.shortcut_status()
        self.assertFalse(result["active"])
        self.assertIn("CLI", result["error"])
        bus.assert_not_called()

    async def test_installer_ensure_preserves_active_custom_shortcut(self):
        custom = kde._key("Ctrl+Alt+F9")[0]
        self.bindings[(kde.COMPONENT, "Record")] = [custom]
        mode_custom = kde._key("Ctrl+Alt+F10")[0]
        self.bindings[(kde.COMPONENT, "CycleMode")] = [mode_custom]
        self.bindings[(kde.COMPONENT, "_launch")] = [98765]
        self.present[kde.COMPONENT] = True
        with patch("phimthai.settings.load_settings") as load:
            result = await kde._ensure(None, self.launcher)
        load.assert_not_called()
        self.assertEqual(result["trigger"], "Ctrl+Alt+F9")
        self.assertEqual(self.bindings[(kde.COMPONENT, "Record")], [custom])
        self.assertEqual(result["mode_trigger"], "Ctrl+Alt+F10")
        self.assertEqual(self.bindings[(kde.COMPONENT, "_launch")], [98765])

    async def test_second_action_failure_rolls_back_both_keys(self):
        self.bindings[(kde.COMPONENT, "Record")] = [self.key]
        self.bindings[(kde.COMPONENT, "_launch")] = [98765]
        self.present[kde.COMPONENT] = True
        self.reject, self.reject_action = True, kde.MODE_ACTION
        with self.assertRaisesRegex(RuntimeError, "did not activate"):
            await kde._install(None, "Ctrl+Alt+F9", self.launcher)
        self.assertEqual(self.bindings[(kde.COMPONENT, "Record")], [self.key])
        self.assertEqual(self.bindings[(kde.COMPONENT, "_launch")], [98765])
        self.assertEqual(self.bindings[(kde.APP_ID, "record")], [self.key])
        self.assertFalse(self.present[kde.APP_ID])

    async def test_mode_conflict_cannot_remove_record_binding(self):
        original_call = self.call
        async def conflict(bus, member, signature="", body=None, **kwargs):
            if member == "getGlobalShortcutsByKey" and body == [kde._key("Meta+Shift+H")[0]]:
                return [[["Keep", "External mode", "other.app", "Other app"]]]
            return await original_call(bus, member, signature, body, **kwargs)
        with patch.object(kde, "_call", conflict), self.assertRaisesRegex(RuntimeError, "Meta\\+Shift\\+H belongs"):
            await kde._install(None, "Meta+H", self.launcher)
        self.assertEqual(self.bindings[(kde.APP_ID, "record")], [self.key])
        self.assertFalse(any(method in {"unregister", "cleanUp", "setShortcut"} for method, _ in self.calls))


class KDEUnavailableTests(unittest.TestCase):
    def test_bus_failure_is_an_inactive_status(self):
        with patch.object(kde.MessageBus, "__init__", side_effect=RuntimeError("No session bus")):
            result = kde.shortcut_status()
        self.assertFalse(result["active"])
        self.assertFalse(result["available"])
        self.assertIn("No session bus", result["error"])


if __name__ == "__main__":
    unittest.main()
