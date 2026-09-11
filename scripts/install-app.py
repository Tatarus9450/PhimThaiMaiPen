#!/usr/bin/env python3
"""Install the GUI into a dedicated venv and add a per-user desktop launcher.

No sudo, model download, hotkey migration or system-Python modification.
The pinned Qwen source patch excludes optional demo/aligner dependencies.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.tatarus9450.PhimThaiMaiPen"
QWEN_URL = "https://files.pythonhosted.org/packages/7f/5b/56c5175d1a4d6ed8602003385570304305e4ae9c40b999d12d75a70c0561/qwen_asr-0.0.6.tar.gz"
QWEN_SHA256 = "294893f2340dc2d58d1f1d1cb8ce26ac0a79f254805ab432dda2892bd5c8d13c"


def run(command, **kwargs):
    subprocess.run([str(item) for item in command], check=True, **kwargs)


def find_python(requested=None):
    candidates = [requested] if requested else [sys.executable, "python3.13", "python3.12", "python3.11"]
    for candidate in candidates:
        executable = shutil.which(candidate)
        if not executable:
            continue
        result = subprocess.run([executable, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip() in {"3.11", "3.12", "3.13"}:
            return executable
    raise RuntimeError("Install Python 3.11–3.13 with venv support, or pass --python /path/to/python")


def install_qwen(python):
    with tempfile.TemporaryDirectory(prefix="phimthai-qwen-source-") as directory:
        root = Path(directory)
        archive = root / "qwen.tar.gz"
        with urllib.request.urlopen(QWEN_URL, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != QWEN_SHA256:
            raise RuntimeError("Qwen source checksum mismatch; installation stopped")
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                target = (root / member.name).resolve()
                if not target.is_relative_to(root) or not (member.isfile() or member.isdir()):
                    raise RuntimeError("Unsupported source archive entry")
            source.extractall(root)
        tree = root / "qwen_asr-0.0.6"
        run(["patch", "--batch", "-p1", "-i", ROOT / "packaging/qwen-minimal.patch"], cwd=tree)
        # Fresh patched source also makes reinstalling/updating idempotent.
        run([python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "--force-reinstall", tree])


def desktop_argument(path):
    value = str(path).replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    # Desktop Entry string escaping is applied after Exec argument escaping.
    return '"' + value.replace("\\", "\\\\") + '"'


def install_launchers(python, data_home):
    launcher = data_home / "phimthai/bin/phimthai"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(str(python)) + ' -m phimthai "$@"\n')
    launcher.chmod(0o755)
    asset_dir = ROOT / "phimthai/assets"
    desktop = data_home / "applications" / (APP_ID + ".desktop")
    desktop.parent.mkdir(parents=True, exist_ok=True)
    text = (asset_dir / desktop.name).read_text()
    text = text.replace("Exec=phimthai", "Exec=/usr/bin/env " + desktop_argument(launcher))
    desktop.write_text(text)
    icon = data_home / "icons/hicolor/scalable/apps" / (APP_ID + ".svg")
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(asset_dir / icon.name, icon)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(desktop.parent)], check=False)
    return launcher, desktop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", help="Python 3.11–3.13 executable")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv-app")
    parser.add_argument("--intel", action="store_true", help="Also install optional OpenVINO runtime")
    parser.add_argument("--no-launcher", action="store_true", help="Install without writing desktop integration")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This application currently supports Linux")
    for command in ("ffmpeg", "patch", "pactl"):
        if not shutil.which(command):
            parser.error(f"Install the system package providing {command}, then run this command again")
    system_python = find_python(args.python)
    environment = args.venv.expanduser().resolve()
    if environment == (ROOT / ".venv").resolve():
        parser.error("Use a separate environment; .venv is reserved for the legacy workflow")
    if environment.exists() and not (environment / "pyvenv.cfg").exists():
        parser.error("The destination exists and is not a virtual environment")
    if not environment.exists():
        run([system_python, "-m", "venv", environment])
    python = environment / "bin/python"
    find_python(str(python))
    run([python, "-m", "pip", "install", "--upgrade", "torch==2.11.0+cpu", "--index-url", "https://download.pytorch.org/whl/cpu"])
    run([python, "-m", "pip", "install", "--upgrade", "-r", ROOT / "packaging/requirements-app.txt"])
    install_qwen(python)
    if args.intel:
        run([python, "-m", "pip", "install", "openvino-genai==2026.3.1.0"])
    run([python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", ROOT])
    run([python, "-m", "pip", "check"])
    run([python, "-c", "from qwen_asr import Qwen3ASRModel; from transformers import MarianMTModel, MarianTokenizer; import phimthai.app; print('ASR, translation and GUI imports passed')"])
    if not args.no_launcher:
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        launcher, desktop = install_launchers(python, data_home)
        print(f"Open PhimThaiMaiPen from your application menu. Launcher: {launcher}")
    print(f"Installed. Run: {shlex.quote(str(python))} -m phimthai")
    print("Download a speech model in Models, then test your microphone in Settings.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
