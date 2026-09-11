"""Desktop consent and one-use restore tokens, without a real D-Bus connection."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from dbus_next import Variant
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
        self.events.assert_called_once_with(event="shortcuts_disabled")

    async def test_restore_ignores_corrupt_state_and_unknown_fields(self):
        portals.state_path().parent.mkdir(parents=True, exist_ok=True)
        for raw in ("null", "[]", "{bad", '{"paste_token":false,"untrusted":"action"}'):
            portals.state_path().write_text(raw)
            await self.client.restore()
        self.client.session.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
