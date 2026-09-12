"""Desktop consent and one-use restore tokens, without a real D-Bus connection."""
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from dbus_next import Message, MessageType, Variant
from phimthai import portals


class PortalConsentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.client = portals.Portals()
        self.client.session = AsyncMock(return_value="/test/session")
        self.client.close_session = AsyncMock()
        self.client.request = AsyncMock(side_effect=[{}, {"devices": 1, "restore_token": "new-test-token"}])
        self.emitter = patch.object(portals, "emit")
        self.events = self.emitter.start()
        self.addCleanup(self.emitter.stop)

    async def test_default_grant_is_session_only_and_saves_no_token(self):
        await self.client.enable_paste()
        options = self.client.request.call_args_list[0].args[3][-1]
        self.assertEqual(set(options), {"types"})
        self.assertFalse(portals.state_path().exists())
        self.assertEqual(self.client.remote, "/test/session")
        self.events.assert_called_with(event="paste_enabled", persistent=False)

    async def test_restore_consumes_old_token_and_saves_new_token_privately(self):
        portals.remember(paste_token="old-test-token")
        async def response(interface, member, signature, body):
            self.assertNotIn("paste_token", portals.saved_state())
            if member == "SelectDevices":
                self.assertEqual(body[-1]["restore_token"].value, "old-test-token")
                self.assertEqual(body[-1]["persist_mode"].value, 2)
                return {}
            return {"devices": 1, "restore_token": "new-test-token"}
        self.client.request.side_effect = response
        await self.client.enable_paste(persist=True, token="old-test-token")
        self.assertEqual(portals.saved_state(), {"paste_token": "new-test-token"})
        self.assertEqual(portals.state_path().stat().st_mode & 0o777, 0o600)

    async def test_denial_never_reuses_token_or_enables_keyboard(self):
        portals.remember(paste_token="old-test-token")
        self.client.request.side_effect = [{}, RuntimeError("permission denied")]
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            await self.client.enable_paste(persist=True, token="old-test-token")
        self.assertIsNone(self.client.remote)
        self.assertNotIn("paste_token", portals.saved_state())
        self.client.close_session.assert_awaited_once_with("/test/session")
        self.assertFalse(any(call.kwargs.get("event") == "paste_enabled" for call in self.events.call_args_list))

    async def test_optional_persistence_error_does_not_lose_granted_session(self):
        with patch.object(portals, "remember", side_effect=OSError("disk full")):
            await self.client.enable_paste(persist=True)
        self.assertEqual(self.client.remote, "/test/session")
        self.client.close_session.assert_not_awaited()
        self.events.assert_called_with(event="paste_enabled", persistent=False)

    async def test_enabling_remember_after_session_grant_requests_persistence(self):
        self.client.remote = "/test/previous-session"
        await self.client.enable_paste(persist=True)
        self.assertEqual(self.client.remote, "/test/session")
        self.assertEqual(portals.saved_state()["paste_token"], "new-test-token")
        self.client.close_session.assert_awaited_once_with("/test/previous-session")
        options = self.client.request.call_args_list[0].args[3][-1]
        self.assertEqual(options["persist_mode"].value, 2)

    async def test_denied_persistence_upgrade_keeps_existing_live_permission(self):
        self.client.remote = "/test/previous-session"
        self.client.request.side_effect = [{}, RuntimeError("permission denied")]
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            await self.client.enable_paste(persist=True)
        self.assertEqual(self.client.remote, "/test/previous-session")
        self.client.close_session.assert_awaited_once_with("/test/session")
        self.assertEqual(portals.saved_state(), {})

    async def test_repeated_enable_reuses_a_remembered_live_session(self):
        self.client.remote = "/test/previous-session"
        portals.remember(paste_token="saved-test-token")
        await self.client.enable_paste(persist=True)
        self.client.session.assert_not_awaited()
        self.events.assert_called_with(event="paste_enabled", persistent=True)

    async def test_shortcut_with_no_binding_is_disabled(self):
        self.client.report_shortcuts([["record", {"trigger_description": Variant("s", "")} ]])
        self.events.assert_any_call(event="shortcuts_disabled")
        self.events.assert_called_with(event="mode_shortcut_enabled", trigger="")

    async def test_mode_shortcut_is_bound_and_routes_only_its_session(self):
        self.client.request.side_effect = None
        self.client.request.return_value = {"shortcuts": [
            ["record", {"trigger_description": Variant("s", "Meta+H")}],
            ["cycle-mode", {"trigger_description": Variant("s", "Meta+Shift+H")}]]}
        await self.client.enable_shortcuts("META+h")
        bindings = self.client.request.call_args.args[3][1]
        self.assertEqual({entry[0] for entry in bindings}, {"record", "cycle-mode"})
        self.events.assert_any_call(event="mode_shortcut_enabled", trigger="Meta+Shift+H")
        self.events.reset_mock()
        for session in ("/other/session", self.client.shortcuts):
            self.client.message(Message.new_signal(portals.PATH, "org.freedesktop.portal.GlobalShortcuts",
                "Activated", "osta{sv}", [session, "cycle-mode", 0, {}]))
        self.events.assert_called_once_with(event="cycle_mode")
        self.events.reset_mock()
        self.client.report_shortcuts([["record", {"trigger_description": Variant("s", "Meta+H")} ]])
        self.events.assert_called_with(event="mode_shortcut_enabled", trigger="")

    async def test_restore_ignores_corrupt_state_and_unknown_fields(self):
        portals.state_path().parent.mkdir(parents=True, exist_ok=True)
        for raw in ("null", "[]", "{bad", '{"paste_token":false,"untrusted":"action"}'):
            portals.state_path().write_text(raw)
            await self.client.restore()
        self.client.session.assert_not_awaited()


