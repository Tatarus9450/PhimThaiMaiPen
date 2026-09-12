"""Persistent native KDE desktop-action shortcuts (no recording or key injection).

KDE's service action runs the installed desktop's Record command, even when the
GUI is closed. The portal's in-process action cannot provide that persistence.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus
from PySide6.QtGui import QKeySequence

from . import APP_ID

DEST = "org.kde.kglobalaccel"
PATH = "/kglobalaccel"
INTERFACE = "org.kde.KGlobalAccel"
COMPONENT = APP_ID + ".desktop"
ACTION = [COMPONENT, "Record", "PhimThaiMaiPen", "Start or stop recording"]
MODE_ACTION = [COMPONENT, "CycleMode", "PhimThaiMaiPen", "Cycle typing mode"]
LEGACY = ("linux-voice-typing-record.desktop", "linux-voice-typing-profile.desktop")
OWNED_ACTIONS = {(COMPONENT, "Record"), (COMPONENT, "CycleMode"), (APP_ID, "record"),
                 *((name, "_launch") for name in LEGACY)}
# KDE kglobalaccel/src/kglobalaccel_p.h: SetPresent=2, NoAutoloading=4.
SET_ACTIVE = 6


def is_kde():
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")


def data_home():
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))


def _key(trigger):
    sequence = QKeySequence.fromString(trigger, QKeySequence.SequenceFormat.PortableText)
    label = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    if not label or sequence.isEmpty() or sequence.count() != 1 or not sequence[0].key().value:
        raise ValueError("Choose one key combination, for example Meta+H")
    return sequence[0].toCombined(), label


def _label(keys):
    return "; ".join(QKeySequence(value).toString(QKeySequence.SequenceFormat.PortableText) for value in keys)


async def _call(bus, member, signature="", body=None, path=PATH, interface=INTERFACE):
    response = await asyncio.wait_for(bus.call(Message(destination=DEST, path=path,
        interface=interface, member=member, signature=signature, body=body or [])), 5)
    if response.message_type == MessageType.ERROR:
        raise RuntimeError(f"KDE {member}: " + str(response.body[0] if response.body else response.error_name))
    return response.body


async def _status(bus):
    keys = (await _call(bus, "shortcut", "as", [ACTION]))[0]
    mode_keys = (await _call(bus, "shortcut", "as", [MODE_ACTION]))[0]
    active = False
    if keys or mode_keys:
        path = (await _call(bus, "getComponent", "s", [COMPONENT]))[0]
        active = bool((await _call(bus, "isActive", path=path,
                                  interface="org.kde.kglobalaccel.Component"))[0])
    return {"available": True, "active": active and bool(keys), "trigger": _label(keys),
            "keys": keys, "component": COMPONENT, "action": "Record",
            "mode_active": active and bool(mode_keys), "mode_trigger": _label(mode_keys), "mode_keys": mode_keys}


def _desktop_argument(path):
    value = str(path).replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value.replace("\\", "\\\\") + '"'


def _desktop_text(launcher):
    text = (Path(__file__).parent / "assets" / COMPONENT).read_text()
    return text.replace("Exec=phimthai", "Exec=/usr/bin/env " + _desktop_argument(launcher))


def _backup(paths, bindings):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = data_home() / "phimthai/backups" / ("kde-" + stamp + "-" + uuid.uuid4().hex[:8])
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"bindings": bindings, "files": []}
    for index, path in enumerate(paths):
        if path.is_file():
            copy = destination / (str(index) + "-" + path.name)
            shutil.copy2(path, copy)
            manifest["files"].append({"path": str(path), "backup": copy.name,
                                      "sha256": hashlib.sha256(copy.read_bytes()).hexdigest()})
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return destination


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def _install(bus, trigger, launcher):
    key, trigger = _key(trigger)
    launcher = Path(launcher or data_home() / "phimthai/bin/phimthai").expanduser().absolute()
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise RuntimeError("Install the native application launcher before enabling its shortcut")
    mode_keys = (await _call(bus, "shortcut", "as", [MODE_ACTION]))[0]
    if len(mode_keys) > 1:
        raise RuntimeError("Keep the existing multi-shortcut mode binding; configure changes in KDE Settings")
    mode_key, mode_trigger = _key(_label(mode_keys) if mode_keys else "Meta+Shift+H")
    if key == mode_key:
        raise RuntimeError("Recording and cycling modes need different shortcuts")
    for candidate, label in ((key, trigger), (mode_key, mode_trigger)):
        owners = (await _call(bus, "getGlobalShortcutsByKey", "i", [candidate]))[0]
        for owner in owners:
            # KGlobalShortcutInfo: action, action display, component, component display, ...
            if (owner[2], owner[0]) not in OWNED_ACTIONS:
                raise RuntimeError(f"{label} belongs to {owner[3]} / {owner[1]}; choose another shortcut")

    retired = [[APP_ID, "record", "PhimThaiMaiPen", "Start / stop voice typing"],
               *[[name, "_launch", "PhimThaiMaiPen", "Launch"] for name in LEGACY]]
    existing = (await _call(bus, "allActionsForComponent", "as", [[COMPONENT, "", "", ""]]))[0]
    extra = [action for action in existing if action[:2] not in [ACTION[:2], MODE_ACTION[:2]]]
    bindings = []
    for action in [ACTION, MODE_ACTION, *extra, *retired]:
        keys = (await _call(bus, "shortcut", "as", [action]))[0]
        present = False
        if keys:
            component_path = (await _call(bus, "getComponent", "s", [action[0]]))[0]
            present = bool((await _call(bus, "isActive", path=component_path,
                interface="org.kde.kglobalaccel.Component"))[0])
        bindings.append({"action": action, "keys": keys, "present": present})
    desktop = data_home() / "applications" / COMPONENT
    service = data_home() / "kglobalaccel" / COMPONENT
    # The separate legacy cleanup also owns applications/profile.desktop. Its
    # shortcut and kglobalaccel copy are retired here, without touching that file.
    legacy_files = [data_home() / "applications" / LEGACY[0],
                    *[data_home() / "kglobalaccel" / name for name in LEGACY]]
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "kglobalshortcutsrc"
    backup = _backup([desktop, service, config, *legacy_files], bindings)
    try:
        text = _desktop_text(launcher)
        if "[Desktop Action CycleMode]" not in text:
            raise RuntimeError("Update the native desktop asset before registering the mode shortcut")
        _write(desktop, text)
        _write(service, text)
        if shutil.which("kbuildsycoca6"):
            subprocess.run(["kbuildsycoca6", "--noincremental"], check=True,
                           capture_output=True, text=True, timeout=20)
        if existing:
            # KDE caches KService actions in the existing component. Recreate
            # only our component to refresh new actions/launcher locations.
            component_path = (await _call(bus, "getComponent", "s", [COMPONENT]))[0]
            await _call(bus, "cleanUp", path=component_path, interface="org.kde.kglobalaccel.Component")
        # Only app-owned bindings are removed. No system-wide key stealing or
        # configuration rewrite; KDE preserves every other component and action.
        for action in retired:
            await _call(bus, "unregister", "ss", action[:2])
        for action, candidate in ((ACTION, key), (MODE_ACTION, mode_key)):
            await _call(bus, "doRegister", "as", [action])
            assigned = (await _call(bus, "setShortcut", "asaiu", [action, [candidate], SET_ACTIVE]))[0]
            if assigned != [candidate]:
                raise RuntimeError("KDE did not activate the requested shortcut")
        for item in bindings:
            if item["action"] in extra:
                await _call(bus, "doRegister", "as", [item["action"]])
                await _call(bus, "setShortcut", "asaiu", [item["action"], item["keys"], SET_ACTIVE])
        status = await _status(bus)
        if not status["active"] or status["keys"] != [key] or not status["mode_active"] or status["mode_keys"] != [mode_key]:
            raise RuntimeError("KDE did not activate the requested shortcut")
        for path in legacy_files:
            path.unlink(missing_ok=True)
        status.update(backup=str(backup), persistent=True)
        return status
    except Exception as exc:
        # Restore only bindings touched in this transaction; never overwrite the
        # full config while the daemon may be saving unrelated user changes.
        failures = []
        manifest = json.loads((backup / "manifest.json").read_text())
        originals = {item["path"]: backup / item["backup"] for item in manifest["files"]}
        for path in [desktop, service, *legacy_files]:
            try:
                if str(path) in originals:
                    _write(path, originals[str(path)].read_text())
                else:
                    path.unlink(missing_ok=True)
            except OSError as restore_error:
                failures.append(str(restore_error))
        try:
            component_path = (await _call(bus, "getComponent", "s", [COMPONENT]))[0]
            await _call(bus, "cleanUp", path=component_path, interface="org.kde.kglobalaccel.Component")
            if shutil.which("kbuildsycoca6"):
                subprocess.run(["kbuildsycoca6", "--noincremental"], check=True,
                               capture_output=True, text=True, timeout=20)
        except Exception as restore_error:
            failures.append(str(restore_error))
        for item in bindings:
            try:
                await _call(bus, "doRegister", "as", [item["action"]])
                await _call(bus, "setShortcut", "asaiu", [item["action"], item["keys"], SET_ACTIVE if item["present"] else 4])
                if not item["present"]:
                    await _call(bus, "setInactive", "as", [item["action"]])
            except Exception as restore_error:
                failures.append(str(restore_error))
        raise RuntimeError(f"{exc}. Shortcut backup: {backup}" +
                           ("; restoration needs attention: " + "; ".join(failures) if failures else "")) from exc


async def _connected(operation, *args):
    bus = MessageBus()
    try:
        await asyncio.wait_for(bus.connect(), 5)
        return await operation(bus, *args)
    finally:
        bus.disconnect()
        try:
            await asyncio.wait_for(bus.wait_for_disconnect(), 1)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            # dbus-next 0.2.3 shuts down this socket but does not close its file
            # descriptor in _finalize. Close after its event reader is removed.
            sock = getattr(bus, "_sock", None)
            if sock is not None:
                sock.close()


async def _ensure(bus, launcher):
    state = await _status(bus)
    if state["active"]:
        if len(state["keys"]) != 1:
            raise RuntimeError("Keep the existing multi-shortcut binding; configure changes in KDE Settings")
        trigger = state["trigger"]
    else:
        from .settings import load_settings
        trigger = load_settings().hotkey
    return await _install(bus, trigger, launcher)


def _sync(operation, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_connected(operation, *args))
    # Do not create an unawaited coroutine inside an existing event loop.
    raise RuntimeError("Use the phimthai.kde CLI from an active asyncio event loop")


def shortcut_status():
    """Read the actual KDE service binding; does not open the app or microphone."""
    try:
        return _sync(_status)
    except Exception as exc:
        return {"available": False, "active": False, "trigger": "", "error": str(exc)}


def install_shortcut(trigger="Meta+H", launcher=None):
    """Install or change this app's native shortcut; return verified status."""
    try:
        return _sync(_install, trigger, launcher)
    except Exception as exc:
        return {"available": False, "active": False, "trigger": "", "error": str(exc)}


def ensure_shortcut(launcher=None):
    """Refresh the installed command while preserving an active custom binding."""
    try:
        return _sync(_ensure, launcher)
    except Exception as exc:
        return {"available": False, "active": False, "trigger": "", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--install", nargs="?", const="", metavar="TRIGGER")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--ensure", action="store_true", help="Keep an existing active shortcut when updating")
    parser.add_argument("--trigger", default="Meta+H")
    parser.add_argument("--launcher", type=Path)
    args = parser.parse_args()
    if args.ensure:
        result = ensure_shortcut(args.launcher)
    else:
        result = install_shortcut(args.install or args.trigger, args.launcher) if args.install is not None else shortcut_status()
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
