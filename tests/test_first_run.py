"""First launch with isolated data and simulated downloads/desktop responses."""
import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dbus_next import Variant

from phimthai import portals
from phimthai.devices import select_device
from phimthai.settings import Settings, config_path, load_settings, save_settings
from tests.test_app_review import IsolatedWindow


class DownloadSetupTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.window.continue_desktop_setup = Mock()
        self.process = Mock()
        self.process.readAllStandardOutput.return_value = b""
        for target, value in (("phimthai.app.QProcess", self.process),
                              ("phimthai.app.local_model", None)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, self.window, "download_process", None)

    def test_first_launch_downloads_recommendation_once_with_main_page_notice(self):
        self.window.model_list.setCurrentRow(1)  # Browsing a model is not selecting it.
        self.window.start_first_run()
        self.window.start_first_run()
        self.process.start.assert_called_once()
        self.assertEqual(self.process.start.call_args.args[1], ["-m", "phimthai.models", "qwen-0.6b"])
        self.assertIn("Qwen3-ASR 0.6B", self.window.setup_message.text())
        self.assertIn("1.89", self.window.setup_message.text())
        self.assertEqual(load_settings().model_setup, "downloading")

    def test_cancel_stays_paused_on_relaunch_and_manual_resume_works(self):
        self.window.start_first_run()
        self.window.cancel_download()
        self.process.kill.assert_called_once()
        self.window.download_finished(9, None)
        self.assertEqual(load_settings().model_setup, "paused")
        self.process.start.reset_mock()
        self.window.startup_started = False
        self.window.settings = load_settings()
        self.window.start_first_run()
        self.process.start.assert_not_called()
        self.window.download_model(model_id="qwen-0.6b")
        self.process.start.assert_called_once()
        self.assertEqual(load_settings().model_setup, "downloading")

    def test_quit_preserves_resume_state_but_network_failure_pauses(self):
        self.window.start_first_run()
        self.window.quitting = True
        self.window.download_finished(9, None)
        self.assertEqual(load_settings().model_setup, "downloading")
        self.window.quitting = False
        self.window.download_model(model_id="qwen-0.6b")
        self.process.readAllStandardOutput.return_value = b'{"error":"Network unavailable"}\n'
        self.window.download_finished(1, None)
        self.assertEqual(load_settings().model_setup, "paused")
        self.assertIn("Network unavailable", self.window.setup_message.text())

    def test_removed_recommendation_is_never_downloaded_again_automatically(self):
        self.window.settings = replace(self.window.settings, model_setup="skipped")
        save_settings(self.window.settings)
        self.window.start_first_run()
        self.process.start.assert_not_called()

    def test_success_reads_final_worker_output_and_finishes_setup(self):
        self.window.start_first_run()
        self.process.readAllStandardOutput.return_value = b'{"done":true,"completed":200,"total":200}\n'
        with patch("phimthai.app.local_model", return_value=self.root):
            self.window.download_finished(0, None)
        self.assertEqual(load_settings().model_setup, "complete")
        self.assertIn("โมเดลพร้อมแล้ว", self.window.setup_message.text())

    def test_failed_settings_write_never_leaves_a_phantom_download(self):
        with patch("phimthai.app.save_settings", side_effect=OSError("disk full")):
            self.window.download_model(model_id="qwen-0.6b")
        self.assertIsNone(self.window.downloading_model)
        self.assertIsNone(self.window.download_process)
        self.process.start.assert_not_called()

    def test_record_availability_tracks_model_and_preserves_stop(self):
        self.window.update_setup_view()
        self.assertFalse(self.window.record_button.isEnabled())
        self.window.recording = True
        self.window.update_setup_view()
        self.assertTrue(self.window.record_button.isEnabled())
        self.window.recording = False
        with patch("phimthai.app.local_model", return_value=self.root):
            self.window.update_setup_view()
            self.assertTrue(self.window.record_button.isEnabled())
            self.window.downloading_model = self.window.settings.model
            self.window.update_setup_view()
            self.assertFalse(self.window.record_button.isEnabled())
        self.window.downloading_model = None


class DesktopSetupTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.window.settings = replace(self.window.settings, model_setup="skipped")
        self.commands = []
        self.bridge = SimpleNamespace(write=lambda raw: self.commands.append(json.loads(raw)),
                                      readAllStandardOutput=lambda: b"")
        self.window.portal = self.bridge
        self.addCleanup(setattr, self.window, "portal", None)
        patcher = patch("phimthai.kde.is_kde", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def event(self, *events):
        self.bridge.readAllStandardOutput = lambda: b"".join(json.dumps(event).encode() + b"\n" for event in events)
        self.window.portal_output()

    def test_permissions_are_sequential_and_readiness_requires_enabled_events(self):
        self.window.start_first_run()
        self.assertEqual([item["action"] for item in self.commands], ["restore"])
        self.event({"event": "command_finished", "action": "restore"})
        self.assertEqual(self.commands[-1]["action"], "shortcuts")
        self.assertEqual(self.commands[-1]["trigger"], "Meta+H")
        self.assertFalse(self.window.paste_enabled)
        self.event({"event": "shortcuts_enabled", "trigger": "Meta+H"},
                   {"event": "mode_shortcut_enabled", "trigger": "Meta+Shift+H"},
                   {"event": "command_finished", "action": "shortcuts"})
        self.assertEqual(self.commands[-1]["action"], "enable_paste")
        self.assertEqual(self.window.mode_shortcut_hint.text(), "Meta+Shift+H")
        self.event({"event": "paste_enabled", "persistent": True},
                   {"event": "command_finished", "action": "enable_paste"})
        self.assertTrue(self.window.paste_enabled)
        self.assertFalse(self.window.desktop_queue)

    def test_denial_clears_queue_and_does_not_repeat_on_next_launch(self):
        self.window.start_first_run()
        self.event({"event": "command_finished", "action": "restore"})
        self.event({"event": "error", "action": "shortcuts", "error": "permission denied"},
                   {"event": "command_finished", "action": "shortcuts"})
        self.assertFalse(self.window.portal_shortcut)
        self.assertFalse(self.window.paste_enabled)
        self.assertFalse(self.window.desktop_queue)
        self.window.startup_started = False
        self.window.settings = load_settings()
        self.commands.clear()
        self.window.start_first_run()
        self.event({"event": "command_finished", "action": "restore"})
        self.assertEqual([item["action"] for item in self.commands], ["restore"])

    def test_active_native_custom_bindings_are_preserved(self):
        self.window.kde_shortcut_state = {"active": True, "mode_active": True,
                                          "trigger": "Meta+J", "mode_trigger": "Meta+Shift+J"}
        self.window.start_first_run()
        self.assertTrue(self.commands[0]["skip_shortcuts"])
        self.event({"event": "command_finished", "action": "restore"})
        self.assertEqual([item["action"] for item in self.commands], ["restore", "enable_paste"])

    def test_partial_restored_binding_never_reopens_configure_during_setup(self):
        self.window.start_first_run()
        self.event({"event": "mode_shortcut_enabled", "trigger": "Meta+Shift+H"},
                   {"event": "command_finished", "action": "restore"})
        self.assertEqual(self.commands[-1]["action"], "enable_paste")
        self.assertFalse(self.window.portal_shortcut)

    def test_bridge_exit_clears_queue_and_quit_cannot_open_another_request(self):
        self.window.start_first_run()
        self.window.portal_finished()
        self.assertFalse(self.window.desktop_queue)
        self.window.quitting = True
        self.window.desktop_queue = [("shortcuts", {})]
        self.window.next_desktop_request()
        self.assertEqual(len(self.commands), 1)

    def test_closing_during_setup_leaves_it_pending_for_next_launch(self):
        self.window.start_first_run()
        self.assertFalse(self.window.settings.desktop_setup_done)
        self.window.portal_finished()
        self.window.startup_started = False
        self.window.portal = self.bridge
        self.commands.clear()
        self.window.start_first_run()
        self.event({"event": "command_finished", "action": "restore"})
        self.assertEqual([item["action"] for item in self.commands], ["restore", "shortcuts"])

    def test_cold_hotkey_restores_permissions_before_recording(self):
        self.window.settings = replace(self.window.settings, desktop_setup_done=True)
        self.window.startup_action = "toggle"
        with patch("phimthai.app.local_model", return_value=self.root), \
             patch.object(self.window, "toggle_record") as record:
            self.window.start_first_run()
            record.assert_not_called()
            self.event({"event": "paste_enabled", "persistent": True},
                       {"event": "command_finished", "action": "restore"})
            record.assert_called_once()
        self.assertFalse(self.window.startup_action)

    def test_cold_hotkey_without_model_never_starts_recording_after_download(self):
        self.window.startup_action = "toggle"
        with patch("phimthai.app.local_model", return_value=None), \
             patch.object(self.window, "showNormal") as show:
            self.window.start_first_run()
        show.assert_called_once()
        self.assertFalse(self.window.startup_action)


class DefaultsAndBetaTests(IsolatedWindow, unittest.TestCase):
    def test_new_defaults_and_old_settings_migration(self):
        self.assertEqual(Settings().paste_mode, "immediate")
        self.assertTrue(Settings().remember_desktop)
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 2, "model": "qwen-1.7b", "device": "gpu", "profile": "raw"}))
        old = load_settings()
        self.assertEqual((old.model, old.device, old.profile), ("qwen-1.7b", "gpu", "raw"))
        self.assertEqual(old.model_setup, "skipped")
        self.assertTrue(old.desktop_setup_done)
        self.assertFalse(old.remember_desktop)
        self.assertEqual(old.paste_mode, "review")

    def test_auto_does_not_use_available_gpu_or_old_fast_measurements(self):
        torch = Mock()
        torch.cuda.is_available.return_value = True
        with patch("phimthai.performance.choose", return_value=("cuda", "")) as choose:
            self.assertEqual(select_device("auto", torch), ("cpu", ""))
        choose.assert_not_called()
        self.assertEqual(select_device("gpu", torch), ("cuda", ""))

    def test_accelerators_have_visible_beta_labels_and_red_warning(self):
        for device in ("gpu", "npu"):
            self.assertIn("Beta", self.window.device.itemText(self.window.device.findData(device)))
        self.assertIn("ฟีเจอร์นี้อยู่ในขั้นตอนพัฒนา หากเปิดแล้วจะมีผลลัพธ์ไม่แน่นอน", self.window.beta_warning.text())
        self.assertEqual(self.window.beta_warning.objectName(), "betaWarning")
        from phimthai.appearance import _STYLESHEET
        self.assertIn("QLabel#betaWarning { color: #ff9b9b", _STYLESHEET)

    def test_partial_shortcuts_changed_preserves_other_binding(self):
        client = portals.Portals()
        with patch.object(portals, "emit") as emit:
            client.report_shortcuts([["record", {"trigger_description": Variant("s", "Meta+H")}],
                                     ["cycle-mode", {"trigger_description": Variant("s", "Meta+Shift+H")}]])
            client.report_shortcuts([["record", {"trigger_description": Variant("s", "Meta+J")}]], partial=True)
        self.assertEqual(client.shortcut_bindings, {"record": "Meta+J", "cycle-mode": "Meta+Shift+H"})
        emit.assert_called_with(event="mode_shortcut_enabled", trigger="Meta+Shift+H")

    def test_portal_preferred_trigger_uses_xdg_logo_not_qt_meta_spelling(self):
        self.assertEqual(portals.preferred_trigger("Meta+H"), "LOGO+h")
        self.assertEqual(portals.preferred_trigger("Meta+Shift+H"), "LOGO+SHIFT+h")
        self.assertEqual(portals.preferred_trigger("Ctrl+Alt+Space"), "CTRL+ALT+space")
        with self.assertRaises(ValueError):
            portals.preferred_trigger("NoModifier+H")


if __name__ == "__main__":
    unittest.main()
