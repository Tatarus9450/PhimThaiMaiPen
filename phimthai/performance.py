"""Only compare measurements for the same machine and model."""
import json
import platform
import statistics
from .settings import data_dir


def machine_key():
    from pathlib import Path
    name = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), platform.machine())
    return name + " / " + platform.release()


def measurements():
    try:
        data = json.loads((data_dir() / "performance.json").read_text())
        values = data.get(machine_key(), {})
        if not isinstance(values, dict):
            return {}
        return {model: {device: [v for v in entries if type(v) in (int, float) and 0 < v < 10000]
                        for device, entries in devices.items() if isinstance(entries, list)}
                for model, devices in values.items() if isinstance(devices, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def record(model, device, result):
    duration = result.get("audio_duration", 0)
    seconds = result.get("processing_time", 0)
    if duration < 2 or seconds <= 0:
        return
    values = measurements()
    entries = values.setdefault(model, {}).setdefault(device, [])
    entries.append(round(seconds / duration, 4))
    values[model][device] = entries[-20:]
    path = data_dir() / "performance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps({machine_key(): values}, indent=2))
    pending.replace(path)


def choose(model, candidates, preference):
    # Power readings are unavailable: CPU is a compatibility default, never
    # advertised as measured most efficient. Experimental NPU is excluded.
    if preference == "power":
        return "cpu", "No energy measurements available; using CPU"
    values = measurements().get(model, {})
    measured = {device: statistics.median(values[device]) for device in candidates if len(values.get(device, [])) >= 3}
    if len(measured) > 1:
        selected = min(measured, key=measured.get)
        return selected, "Auto selected from processing times measured on this machine"
    return "cpu", "Auto uses CPU until comparable device measurements are available"
