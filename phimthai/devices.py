"""Capability detection does not certify successful model inference."""
import importlib.util
import os
import platform
from pathlib import Path
from functools import lru_cache
from .settings import DEFAULT_MODEL


@lru_cache(maxsize=1)
def openvino_devices():
    try:
        import openvino
        return openvino.Core().available_devices
    except Exception:
        return []


def inventory():
    npus = []
    for device in Path("/sys/class/accel").glob("accel[0-9]*"):
        driver = device / "device/driver"
        npus.append({"device": device.name, "driver": driver.resolve().name if driver.exists() else "unknown",
                     "status": "detected", "asr_verified": False})
    return {"system": platform.platform(), "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "cpu_threads": os.cpu_count(), "npu": npus,
            "openvino_installed": importlib.util.find_spec("openvino") is not None,
            "openvino_devices": openvino_devices(),
            "flatpak": Path("/.flatpak-info").exists()}


def select_device(requested, torch, model=DEFAULT_MODEL, preference="speed"):
    if requested == "npu":
        raise RuntimeError("This model has no verified NPU backend. Choose Auto or CPU. Detected NPU hardware alone is not sufficient.")
    if requested == "auto":
        # Accelerators are opt-in Beta, including when old measurements exist.
        return "cpu", ""
    if requested == "gpu" and torch.cuda.is_available():
        return "cuda", ""
    if requested == "gpu":
        return "cpu", "Compatible GPU unavailable; using CPU"
    return "cpu", ""
