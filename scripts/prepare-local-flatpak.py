#!/usr/bin/env python3
"""Prepare an experimental offline Flatpak from resolved local wheels.

This is an integration-test bundle, NOT the source-compliant Flathub manifest.
Run packaging/requirements-local.txt resolution inside org.kde.Sdk 6.11 first.
"""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.tatarus9450.PhimThaiMaiPen"
cache = ROOT / ".cache"
cache.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("--source-pyside", action="store_true", help="Use the verified local source-build UI artifact")
args = parser.parse_args()
source = cache / "flatpak-source.tar.gz"


def include(member):
    return None if "__pycache__" in member.name or member.name.endswith(".pyc") else member


with tarfile.open(source, "w:gz") as archive:
    for name in ("phimthai", "typhoon_backend.py", "typhoon_service.py", "pyproject.toml", "README.md", "LICENSE",
                 "packaging/requirements-local.txt", "packaging/patch-qwen.py"):
        archive.add(ROOT / name, arcname=name, filter=include)

manifest = {
    "app-id": APP_ID, "runtime": "org.kde.Platform", "runtime-version": "6.11", "sdk": "org.kde.Sdk",
    "command": "phimthai", "finish-args": ["--socket=wayland", "--socket=fallback-x11", "--share=ipc",
        "--socket=pulseaudio", "--share=network", "--device=dri", "--env=QT_AUDIO_BACKEND=pulseaudio",
        "--env=QT_PLUGIN_PATH=/app/lib/plugins:/usr/lib/plugins"],
    "build-options": {"env": {"PYTHONPATH": "/app/lib/python3.13/site-packages"}},
    "modules": [{"name": "krb5", "subdir": "src", "config-opts": ["--disable-static", "--disable-rpath", "--without-keyutils", "--without-libedit"],
        "sources": [{"type": "archive", "url": "https://kerberos.org/dist/krb5/1.22/krb5-1.22.2.tar.gz",
            "sha256": "3243ffbc8ea4d4ac22ddc7dd2a1dc54c57874c40648b60ff97009763554eaf13"}]},
        {"name": "phimthai-local-experiment", "buildsystem": "simple", "build-commands": [
        "python3 -m pip install --ignore-installed --no-index --find-links=wheels --no-build-isolation --prefix=/app -r packaging/requirements-local.txt",
        "python3 -m pip install --no-index --no-deps --prefix=/app wheels/qwen_asr-0.0.6-py3-none-any.whl",
        "python3 packaging/patch-qwen.py",
        "install -m755 /app/lib/libQt6Multimedia.so.6.11.1 /app/lib/python3.13/site-packages/PySide6/Qt/lib/libQt6Multimedia.so.6",
        "install -m755 /app/lib/plugins/multimedia/libffmpegmediaplugin.so /app/lib/python3.13/site-packages/PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.so",
        "python3 -m pip install --no-index --no-deps --no-build-isolation --prefix=/app .",
        f"install -Dm644 phimthai/assets/{APP_ID}.desktop /app/share/applications/{APP_ID}.desktop",
        f"install -Dm644 phimthai/assets/{APP_ID}.metainfo.xml /app/share/metainfo/{APP_ID}.metainfo.xml",
        f"install -Dm644 phimthai/assets/{APP_ID}.svg /app/share/icons/hicolor/scalable/apps/{APP_ID}.svg",
        "install -Dm644 LICENSE /app/share/licenses/phimthai/LICENSE",
    ], "sources": [
        {"type": "archive", "path": "flatpak-source.tar.gz", "strip-components": 0,
         "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        {"type": "dir", "path": "flatpak-wheels", "dest": "wheels"},
    ]}],
}
qt_audio = json.loads((ROOT / "packaging/qtmultimedia.json").read_text())
for item in qt_audio["sources"]:
    if item["type"] == "patch":
        item["path"] = str(ROOT / "packaging" / item["path"])
manifest["modules"].insert(1, qt_audio)
if args.source_pyside:
    pyside_files = cache / "pyside-source-proof/build/files"
    if not (pyside_files / "lib/python3.13/site-packages/pyside6-6.11.1.dist-info/METADATA").is_file():
        raise SystemExit("Complete the PySide source proof and metadata before selecting --source-pyside")
    module = manifest["modules"][2]
    module["build-commands"] = [command for command in module["build-commands"]
                                if "/PySide6/Qt/" not in command]
    module["build-commands"][0] = module["build-commands"][0].replace("packaging/requirements-local.txt", "requirements-source-ui.txt")
    requirements = (ROOT / "packaging/requirements-local.txt").read_text().splitlines()
    (cache / "requirements-source-ui.txt").write_text("\n".join(line for line in requirements if not line.startswith("PySide6")) + "\n")
    module["sources"].append({"type": "file", "path": "requirements-source-ui.txt"})
    manifest["modules"].insert(2, {"name": "pyside-source-artifact-local-experiment", "buildsystem": "simple",
        "build-options": {"no-debuginfo": True, "strip": False},
        "build-commands": ["mkdir -p /app/lib/python3.13/site-packages",
            "cp -a lib/python3.13/site-packages/PySide6 lib/python3.13/site-packages/shiboken6 lib/python3.13/site-packages/pyside6-6.11.1.dist-info lib/python3.13/site-packages/shiboken6-6.11.1.dist-info /app/lib/python3.13/site-packages/",
            "cp -a lib/libpyside6*.so* lib/libshiboken6*.so* /app/lib/"],
        "sources": [{"type": "dir", "path": "pyside-source-proof/build/files"}]})
npu_runtime = cache / "npu-sdk-proof/runtime"
if (npu_runtime / "flm-real").is_file():
    marker = {"version": "1.0.5", "profile": "phimthai-language-prefix-and-timestamp-fix",
              "binary_sha256": hashlib.sha256((npu_runtime / "flm-real").read_bytes()).hexdigest(),
              "status": "experimental", "provenance": "proof/source-build.json"}
    (npu_runtime / "phimthai-runtime.json").write_text(json.dumps(marker, indent=2))
    manifest["modules"].append({"name": "fastflowlm-local-experiment", "buildsystem": "simple",
        "build-options": {"no-debuginfo": True, "strip": False},
        "build-commands": ["mkdir -p /app/libexec/fastflowlm", "cp -a . /app/libexec/fastflowlm/"],
        "sources": [{"type": "dir", "path": "npu-sdk-proof/runtime"}]})
path = cache / (APP_ID + ".local.json")
vulkan_runtime = cache / "vulkan-cpu-proof/runtime"
if not (vulkan_runtime / "whisper-server").is_file():
    vulkan_runtime = cache / "vulkan-proof/runtime"
if (vulkan_runtime / "whisper-server").is_file():
    manifest["modules"].append({"name": "whisper-vulkan-local-experiment", "buildsystem": "simple",
        "build-options": {"no-debuginfo": True, "strip": False},
        "build-commands": ["mkdir -p /app/libexec/whisper-vulkan", "cp -a . /app/libexec/whisper-vulkan/"],
        "sources": [{"type": "dir", "path": str(vulkan_runtime.relative_to(cache))}]})
path.write_text(json.dumps(manifest, indent=2) + "\n")
print(path)
