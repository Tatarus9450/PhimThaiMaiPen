#!/usr/bin/env python3
"""Interrupt a real pinned model download, prove HTTP byte-range resume and hashes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--child", action="store_true")
parser.add_argument("--events")
parser.add_argument("--report", default=str(ROOT / "docs/evidence/model-resume.json"))
args = parser.parse_args()

if args.child:
    import huggingface_hub.file_download as fetch
    from phimthai.models import download, local_model
    original = fetch._request_wrapper
    # Smaller HTTP chunks only slow this test enough to interrupt deterministically.
    fetch.constants.DOWNLOAD_CHUNK_SIZE = 65536

    def request(*a, **kw):
        response = original(*a, **kw)
        if kw.get("method") == "GET":
            with open(args.events, "a") as events:
                events.write(json.dumps({"range": (kw.get("headers") or {}).get("Range"),
                                         "status": response.status_code}) + "\n")
            iterate = response.iter_content
            def chunks(*ca, **ck):
                for chunk in iterate(*ca, **ck):
                    time.sleep(0.004)
                    yield chunk
            response.iter_content = chunks
        return response

    fetch._request_wrapper = request
    download("whisper-tiny-ov")
    if not local_model("whisper-tiny-ov", verify=True):
        raise SystemExit("Downloaded model failed verification")
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix="phimthai-download-proof-") as temporary:
    directory = Path(temporary)
    environment = dict(os.environ, XDG_DATA_HOME=str(directory / "data"),
                       HF_HOME=str(directory / "hf"), HF_HUB_DISABLE_XET="1",
                       HF_HUB_DISABLE_PROGRESS_BARS="1")
    events = directory / "events.jsonl"
    command = [sys.executable, str(Path(__file__).resolve()), "--child", "--events", str(events)]
    first = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    interrupted_bytes = 0
    try:
        deadline = time.monotonic() + 120
        while first.poll() is None and time.monotonic() < deadline:
            for incomplete in directory.rglob("*.incomplete"):
                try:
                    size = incomplete.stat().st_size
                except FileNotFoundError:
                    continue
                if size >= 1_048_576:
                    interrupted_bytes = size
                    break
            if interrupted_bytes:
                break
            time.sleep(0.03)
    finally:
        if first.poll() is None:
            first.kill()
        first.wait(timeout=10)
    if not interrupted_bytes:
        raise SystemExit("No partial download observed; test did not establish resume")
    events.write_text("")
    second = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=240)
    requests = [json.loads(line) for line in events.read_text().splitlines()]
    ranges = [r for r in requests if r["range"] and r["range"] != "bytes=0-" and r["status"] == 206]
    report = {"model": "whisper-tiny-ov", "interrupted_bytes_observed": interrupted_bytes,
              "restart_exit_code": second.returncode, "resumed_http_requests": ranges,
              "verified_after_resume": second.returncode == 0, "isolated_data": True,
              "test_only_changes": "HTTP chunks 64 KiB with 4 ms delay; Xet disabled to observe Range headers"}
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    if second.returncode or not ranges:
        print(second.stderr[-2000:], file=sys.stderr)
        raise SystemExit(1)
