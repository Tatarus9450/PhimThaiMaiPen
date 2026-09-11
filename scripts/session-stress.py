#!/usr/bin/env python3
"""Exercise real inference workers with unique audio files and job IDs."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QCoreApplication, QTimer
from phimthai.jobs import JobController
from phimthai.settings import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="whisper-turbo-amd")
parser.add_argument("--device", default="npu")
parser.add_argument("--count", type=int, default=100)
parser.add_argument("--output", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
files = sorted((root / ".cache/benchmark").glob("*.wav"))
if len(files) != 4:
    raise SystemExit("Run benchmark.py to prepare the four pinned public fixtures")
app = QCoreApplication([])
temporary = tempfile.TemporaryDirectory(prefix="phimthai-stress-", dir=os.environ.get("XDG_RUNTIME_DIR"))
jobs = JobController(temp_root=temporary.name)
settings = Settings(model=args.model, device=args.device, profile="raw")
submitted, responses, failures, pids = {}, [], [], set()


def submit():
    i = len(submitted)
    if i == args.count:
        return
    source = files[i % len(files)]
    audio = Path(temporary.name) / f"job-{i}.wav"
    shutil.copyfile(source, audio)
    job_id = jobs.submit(settings, action="transcribe", audio=str(audio))
    submitted[job_id] = {"source": source.name, "temporary_audio": str(audio)}


def finish():
    jobs.cancel()
    temporary.cleanup()
    report = {"requested": args.count, "completed": len(responses), "unique_ids": len({r["id"] for r in responses}),
              "worker_pids": sorted(pids), "failures": failures, "temporary_directory_removed": not Path(temporary.name).exists(),
              "scope": "Real ASR via Qt worker with unique audio files; microphone and paste are separate tests", "results": responses}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    app.exit(0 if len(responses) == args.count and not failures else 1)


def received(result):
    if result["id"] not in submitted or any(r["id"] == result["id"] for r in responses):
        failures.append("Unknown or duplicate job ID")
        finish()
        return
    pids.add(jobs.worker_pid)
    item = dict(result, source_file=submitted[result["id"]]["source"])
    item.pop("settings", None)
    responses.append(item)
    print(json.dumps({"completed": len(responses), "device": result.get("device")}), flush=True)
    Path(submitted[result["id"]]["temporary_audio"]).unlink(missing_ok=True)
    if len(responses) == args.count:
        QTimer.singleShot(0, finish)
    else:
        QTimer.singleShot(0, submit)


jobs.result.connect(received)
jobs.failed.connect(lambda message: (failures.append(message), finish()))
QTimer.singleShot(0, submit)
raise SystemExit(app.exec())
