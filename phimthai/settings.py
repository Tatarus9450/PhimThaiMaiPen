"""Versioned user settings, independent of an application's installation path."""
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_MODEL = "typhoon-realtime"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "phimthai"


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "phimthai/settings.json"


@dataclass
class Settings:
    version: int = 2
    model: str = DEFAULT_MODEL
    device: str = "auto"
    language: str = "auto"
    profile: str = "smart"
    microphone: str = ""
    paste_mode: str = "immediate"
    preference: str = "speed"
    keep_history: bool = False
    keep_audio_history: bool = False
    remember_desktop: bool = True
    onboarding_done: bool = False
    model_setup: str = "pending"
    desktop_setup_done: bool = False
    hotkey: str = "Meta+H"
    reduced_transparency: bool = False
    sound_feedback: bool = True
    popup_enabled: bool = True
    cpu_threads: int = field(default_factory=lambda: os.cpu_count() or 1)
    dictionary: str = ""
    vad: bool = True

    def validate(self):
        from .models import CATALOG
        if self.model not in CATALOG or CATALOG[self.model].kind != "asr":
            raise ValueError("Unknown speech model")
        for key, default in asdict(Settings()).items():
            if type(getattr(self, key)) is not type(default):
                raise ValueError(f"Invalid type for {key}")
        for key, allowed in _CHOICES.items():
            if getattr(self, key) not in allowed:
                raise ValueError(f"Invalid {key}: {getattr(self, key)}")
        if not 1 <= self.cpu_threads <= max(1, os.cpu_count() or 1):
            raise ValueError("CPU threads exceed the available processors")
        return self


_CHOICES = {"device": {"auto", "cpu", "gpu", "npu"}, "language": {"auto", "Thai", "English"},
            "profile": {"raw", "smart", "th_to_eng"}, "paste_mode": {"review", "immediate"},
            "preference": {"speed", "power"},
            "model_setup": {"pending", "downloading", "paused", "complete", "skipped"}}
# An upgrade is not a new installation. Never download a model the user
# removed, change paste behavior, or re-prompt for desktop permissions.
_UPGRADE = {"model_setup": "skipped", "desktop_setup_done": True, "remember_desktop": False, "paste_mode": "review"}


def _backup(path: Path):
    data = path.read_bytes()
    for old in path.parent.glob(f"{path.name}.bak-*"):
        if old.read_bytes() == data:
            return old
    target = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-{n}")
        n += 1
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return target


def load_settings_with_report() -> tuple[Settings, list[str]]:
    """Load settings, replacing invalid fields with defaults; warnings are user-facing Thai."""
    from .models import CATALOG
    path = config_path()
    if not path.exists():
        return Settings(), []
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("not an object")
    except (OSError, ValueError, UnicodeDecodeError):
        warnings = ["ไฟล์ตั้งค่าเสียหาย ใช้ค่าเริ่มต้นแทน"]
        try:
            warnings[0] += f" (สำรองไว้ที่ {_backup(path)})"
        except OSError:
            pass
        return Settings(**_UPGRADE), warnings
    if values.get("version", 2) != 2:
        raise ValueError("Settings were written by an unsupported application version")
    for key, value in _UPGRADE.items():
        values.setdefault(key, value)
    defaults = asdict(Settings())
    fields, warnings = {}, []
    for key, default in defaults.items():
        if key not in values:
            continue
        value = values[key]
        if type(value) is not type(default) or value not in _CHOICES.get(key, (value,)):
            ok = False
        elif key == "model":
            ok = value in CATALOG and CATALOG[value].kind == "asr"
        elif key == "cpu_threads":
            ok = 1 <= value <= max(1, os.cpu_count() or 1)
            if not ok and type(value) is int:
                fields[key] = min(max(1, value), default)
                warnings.append(f"ตั้งค่า {key} ไม่ถูกต้อง ปรับเป็น {fields[key]} แทน")
                continue
        else:
            ok = True
        if ok:
            fields[key] = value
        else:
            warnings.append(f"ตั้งค่า {key} ไม่ถูกต้อง ใช้ค่าเริ่มต้นแทน")
    if warnings:
        try:
            _backup(path)
        except OSError:
            pass
    return Settings(**fields).validate(), warnings


def load_settings() -> Settings:
    return load_settings_with_report()[0]


def save_settings(settings: Settings):
    settings.validate()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as f:
        json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
        temp = Path(f.name)
    temp.replace(path)
