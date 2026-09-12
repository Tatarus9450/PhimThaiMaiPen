"""Desktop requests from first-launch setup or controls; the OS owns consent."""
import asyncio
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

DEST = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"


def state_path():
    from .settings import config_path
    return config_path().with_name("desktop-sessions.json")


def saved_state():
    try:
        values = json.loads(state_path().read_text())
        if not isinstance(values, dict):
            return {}
        return {key: value for key, value in values.items()
                if key in {"shortcut", "paste_token"} and isinstance(value, str) and value}
    except (OSError, ValueError):
        return {}


def remember(**values):
    path = state_path()
    state = saved_state()
    for key, value in values.items():
        state.pop(key, None)
        if value:
            state[key] = value
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        json.dump(state, output)
        temporary = Path(output.name)
    temporary.replace(path)


def emit(**event):
    print(json.dumps(event), flush=True)


def preferred_trigger(trigger):
    """Translate UI/Qt spelling to the XDG shortcuts specification."""
    parts = trigger.strip().split("+")
    aliases = {"CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "SHIFT": "SHIFT",
               "META": "LOGO", "SUPER": "LOGO", "LOGO": "LOGO"}
    try:
        modifiers = [aliases[part.upper()] for part in parts[:-1]]
    except KeyError as exc:
        raise ValueError("รูปแบบปุ่มลัดไม่รองรับ เช่น Meta+H หรือ Ctrl+Alt+Space") from exc
    key = parts[-1]
    key = {"SPACE": "space", "ESC": "Escape", "ESCAPE": "Escape", "RETURN": "Return",
           "ENTER": "Return", "TAB": "Tab", "BACKSPACE": "BackSpace", "DELETE": "Delete"}.get(key.upper(), key)
    if len(key) == 1:
        key = key.lower()
    if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
        raise ValueError("รูปแบบปุ่มลัดไม่รองรับ เช่น Meta+H")
    return "+".join([*modifiers, key])


