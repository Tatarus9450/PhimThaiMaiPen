"""Private rotating log, crash capture, and a pasteable diagnostic report."""
import configparser
import glob
import json
import logging
import logging.handlers
import os
import platform
import re
import sys
from collections import deque
from pathlib import Path

from . import APP_ID, __version__
from .settings import config_path, data_dir

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handler = None
_SECRET = re.compile(r"""(?i)\b(\w*token|\w*secret|password|passwd|api[_-]?key|authorization)\b(["']?\s*[:=]\s*["']?)[^\s"',]+""")
_SYSTEM_FLATPAK = Path("/var/lib/flatpak/app")
_HEX = re.compile(r"\b[0-9a-f]{32,}\b")


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "phimthai"


def log_path() -> Path:
    return state_dir() / "logs/phimthai.log"


def setup_logging(level=logging.INFO):
    global _handler
    root = logging.getLogger()
    root.setLevel(level)
    if _handler is not None and _handler in root.handlers:
        return _handler
    try:
        path = log_path()
        for d in (state_dir(), path.parent):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(d, 0o700)
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
        os.chmod(path, 0o600)
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except Exception:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    _handler = handler
    if not getattr(sys.excepthook, "_phimthai", False):
        previous = sys.excepthook

        def hook(kind, value, tb):
            try:
                logging.getLogger("phimthai").critical("Uncaught exception", exc_info=(kind, value, tb))
            except Exception:
                pass
            previous(kind, value, tb)
        hook._phimthai = True
        sys.excepthook = hook
    return handler


def tail(lines=200) -> str:
    try:
        with log_path().open(encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=lines))
    except OSError:
        return ""


def _flatpak_info():
    try:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read("/.flatpak-info")
        out = []
        for section, keys in (("Application", ("name", "runtime")), ("Instance", ("branch", "app-commit", "arch", "flatpak-version"))):
            out += [f"{section}.{k}={parser.get(section, k)}" for k in keys if parser.has_option(section, k)]
        return out
    except Exception:
        return []


def _installed_version(root: Path):
    for init in glob.glob(str(root / "active/files/lib/python3*/site-packages/phimthai/__init__.py")):
        try:
            match = re.search(r'__version__\s*=\s*"([^"]+)"', Path(init).read_text(encoding="utf-8"))
            if match:
                return match.group(1)
        except OSError:
            pass
    return "unknown version"


def detect_duplicate_installs() -> list[str]:
    found = []
    try:
        home = Path.home()
        for scope, base in (("system", _SYSTEM_FLATPAK),
                            ("user", Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "flatpak/app")):
            try:
                for branch in sorted((base / APP_ID).glob("*/*")):
                    if branch.is_dir() and (branch / "active").exists():
                        found.append(f"Flatpak ({scope}) {branch.parent.name}/{branch.name}: {_installed_version(branch)}")
            except OSError:
                pass
        launcher = data_dir() / "bin/phimthai"
        if launcher.exists():
            found.append(f"Native launcher: {launcher}")
        desktop = home / ".local/share/applications" / f"{APP_ID}.desktop"
        if desktop.exists():
            found.append(f"User desktop entry overrides Flatpak export: {desktop}")
    except Exception:
        pass
    return found


def _settings_summary():
    try:
        values = json.loads(config_path().read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            return ["settings: unreadable"]
    except FileNotFoundError:
        return ["settings: none (new installation)"]
    except Exception:
        return ["settings: unreadable"]
    out = []
    for key, value in sorted(values.items()):
        if key == "dictionary":
            value = f"<redacted, {len(value) if isinstance(value, str) else '?'} chars>"
        elif key == "microphone":
            value = "<set>" if value else "<default>"
        elif not isinstance(value, (bool, int, float)) and not (isinstance(value, str) and len(value) <= 40):
            value = f"<{type(value).__name__}>"
        out.append(f"settings.{key}={value}")
    return out


def _redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)


def diagnostic_report(extra: dict | None = None) -> str:
    lines = ["PhimThaiMaiPen diagnostic report", f"version: {__version__}",
             f"python: {sys.version.split()[0]}"]
    try:
        import PySide6
        from PySide6 import QtCore
        lines += [f"PySide6: {PySide6.__version__}", f"Qt: {QtCore.qVersion()}"]
    except Exception:
        lines.append("PySide6: unavailable")
    lines += [f"platform: {platform.platform()}",
              f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE', '')}",
              f"XDG_CURRENT_DESKTOP: {os.environ.get('XDG_CURRENT_DESKTOP', '')}"]
    info = _flatpak_info() if os.path.exists("/.flatpak-info") else []
    lines.append(f"flatpak: {'yes' if os.path.exists('/.flatpak-info') else 'no'}")
    lines += [f"  {line}" for line in info]
    lines += _settings_summary()
    duplicates = detect_duplicate_installs()
    lines.append("installs: " + ("none visible" if not duplicates else ""))
    lines += [f"  {d}" for d in duplicates]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    lines += ["", f"--- log tail ({log_path()}) ---", _HEX.sub("<redacted>", tail())]
    return _redact("\n".join(lines))
