#!/usr/bin/env python3
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

BASE = Path(__file__).parent.resolve()
SOCKET_FILE = Path("/tmp/voice_agent_typhoon.sock")
SERVICE_PID_FILE = Path("/tmp/voice_agent_typhoon.pid")
SERVICE_LOG_FILE = Path("/tmp/voice_agent_typhoon.log")
PROFILE_FILE = Path("/tmp/voice_agent_profile")

DEFAULT_CONFIG = {
    "POPUP_ENABLED": "true",
    "TYPHOON_MODEL": "Qwen/Qwen3-ASR-0.6B",
    "TYPHOON_ASR_BACKEND": "auto",
    "TYPHOON_ASR_LANGUAGE": "auto",
    "TYPHOON_TRANSLATE_MODEL": "Helsinki-NLP/opus-mt-th-en",
    "TYPHOON_DEVICE": "auto",
    "TYPHOON_CPU_THREADS": str(os.cpu_count() or 4),
    "TYPHOON_VENV": str((BASE / ".venv").resolve()),
    "TYPHOON_HF_HOME": str((BASE / ".cache" / "huggingface").resolve()),
    "TYPHOON_PROFILE_DEFAULT": "smart",
    "TYPHOON_REQUEST_TIMEOUT": "300",
    "TYPHOON_STARTUP_TIMEOUT": "600",
    "TYPHOON_FFMPEG_TIMEOUT": "30",
    "TYPHOON_REPLACEMENTS_FILE": str((BASE / "typhoon_replacements.tsv").resolve()),
}

PATH_KEYS = {"TYPHOON_VENV", "TYPHOON_HF_HOME", "TYPHOON_REPLACEMENTS_FILE"}


def get_asr_backend(config: dict[str, str]) -> str:
    backend = config.get("TYPHOON_ASR_BACKEND", "auto").strip().lower()
    if backend == "auto":
        model = config.get("TYPHOON_MODEL", DEFAULT_CONFIG["TYPHOON_MODEL"])
        return "qwen" if "qwen3-asr" in model.lower() else "typhoon"
    if backend not in {"qwen", "typhoon"}:
        raise ValueError(f"Unsupported TYPHOON_ASR_BACKEND: {backend}")
    return backend


def _strip_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _expand_path(value: str) -> str:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = (BASE / expanded).resolve()
    return str(expanded)


def load_config() -> dict[str, str]:
    config = dict(DEFAULT_CONFIG)
    config_path = BASE / "config.env"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            value = _strip_value(raw_value)
            if key:
                config[key] = value

    for key in PATH_KEYS:
        if key in config:
            config[key] = _expand_path(config[key])

    return config


def config_bool(config: dict[str, str], key: str, default: bool = False) -> bool:
    value = config.get(key, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def normalize_profile(value: str | None) -> str:
    if not value:
        return "smart"
    normalized = value.strip().lower()
    if normalized == "raw":
        return "raw"
    if normalized in {"th_to_eng", "th-to-eng", "th2eng", "translate"}:
        return "th_to_eng"
    return "smart"


def get_active_profile(config: dict[str, str] | None = None) -> str:
    config = config or load_config()
    if PROFILE_FILE.exists():
        return normalize_profile(PROFILE_FILE.read_text(encoding="utf-8", errors="ignore"))

    profile = normalize_profile(config.get("TYPHOON_PROFILE_DEFAULT", "smart"))
    PROFILE_FILE.write_text(profile, encoding="utf-8")
    return profile


def set_active_profile(profile: str) -> str:
    normalized = normalize_profile(profile)
    PROFILE_FILE.write_text(normalized, encoding="utf-8")
    return normalized


def get_service_python(config: dict[str, str] | None = None) -> Path:
    config = config or load_config()
    venv_path = Path(config["TYPHOON_VENV"])
    return venv_path / "bin" / "python"


def _read_pid() -> int | None:
    try:
        return int(SERVICE_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def send_request(payload: dict, timeout: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(SOCKET_FILE))
        client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")

        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break

    if not chunks:
        raise RuntimeError("Typhoon service closed the connection without a response.")

    raw = b"".join(chunks).split(b"\n", 1)[0]
    response = json.loads(raw.decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Typhoon service request failed."))
    return response


def ping_service(timeout: float = 0.3) -> bool:
    if not SOCKET_FILE.exists():
        return False
    try:
        send_request({"action": "ping"}, timeout=timeout)
    except Exception:
        return False
    return True


def _wait_for_service(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ping_service(timeout=0.5):
            return True

        pid = _read_pid()
        if pid is not None and not _pid_alive(pid):
            break
        time.sleep(0.25)

    return ping_service(timeout=0.5)


def _clear_service_state() -> None:
    SOCKET_FILE.unlink(missing_ok=True)
    SERVICE_PID_FILE.unlink(missing_ok=True)


def _spawn_service(config: dict[str, str]) -> None:
    python_bin = get_service_python(config)
    if not python_bin.exists():
        raise FileNotFoundError(
            f"Typhoon environment is missing: {python_bin}. Run ./install.sh first."
        )

    with SERVICE_LOG_FILE.open("ab") as log_file:
        proc = subprocess.Popen(
            [str(python_bin), str(BASE / "typhoon_service.py")],
            cwd=str(BASE),
            start_new_session=True,
            stdout=log_file,
            stderr=log_file,
        )
    SERVICE_PID_FILE.write_text(str(proc.pid), encoding="utf-8")


def stop_service(timeout: float = 5.0) -> bool:
    pid = _read_pid()
    was_running = _pid_alive(pid)

    if was_running and pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            was_running = False

        deadline = time.time() + timeout
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.1)

        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

            deadline = time.time() + 2.0
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.1)

    _clear_service_state()
    return was_running


def ensure_service(wait: bool = True, timeout: float | None = None) -> bool:
    config = load_config()
    timeout = timeout if timeout is not None else float(config["TYPHOON_STARTUP_TIMEOUT"])

    if ping_service(timeout=0.5):
        return True

    pid = _read_pid()
    if _pid_alive(pid):
        if not wait:
            return False
        if _wait_for_service(timeout):
            return True
        stop_service(timeout=5.0)
    else:
        _clear_service_state()

    _spawn_service(config)

    if not wait:
        return False

    if _wait_for_service(timeout):
        return True

    stop_service(timeout=2.0)
    raise RuntimeError(f"Typhoon service failed to start. Check {SERVICE_LOG_FILE}.")


def transcribe_audio(
    audio_path: str | Path,
    profile: str | None = None,
    timeout: float | None = None,
) -> dict:
    config = load_config()
    ensure_service(wait=True, timeout=float(config["TYPHOON_STARTUP_TIMEOUT"]))

    request_timeout = timeout if timeout is not None else float(config["TYPHOON_REQUEST_TIMEOUT"])
    active_profile = normalize_profile(profile or get_active_profile(config))

    return send_request(
        {
            "action": "transcribe",
            "audio_path": str(Path(audio_path).resolve()),
            "profile": active_profile,
        },
        timeout=request_timeout,
    )
