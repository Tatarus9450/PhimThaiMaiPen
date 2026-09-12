"""Versioned user settings, independent of an application's installation path."""
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "phimthai"


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "phimthai/settings.json"


@dataclass
class Settings:
    version: int = 2
    model: str = "qwen-0.6b"
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
    cpu_threads: int = field(default_factory=lambda: min(6, os.cpu_count() or 1))
    dictionary: str = ""
    vad: bool = True

    def validate(self):
        from .models import CATALOG
        if self.model not in CATALOG or CATALOG[self.model].kind != "asr":
            raise ValueError("Unknown speech model")
        for key, default in asdict(Settings()).items():
            if type(getattr(self, key)) is not type(default):
                raise ValueError(f"Invalid type for {key}")
        choices = {"device": {"auto", "cpu", "gpu", "npu"}, "language": {"auto", "Thai", "English"},
                   "profile": {"raw", "smart", "th_to_eng"}, "paste_mode": {"review", "immediate"},
                   "preference": {"speed", "power"},
                   "model_setup": {"pending", "downloading", "paused", "complete", "skipped"}}
        for key, allowed in choices.items():
            if getattr(self, key) not in allowed:
                raise ValueError(f"Invalid {key}: {getattr(self, key)}")
        if not 1 <= self.cpu_threads <= max(1, os.cpu_count() or 1):
            raise ValueError("CPU threads exceed the available processors")
        return self


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        return Settings(cpu_threads=min(6, os.cpu_count() or 1))
    values = json.loads(path.read_text(encoding="utf-8"))
    if values.get("version", 2) != 2:
        raise ValueError("Settings were written by an unsupported application version")
    # An upgrade is not a new installation. Never download a model the user
    # removed, change paste behavior, or re-prompt for desktop permissions.
    values.setdefault("model_setup", "skipped")
    values.setdefault("desktop_setup_done", True)
    values.setdefault("remember_desktop", False)
    values.setdefault("paste_mode", "review")
    return Settings(**{k: v for k, v in values.items() if k in Settings.__dataclass_fields__}).validate()


def save_settings(settings: Settings):
    settings.validate()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as f:
        json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
        temp = Path(f.name)
    temp.replace(path)
