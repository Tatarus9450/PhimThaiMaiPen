#!/usr/bin/env python3
"""Install a reviewed local FastFlowLM build with its license/provenance intact."""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phimthai.settings import data_dir

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
args = parser.parse_args()
source = args.source.resolve()
for required in ("flm", "flm-real", "lib", "LICENSE_RUNTIME.txt", "NOTICE-PHIMTHAI.txt", "proof/source-build.json"):
    if not (source / required).exists():
        raise SystemExit(f"Incomplete reviewed runtime: {required}")
for path in source.rglob("*"):
    if path.is_symlink() and not path.resolve().is_relative_to(source):
        raise SystemExit("Runtime contains an external symbolic link")
target = data_dir() / "runtimes/fastflowlm"
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    raise SystemExit("Runtime already installed. Stop the app and move the old runtime aside before upgrading.")
with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
    staged = Path(temporary) / "fastflowlm"
    shutil.copytree(source, staged, symlinks=True)
    marker = {"version": "1.0.5", "profile": "phimthai-language-prefix-and-timestamp-fix",
              "binary_sha256": hashlib.sha256((staged / "flm-real").read_bytes()).hexdigest(),
              "status": "experimental", "provenance": "proof/source-build.json"}
    (staged / "phimthai-runtime.json").write_text(json.dumps(marker, indent=2))
    staged.rename(target)
print(target)
