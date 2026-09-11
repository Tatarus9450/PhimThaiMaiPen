#!/usr/bin/env python3
"""Small, reproducible FLEURS baseline. Not a representative accuracy certification."""
import argparse
import hashlib
import io
import json
import re
import resource
import statistics
import sys
import tarfile
import time
import unicodedata
import urllib.request
from pathlib import Path

REV = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
SAMPLES = [
    ("th_th", "10021525843523202225.wav", "d3c1f7278bb82f716a5ef7b804959d3ad655cf4790be0fc432a12de962d8a2d8"),
    ("th_th", "10026868752543983818.wav", "d774e3bb5370542c316ae458aa819900d2e0e9737ba9046804ee416ef7339de6"),
    ("en_us", "1003119935936341070.wav", "33aca50159ec2e3cbcc894eb26faa916d6badb1b49fb75994973561540a7f012"),
    ("en_us", "10052240106321793346.wav", "7603cae3294309ef70d234180cefccc3b13865ee525262228a636069b9b62841"),
]


def fetch_samples(directory):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for language in ("th_th", "en_us"):
        base = f"https://huggingface.co/datasets/google/fleurs/resolve/{REV}/data/{language}"
        references = urllib.request.urlopen(base + "/test.tsv", timeout=60).read().decode("utf-8")
        rows = {r.split("\t")[1]: r.split("\t")[2] for r in references.splitlines()}
        needed = {name: sha for lang, name, sha in SAMPLES if lang == language}
        if any(not (directory / name).exists() for name in needed):
            request = urllib.request.Request(base + "/audio/test.tar.gz", headers={"Range": "bytes=0-2097151"})
            with urllib.request.urlopen(request, timeout=60) as response:
                compressed = response.read(2097152)
            with tarfile.open(fileobj=io.BytesIO(compressed), mode="r|gz") as archive:
                for member in archive:
                    name = Path(member.name).name
                    if name in needed:
                        data = archive.extractfile(member).read()
                        if hashlib.sha256(data).hexdigest() != needed[name]:
                            raise RuntimeError("Sample hash mismatch")
                        (directory / name).write_bytes(data)
                    if all((directory / name).exists() for name in needed):
                        break
        for name, sha in needed.items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != sha:
                raise RuntimeError("Sample hash mismatch")
            manifest.append({"language": language, "file": name, "reference": rows[name], "sha256": sha})
    return manifest


def normalize(text, language):
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(c if not unicodedata.category(c).startswith("P") else " " for c in text)
    return list("".join(text.split())) if language.startswith("th") else text.split()


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = next_row
    return row[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--cache", default=str(Path(__file__).resolve().parent.parent / ".cache/benchmark"))
    args = parser.parse_args()
    sys.path.insert(0, args.source)
    import typhoon_service as service
    service.CONFIG["TYPHOON_CPU_THREADS"] = str(args.threads)
    manifest = fetch_samples(Path(args.cache))
    started = time.perf_counter()
    service.load_model()
    startup = time.perf_counter() - started
    results = []
    for item in manifest:
        response = service.transcribe_audio(Path(args.cache) / item["file"], "raw")
        reference = normalize(item["reference"], item["language"])
        hypothesis = normalize(response["text"], item["language"])
        result = dict(item, hypothesis=response["text"], errors=distance(reference, hypothesis),
                      units=len(reference), processing_time=response["processing_time"], duration=response["audio_duration"])
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {"dataset": "Google FLEURS", "revision": REV, "license": "CC-BY-4.0", "threads": args.threads,
              "model": service.CONFIG["TYPHOON_MODEL"], "startup_seconds": startup,
              "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
              "normalization": "Unicode NFC, lowercase, punctuation replaced with spaces; Thai removes whitespace for CER, English whitespace tokens for WER",
              "limitation": "Four samples only, not representative or natural code-switching", "samples": results}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