class Portals:
    def __init__(self):
        self.bus = None
        self.responses = {}
        self.shortcuts = None
        self.remote = None
        self.shortcut_bindings = {}

    def message(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.responses.get(message.path)
            if future and not future.done():
                future.set_result(message.body)
        if message.interface == "org.freedesktop.portal.GlobalShortcuts" and message.member == "Activated":
            if self.shortcuts and message.body[0] == self.shortcuts:
                if message.body[1] == "record":
                    emit(event="shortcut")
                elif message.body[1] == "cycle-mode":
                    emit(event="cycle_mode")
        if message.interface == "org.freedesktop.portal.GlobalShortcuts" and message.member == "ShortcutsChanged":
            if self.shortcuts and message.body[0] == self.shortcuts:
                self.report_shortcuts(message.body[1], partial=True)
        if message.interface == "org.freedesktop.portal.Session" and message.member == "Closed":
            if message.path == self.remote:
                self.remote = None
                emit(event="paste_disabled")
            if message.path == self.shortcuts:
                self.shortcuts = None
                self.shortcut_bindings.clear()
                emit(event="shortcuts_disabled")
                emit(event="mode_shortcut_enabled", trigger="")

    async def connect(self):
        self.bus = await MessageBus().connect()
        self.bus.add_message_handler(self.message)
        await self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s",
            body=["type='signal',sender='org.freedesktop.portal.Desktop'"]))

    async def request(self, interface, member, signature, body):
        token = "phimthai_" + uuid.uuid4().hex
        body[-1]["handle_token"] = Variant("s", token)
        sender = self.bus.unique_name.lstrip(":").replace(".", "_")
        path = PATH + "/request/" + sender + "/" + token
        future = asyncio.get_running_loop().create_future()
        self.responses[path] = future
        try:
            reply = await self.bus.call(Message(destination=DEST, path=PATH,
                interface="org.freedesktop.portal." + interface, member=member, signature=signature, body=body))
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError(" ".join(str(v) for v in reply.body))
            code, values = await asyncio.wait_for(future, timeout=120)
            if code:
                raise RuntimeError("Desktop permission was cancelled or denied")
            return {key: value.value for key, value in values.items()}
        except asyncio.TimeoutError as exc:
            await self.bus.call(Message(destination=DEST, path=path,
                interface="org.freedesktop.portal.Request", member="Close"))
            raise RuntimeError("Desktop permission request timed out. Try again when ready to respond.") from exc
        finally:
            self.responses.pop(path, None)

    async def close_session(self, path):
        if path:
            await self.bus.call(Message(destination=DEST, path=path,
                interface="org.freedesktop.portal.Session", member="Close"))

    async def session(self, interface):
        response = await self.request(interface, "CreateSession", "a{sv}",
            [{"session_handle_token": Variant("s", "phimthai_" + uuid.uuid4().hex)}])
        return response["session_handle"]

    async def enable_shortcuts(self, trigger, persist=False):
        if self.shortcuts:
            reply = await self.bus.call(Message(destination=DEST, path=PATH, interface="org.freedesktop.portal.GlobalShortcuts",
                member="ConfigureShortcuts", signature="osa{sv}", body=[self.shortcuts, "", {}]))
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError("Shortcut configuration is unavailable on this desktop. Restart the app to bind again.")
            if persist:
                try:
                    remember(shortcut=trigger)
                except OSError:
                    emit(event="warning", error="Shortcut works for this session; desktop preference could not be saved")
            return
        session = await self.session("GlobalShortcuts")
        try:
            response = await self.request("GlobalShortcuts", "BindShortcuts", "oa(sa{sv})sa{sv}",
                [session, [["record", {"description": Variant("s", "Start / stop voice typing"),
                                             "preferred_trigger": Variant("s", preferred_trigger(trigger))}],
                           ["cycle-mode", {"description": Variant("s", "Switch dictation mode"),
                                           "preferred_trigger": Variant("s", "LOGO+SHIFT+h")}]], "", {}])
            self.shortcuts = session
            self.report_shortcuts(response.get("shortcuts", []))
            if persist:
                try:
                    remember(shortcut=trigger)
                except OSError:
                    emit(event="warning", error="Shortcut works for this session; desktop preference could not be saved")
        except BaseException:
            await self.close_session(session)
            raise

    def report_shortcuts(self, shortcuts, partial=False):
        if not partial:
            self.shortcut_bindings.clear()
        for identifier, values in shortcuts:
            if identifier in {"record", "cycle-mode"}:
                description = values.get("trigger_description")
                self.shortcut_bindings[identifier] = description.value.strip() if description and isinstance(description.value, str) else ""
        trigger = self.shortcut_bindings.get("record", "")
        emit(event="shortcuts_enabled", trigger=trigger) if trigger else emit(event="shortcuts_disabled")
        emit(event="mode_shortcut_enabled", trigger=self.shortcut_bindings.get("cycle-mode", ""))

    async def enable_paste(self, persist=False, token=""):
        previous = self.remote
        if previous and (not persist or saved_state().get("paste_token")):
            emit(event="paste_enabled", persistent=bool(saved_state().get("paste_token")))
            return
        session = await self.session("RemoteDesktop")
        try:
            options = {"types": Variant("u", 1)}
            if persist:
                options["persist_mode"] = Variant("u", 2)
                if token:
                    options["restore_token"] = Variant("s", token)
                    # Tokens are single use. Never retry a consumed token after
                    # denial or a crash; the OS can request consent again.
                    remember(paste_token="")
            await self.request("RemoteDesktop", "SelectDevices", "oa{sv}",
                [session, options])
            response = await self.request("RemoteDesktop", "Start", "osa{sv}", [session, "", {}])
            if not response.get("devices", 0) & 1:
                raise RuntimeError("Keyboard permission was not granted")
            persisted = False
            if persist:
                try:
                    remember(paste_token=response.get("restore_token", ""))
                    persisted = bool(response.get("restore_token"))
                except OSError:
                    emit(event="warning", error="Paste works for this session; desktop permission could not be saved")
            self.remote = session
        except BaseException:
            await self.close_session(session)
            raise
        if previous:
            try:
                await self.close_session(previous)
            except Exception:
                emit(event="warning", error="Previous paste session could not be closed; it will end when the app exits")
        emit(event="paste_enabled", persistent=persisted)

    async def restore(self, skip_shortcuts=False):
        state = saved_state()
        for key, value in state.items():
            try:
                if key == "shortcut":
                    if not skip_shortcuts:
                        await self.enable_shortcuts(value, persist=True)
                elif key == "paste_token":
                    await self.enable_paste(persist=True, token=value)
            except Exception as exc:
                emit(event="error", error=str(exc))

    async def paste(self, request_id=None):
        if not self.remote:
            raise RuntimeError("Enable paste permission in Settings, or use Copy")
        async def key(keycode, state):
            try:
                return await asyncio.wait_for(self.bus.call(Message(destination=DEST, path=PATH,
                        interface="org.freedesktop.portal.RemoteDesktop", member="NotifyKeyboardKeycode",
                        signature="oa{sv}iu", body=[self.remote, {}, keycode, state])), timeout=5)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Keyboard request timed out") from exc
        # Linux evdev KEY_LEFTCTRL / KEY_V. A Latin 'v' keysym cannot be
        # resolved by KDE while the Thai keyboard layout is active.
        try:
            for keycode in (29, 47):
                reply = await key(keycode, 1)
                if reply.message_type == MessageType.ERROR:
                    raise RuntimeError("Keyboard request failed")
        finally:
            release_error = None
            for keycode in (47, 29):
                try:
                    reply = await key(keycode, 0)
                    if reply.message_type == MessageType.ERROR:
                        raise RuntimeError("Keyboard release failed")
                except Exception as exc:
                    # Still release Ctrl if releasing V failed.
                    release_error = release_error or exc
            if release_error:
                raise RuntimeError("Keyboard release failed") from release_error
        emit(event="paste_sent", request_id=request_id)


async def main():
    portals = Portals()
    await portals.connect()
    emit(event="ready")
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        action = None
        request = {}
        try:
            request = json.loads(line)
            action = request["action"]
            if action == "shortcuts":
                await portals.enable_shortcuts(request.get("trigger", "META+h"), request.get("persist", False))
            elif action == "enable_paste":
                await portals.enable_paste(request.get("persist", False))
            elif action == "paste":
                await portals.paste(request.get("request_id"))
            elif action == "restore":
                await portals.restore(skip_shortcuts=request.get("skip_shortcuts", False))
            elif action == "forget":
                state_path().unlink(missing_ok=True)
        except Exception as exc:
            emit(event="error", error=str(exc), action=action,
                 request_id=request.get("request_id") if isinstance(request, dict) else None)
        finally:
            if action in {"shortcuts", "enable_paste", "restore"}:
                emit(event="command_finished", action=action)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        emit(event="error", error=str(exc))
