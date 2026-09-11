#!/usr/bin/env python3
"""Small natural Thai-English challenge set; not a representative benchmark."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from phimthai.settings import Settings
from phimthai.worker import run
from benchmark import normalize, distance

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="qwen-0.6b")
parser.add_argument("--device", default="cpu")
parser.add_argument("--threads", type=int, default=6)
parser.add_argument("--output", required=True)
parser.add_argument("--concurrent-builds", action="store_true")
args = parser.parse_args()
manifest = json.loads((ROOT / "docs/evidence/tvspeech-mixed-subset.json").read_text())
settings = Settings(model=args.model, device=args.device, cpu_threads=args.threads, profile="raw")
results = []
try:
    for sample in manifest["samples"]:
        path = ROOT / ".cache/benchmark-mixed" / sample["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample["sha256"]:
            raise SystemExit("Input hash mismatch")
        started = time.perf_counter()
        result = run({"action": "transcribe", "audio": str(path), "settings": asdict(settings)})
        reference, actual = normalize(sample["reference"], "th"), normalize(result["text"], "th")
        result.update(file=sample["file"], reference=sample["reference"], elapsed=time.perf_counter() - started,
                      errors=distance(reference, actual), units=len(reference))
        results.append(result)
        print(json.dumps({"file": sample["file"], "errors": result["errors"], "units": result["units"],
                          "device": result["device"], "elapsed": result["elapsed"]}), flush=True)
finally:
    from phimthai.fastflowlm_backend import stop
    stop()

report = {"dataset": manifest["dataset"], "revision": manifest["revision"],
          "selection": manifest["selection"], "model": args.model, "device": args.device,
          "cpu_threads": args.threads, "concurrent_builds": args.concurrent_builds,
          "timing_caveat": "Concurrent builds make these timings unsuitable for a speed comparison" if args.concurrent_builds else "Small sample; cold first job included",
          "normalization": "NFC/lowercase/punctuation removed/whitespace removed; character error rate includes both Thai and Latin characters",
          "errors": sum(r["errors"] for r in results), "units": sum(r["units"] for r in results),
          "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
          "samples": results}
Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
