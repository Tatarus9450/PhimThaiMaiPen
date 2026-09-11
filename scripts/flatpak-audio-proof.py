#!/usr/bin/env python3
"""Exercise packaged capture/removal using owned virtual microphones only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.tatarus9450.PhimThaiMaiPen"
parser = argparse.ArgumentParser()
parser.add_argument("--child", choices=["capture", "disconnect"])
parser.add_argument("--source")
parser.add_argument("--directory")
parser.add_argument("--input", default=str(ROOT / ".cache/benchmark/10021525843523202225.wav"))
args = parser.parse_args()

if args.child:
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtMultimedia import QMediaDevices
    from phimthai.audio import Recorder
    directory = Path(args.directory)
    app = QCoreApplication([])
    # Require the source-built safety library, whose Pulse capture refuses moves.
    built = Path("/app/lib/libQt6Multimedia.so.6.11.1")
    loaded = {Path(line.split()[-1]) for line in Path("/proc/self/maps").read_text().splitlines()
              if "/libQt6Multimedia.so." in line}
    if not built.is_file() or not loaded or any(built.read_bytes() != actual.read_bytes() for actual in loaded):
        raise SystemExit("Patched Qt library not installed; refusing microphone test")
    device = next((d for d in QMediaDevices.audioInputs() if bytes(d.id()).decode() == args.source), None)
    if device is None:
        raise SystemExit("Owned virtual source absent; refusing any fallback")
    recorder = Recorder()
    errors, levels = [], []
    recorder.failed.connect(errors.append)
    recorder.level.connect(levels.append)
    recorder.start(directory / (args.child + ".wav"), bytes(device.id()).hex())
    (directory / "ready").write_text("ready")
    started = time.monotonic()

    def finish():
        stopped_on_error = recorder.source is None and bool(errors)
        captured = recorder.stop()
        with wave.open(str(directory / (args.child + ".wav"))) as audio:
            duration = audio.getnframes() / audio.getframerate()
        report = {"mode": args.child, "duration": duration, "captured": captured,
                  "errors": errors, "maximum_level_percent": max(levels or [0]),
                  "stopped_on_disconnect": stopped_on_error, "wall_seconds": time.monotonic() - started,
                  "library_sha256": hashlib.sha256(built.read_bytes()).hexdigest()}
        (directory / (args.child + ".json")).write_text(json.dumps(report, indent=2))
        valid = stopped_on_error if args.child == "disconnect" else captured and not errors and max(levels or [0]) > 0
        app.exit(0 if valid else 1)

    if args.child == "disconnect":
        recorder.failed.connect(lambda _message: QTimer.singleShot(0, finish))
    QTimer.singleShot(7000 if args.child == "disconnect" else 10500, finish)
    raise SystemExit(app.exec())

owned_modules = []
reports = []
name = "phimthai_proof_" + uuid.uuid4().hex[:10]

def pactl(*arguments):
    return subprocess.check_output(["pactl", *arguments], text=True).strip()

with tempfile.TemporaryDirectory(prefix="phimthai-audio-proof-") as temporary:
    directory = Path(temporary)
    child = player = None
    try:
        owned_modules.append(pactl("load-module", "module-null-sink", f"sink_name={name}"))
        source_module = pactl("load-module", "module-remap-source", f"master={name}.monitor", f"source_name={name}_source")
        owned_modules.append(source_module)
        for mode in ("capture", "disconnect"):
            (directory / "ready").unlink(missing_ok=True)
            command = ["flatpak", "run", f"--filesystem={directory}", f"--filesystem={ROOT / 'scripts'}:ro",
                       "--command=python3", APP_ID, str(Path(__file__).resolve()), "--child", mode,
                       "--source", name + "_source", "--directory", str(directory)]
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 15
            while not (directory / "ready").exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if not (directory / "ready").exists():
                raise RuntimeError("Packaged capture did not become ready")
            if mode == "capture":
                player = subprocess.Popen(["paplay", "--device=" + name, args.input])
            else:
                time.sleep(1)
                pactl("unload-module", source_module)
                owned_modules.remove(source_module)
            output, error = child.communicate(timeout=20)
            if child.returncode:
                raise RuntimeError(f"{mode} failed: {output} {error}")
            reports.append(json.loads((directory / (mode + ".json")).read_text()))
            if player:
                player.wait(timeout=5)
                player = None
    finally:
        for process in (child, player):
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        for module in reversed(owned_modules):
            pactl("unload-module", module)

report = {"environment": "Installed Flatpak on Fedora KDE Wayland, PulseAudio portal socket",
          "physical_microphone_opened": False, "source": "Owned virtual source; public FLEURS input",
          "tests": reports, "owned_virtual_modules_removed": True}
(ROOT / "docs/evidence/flatpak-audio.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