class PortalPasteKeycodeTests(unittest.IsolatedAsyncioTestCase):
    """Physical evdev keys remain the same under Thai and English layouts."""

    def setUp(self):
        self.client = portals.Portals()
        self.client.remote = "/test/keyboard-session"
        self.success = SimpleNamespace(message_type=MessageType.METHOD_RETURN)
        self.client.bus = SimpleNamespace(call=AsyncMock(return_value=self.success))
        emitter = patch.object(portals, "emit")
        self.events = emitter.start()
        self.addCleanup(emitter.stop)

    def sent_keys(self):
        return [tuple(call.args[0].body[-2:]) for call in self.client.bus.call.await_args_list]

    async def test_uses_evdev_control_v_press_then_reverse_release(self):
        await self.client.paste("test-request")
        self.assertEqual(self.sent_keys(), [(29, 1), (47, 1), (47, 0), (29, 0)])
        for call in self.client.bus.call.await_args_list:
            message = call.args[0]
            self.assertEqual(message.member, "NotifyKeyboardKeycode")
            self.assertEqual(message.interface, "org.freedesktop.portal.RemoteDesktop")
            self.assertEqual(message.destination, portals.DEST)
            self.assertEqual(message.path, portals.PATH)
            self.assertEqual(message.signature, "oa{sv}iu")
            self.assertEqual(message.body[:2], [self.client.remote, {}])
        self.events.assert_called_once_with(event="paste_sent", request_id="test-request")

    async def test_missing_permission_never_sends_keyboard_events(self):
        self.client.remote = None
        with self.assertRaisesRegex(RuntimeError, "Enable paste permission"):
            await self.client.paste()
        self.client.bus.call.assert_not_awaited()
        self.events.assert_not_called()

    async def test_press_failure_still_attempts_both_releases_without_success_ack(self):
        for keycode in (29, 47):
            for failure in ("transport", "dbus-error"):
                with self.subTest(keycode=keycode, failure=failure):
                    self.client.bus.call.reset_mock()
                    self.events.reset_mock()

                    async def response(message):
                        if tuple(message.body[-2:]) == (keycode, 1):
                            if failure == "transport":
                                raise OSError("Synthetic keyboard transport failure")
                            return SimpleNamespace(message_type=MessageType.ERROR)
                        return self.success

                    self.client.bus.call.side_effect = response
                    with self.assertRaises(Exception):
                        await self.client.paste()
                    self.assertEqual(self.sent_keys()[-2:], [(47, 0), (29, 0)])
                    self.events.assert_not_called()

    async def test_release_failure_cannot_skip_control_release_or_claim_success(self):
        for keycode in (47, 29):
            for failure in ("transport", "dbus-error"):
                with self.subTest(keycode=keycode, failure=failure):
                    self.client.bus.call.reset_mock()
                    self.events.reset_mock()

                    async def response(message):
                        if tuple(message.body[-2:]) == (keycode, 0):
                            if failure == "transport":
                                raise OSError("Synthetic keyboard release failure")
                            return SimpleNamespace(message_type=MessageType.ERROR)
                        return self.success

                    self.client.bus.call.side_effect = response
                    with self.assertRaisesRegex(RuntimeError, "Keyboard release failed"):
                        await self.client.paste()
                    self.assertEqual(self.sent_keys(), [(29, 1), (47, 1), (47, 0), (29, 0)])
                    self.events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
