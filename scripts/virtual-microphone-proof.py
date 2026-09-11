#!/usr/bin/env python3
"""Capture public test audio ONLY from an explicitly named virtual source."""
import argparse
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

os.environ.setdefault("QT_AUDIO_BACKEND", "pulseaudio")
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtMultimedia import QMediaDevices
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phimthai.audio import Recorder

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--report", required=True)
args = parser.parse_args()
app = QCoreApplication([])
device = next((d for d in QMediaDevices.audioInputs() if bytes(d.id()) == b"phimthai_test_source"), None)
if device is None:
    raise SystemExit("Isolated virtual source not found; refusing to select another microphone")
recorder = Recorder()
levels, errors = [], []
recorder.level.connect(levels.append)
recorder.failed.connect(errors.append)
recorder.start(Path(args.output), bytes(device.id()).hex())
player = None


def play():
    global player
    player = subprocess.Popen(["paplay", "--device=phimthai_test", args.input])


def finish():
    captured = recorder.stop()
    if player and player.poll() is None:
        player.terminate()
        player.wait(timeout=5)
    with wave.open(args.output, "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        report = {"source": "isolated virtual source with public test audio", "captured": captured,
                  "sample_rate": audio.getframerate(), "channels": audio.getnchannels(),
                  "duration": duration, "maximum_level_percent": max(levels or [0]), "errors": errors}
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    app.exit(0 if captured and not errors and max(levels or [0]) > 0 else 1)


QTimer.singleShot(600, play)
QTimer.singleShot(10000, finish)
raise SystemExit(app.exec())
