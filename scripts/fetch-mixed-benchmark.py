#!/usr/bin/env python3
"""Fetch only four pinned TVSpeech rows, checking reference, revision and WAV hash."""
import argparse
import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def get_json(url):
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if attempt or error.code not in (429, 500, 502, 503, 504):
                raise
    raise RuntimeError("Metadata request did not complete")


def fetch(manifest, output):
    output.mkdir(parents=True, exist_ok=True)
    pages = {}
    for sample in manifest["samples"]:
        target = output / sample["file"]
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != sample["sha256"]:
                raise RuntimeError(f"Existing file hash mismatch: {target}")
            print(f"Verified {target.name}")
            continue
        offset = sample["row_idx"] // 100 * 100
        if offset not in pages:
            query = urllib.parse.urlencode(dict(dataset=manifest["dataset"],
                config=manifest["config"], split=manifest["split"], offset=offset, length=100))
            page = get_json("https://datasets-server.huggingface.co/rows?" + query)
            pages[offset] = {row["row_idx"]: row["row"] for row in page["rows"]}
        row = pages[offset][sample["row_idx"]]
        if row["audio_id"] != sample["audio_id"] or row["sentence"] != sample["reference"]:
            raise RuntimeError("Viewer row/reference drift; use the pinned Parquet in manifest")
        asset = row["audio"][0]["src"]
        parsed = urllib.parse.urlparse(asset)
        expected = f'/cached-assets/{manifest["dataset"]}/--/{manifest["revision"]}/--/'
        if parsed.scheme != "https" or parsed.netloc != "datasets-server.huggingface.co" or not urllib.parse.unquote(parsed.path).startswith(expected):
            raise RuntimeError("Viewer asset revision drift; refusing different data")
        with urllib.request.urlopen(asset, timeout=30) as response:
            announced = response.headers.get("Content-Length")
            if announced is not None and int(announced) != sample["bytes"]:
                raise RuntimeError("Unexpected WAV size")
            audio = response.read(sample["bytes"] + 1)
        if len(audio) != sample["bytes"] or hashlib.sha256(audio).hexdigest() != sample["sha256"]:
            raise RuntimeError("Downloaded WAV integrity mismatch")
        with tempfile.NamedTemporaryFile(dir=output, prefix=".tvspeech-", delete=False) as temporary:
            temporary.write(audio)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)
        print(f"Fetched and verified {target.name} ({len(audio)} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    parser.add_argument("--manifest", type=Path, default=root / "docs/evidence/tvspeech-mixed-subset.json")
    parser.add_argument("--output", type=Path, default=root / ".cache/benchmark-mixed")
    args = parser.parse_args()
    fetch(json.loads(args.manifest.read_text()), args.output)
