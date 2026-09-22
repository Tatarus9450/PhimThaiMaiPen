#!/usr/bin/env python3
"""Verify the packaged app under `flatpak build --runtime --readonly`.

No QApplication, recording, desktop portal, clipboard, singleton or live app
connection is created. ASR accepts only hash-pinned public Google FLEURS clips.
Model files are read through a temporary XDG data tree; user settings/history
are never loaded. Stdout is one JSON report and never contains a transcript.
"""
import argparse
import configparser
import contextlib
from dataclasses import asdict, replace
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
SAMPLES = (
    {"file": "10026868752543983818.wav", "language": "Thai",
     "sha256": "d774e3bb5370542c316ae458aa819900d2e0e9737ba9046804ee416ef7339de6",
     "reference": "สิ่งนี้เรียกว่าค่า pH ของสารเคมี คุณสามารถสร้างตัวระบุได้โดยใช้น้ำกะหล่ำปลีแดง"},
    {"file": "1003119935936341070.wav", "language": "English",
     "sha256": "33aca50159ec2e3cbcc894eb26faa916d6badb1b49fb75994973561540a7f012",
     "reference": "However, due to the slow communication channels, styles in the west could lag behind by 25 to 30 year."},
)


class VerificationFailure(RuntimeError):
    """Only deliberate, transcript-free messages may enter the JSON report."""


def require(condition, message):
    if not condition:
        raise VerificationFailure(message)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def available_memory_mib():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise VerificationFailure("MemAvailable is unavailable")


@contextlib.contextmanager
def silence_backend_output():
    """Capture Python and native library output; discard it on exit."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = [os.dup(descriptor) for descriptor in (1, 2)]
    with tempfile.TemporaryFile() as capture:
        try:
            os.dup2(capture.fileno(), 1)
            os.dup2(capture.fileno(), 2)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            for descriptor, original in zip((1, 2), saved):
                os.dup2(original, descriptor)
                os.close(original)


def units(text, language):
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)
    return list("".join(text.split())) if language == "Thai" else text.split()


def edit_distance(first, second):
    row = list(range(len(second) + 1))
    for index, left in enumerate(first, 1):
        next_row = [index]
        for other, right in enumerate(second, 1):
            next_row.append(min(next_row[-1] + 1, row[other] + 1,
                                row[other - 1] + (left != right)))
        row = next_row
    return row[-1]


def check_dependency_metadata():
    from packaging.requirements import Requirement
    failures = []
    checked = 0
    for distribution in metadata.distributions():
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            checked += 1
            try:
                version = metadata.version(requirement.name)
                if version not in requirement.specifier:
                    failures.append(f"{distribution.name}: incompatible {requirement.name}")
            except metadata.PackageNotFoundError:
                failures.append(f"{distribution.name}: missing {requirement.name}")
    return {"requirements_checked": checked, "failures": sorted(set(failures))}


def check_packaged_source(package_directory):
    files = [(path, package_directory / path.relative_to(ROOT / "phimthai"))
             for path in (ROOT / "phimthai").rglob("*")
             if path.is_file() and (path.suffix == ".py" or "assets" in path.parts)
             and "__pycache__" not in path.parts]
    for name in ("typhoon_service", "typhoon_backend"):
        files.append((ROOT / f"{name}.py", Path(importlib.util.find_spec(name).origin)))
    aggregate = hashlib.sha256()
    for source, packaged in sorted(files):
        require(packaged.is_file(), "A packaged application source/asset is missing")
        expected, actual = digest(source), digest(packaged)
        require(expected == actual, f"Packaged file differs from checkout: {source.relative_to(ROOT)}")
        aggregate.update(f"{source.relative_to(ROOT)}\0{actual}\n".encode())
    return {"files_checked": len(files), "matches_checkout": True,
            "aggregate_sha256": aggregate.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, help="Read-only managed Qwen 0.6B directory with verified.json")
    parser.add_argument("--samples-dir", type=Path, default=ROOT / ".cache/benchmark")
    parser.add_argument("--imports-only", action="store_true", help="Skip model loading and transcription")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--minimum-available-mib", type=int, default=7000)
    args = parser.parse_args()
    args.samples_dir = args.samples_dir.resolve()
    if args.model_dir:
        args.model_dir = args.model_dir.resolve()
    report = {"status": "running", "stage": "runtime", "asr_requested": not args.imports_only,
              "scope": "Packaged /app code, runtime-only, no GUI/audio capture/portal/clipboard/singleton. Temporary XDG state; read-only model and hash-pinned public audio. No transcript output."}
    started = time.perf_counter()
    try:
        require(Path("/.flatpak-info").is_file(), "Run inside Flatpak with --runtime --readonly")
        info = configparser.ConfigParser(interpolation=None)
        info.read("/.flatpak-info")
        runtime = info.get("Application", "runtime", fallback="")
        require("/org.kde.Platform/" in "/" + runtime, "Platform runtime required; do not validate against the SDK")
        report["runtime"] = runtime
        with tempfile.TemporaryDirectory(prefix="phimthai-preview-check-") as temporary:
            temporary = Path(temporary)
            for key, relative in {"XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
                                  "XDG_CACHE_HOME": "cache", "HF_HOME": "cache/huggingface",
                                  "HF_HUB_CACHE": "cache/huggingface/hub"}.items():
                os.environ[key] = str(temporary / relative)
            os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                               "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
                               "PYTHONDONTWRITEBYTECODE": "1"})
            os.chdir(temporary)
            import phimthai
            from phimthai.settings import Settings

            package = Path(phimthai.__file__).resolve().parent
            require(package.is_relative_to("/app"), "Imported application is not the packaged /app copy")
            expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
            require(phimthai.__version__ == expected_version == metadata.version("phimthai-maipen"),
                    "Packaged application version differs from checkout or distribution metadata")
            report["version"] = phimthai.__version__
            defaults = Settings()
            report["defaults"] = {key: getattr(defaults, key) for key in ("model", "device", "profile", "language")}
            require(report["defaults"] == {"model": "typhoon-realtime", "device": "auto", "profile": "smart", "language": "auto"},
                    "Typhoon / Auto / Smart Mix defaults changed")
            report["first_launch"] = {key: getattr(defaults, key) for key in
                                      ("model_setup", "desktop_setup_done", "remember_desktop", "paste_mode")}
            require(report["first_launch"] == {"model_setup": "pending", "desktop_setup_done": False,
                                               "remember_desktop": True, "paste_mode": "immediate"},
                    "First-launch download/desktop defaults are incorrect")
            report["source"] = check_packaged_source(package)
            icon_name = phimthai.APP_ID + ".png"
            desktop_icon = Path("/app/share/icons/hicolor/512x512/apps") / icon_name
            require(desktop_icon.is_file(), "Desktop penguin icon is missing")
            require(digest(desktop_icon) == digest(package / "assets" / icon_name),
                    "Desktop icon differs from the packaged application icon")
            report["desktop_icon"] = {"path": str(desktop_icon), "sha256": digest(desktop_icon),
                                      "matches_application": True}
            report["dependencies"] = check_dependency_metadata()
            require(not report["dependencies"]["failures"], "Installed dependency metadata is inconsistent")
            report["versions"] = {name: metadata.version(name) for name in
                                  ("PySide6", "shiboken6", "torch", "nemo-toolkit", "qwen-asr", "transformers", "dbus-next", "soundfile")}
            report["stage"] = "imports"
            report["available_memory_mib"] = available_memory_mib()
            if not args.imports_only:
                require(report["available_memory_mib"] >= args.minimum_available_mib,
                        "Insufficient available RAM for the bounded Qwen CPU check")
            with silence_backend_output():
                for name in ("phimthai.app", "nemo.collections.asr", "qwen_asr", "webrtcvad", "soundfile", "torch", "dbus_next"):
                    importlib.import_module(name)
                from PySide6.QtCore import qVersion
                from PySide6.QtMultimedia import QAudioSource, QAudioOutput, QMediaPlayer
            report["qt"] = {"version": qVersion(), "audio_backend": os.environ.get("QT_AUDIO_BACKEND"),
                            "audio_classes_imported": [item.__name__ for item in (QAudioSource, QAudioOutput, QMediaPlayer)],
                            "patched_library": Path("/app/lib/libQt6Multimedia.so.6").is_file(),
                            "ffmpeg_plugin": Path("/app/lib/plugins/multimedia/libffmpegmediaplugin.so").is_file()}
            require(report["qt"]["audio_backend"] == "pulseaudio", "Expected PulseAudio backend is not configured")
            require(report["qt"]["patched_library"] and report["qt"]["ffmpeg_plugin"], "Patched Qt audio libraries are missing")
            require(shutil.which("ffmpeg"), "FFmpeg is missing from the Platform app environment")
            ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10, check=True)
            report["ffmpeg"] = ffmpeg.stdout.splitlines()[0]
            if not args.imports_only:
                require(args.model_dir and (args.model_dir / "verified.json").is_file(), "Provide the managed read-only Qwen model directory")
                require(1 <= args.threads <= (os.cpu_count() or 1), "CPU thread count is out of range")
                for sample in SAMPLES:
                    path = args.samples_dir / sample["file"]
                    require(path.is_file() and digest(path) == sample["sha256"], "Public FLEURS fixture missing or checksum mismatch")
                model_link = temporary / "data/phimthai/models/qwen-0.6b"
                model_link.parent.mkdir(parents=True)
                model_link.symlink_to(args.model_dir.resolve(), target_is_directory=True)
                from phimthai.models import CATALOG, local_model
                report["stage"] = "model_integrity"
                require(local_model("qwen-0.6b", verify=True) is not None, "Pinned Qwen model integrity verification failed")
                report["model"] = {"repository": CATALOG["qwen-0.6b"].repo,
                                   "revision": CATALOG["qwen-0.6b"].revision, "integrity_verified": True}
                report["dataset"] = {"name": "Google FLEURS", "revision": FLEURS_REVISION, "license": "CC-BY-4.0",
                                     "source": f"https://huggingface.co/datasets/google/fleurs/tree/{FLEURS_REVISION}",
                                     "limitation": "Two known public clips; functional smoke, not representative accuracy certification"}
                report["samples"] = []
                from phimthai.worker import run
                # This historical optional-Qwen accuracy proof intentionally
                # uses its supplied Qwen model, independently of app defaults.
                settings = replace(defaults, model="qwen-0.6b", cpu_threads=args.threads)
                for sample in SAMPLES:
                    report["stage"] = "inference_" + sample["language"].lower()
                    print(json.dumps({"stage": report["stage"]}), file=sys.stderr, flush=True)
                    sample_started = time.perf_counter()
                    with silence_backend_output():
                        result = run({"id": "preview-" + sample["language"].lower(), "action": "transcribe",
                                      "audio": str(args.samples_dir / sample["file"]), "settings": asdict(settings)})
                    require(result.get("ok") and result.get("text") and result.get("device") == "cpu",
                            "Qwen CPU did not produce a nonempty successful transcript")
                    reference = units(sample["reference"], sample["language"])
                    errors = edit_distance(reference, units(result["text"], sample["language"]))
                    entry = {"file": sample["file"], "sha256": sample["sha256"], "language": sample["language"],
                             "device": result["device"], "profile": result.get("profile"),
                             "characters": len(result["text"]), "transcript_sha256": hashlib.sha256(result["text"].encode()).hexdigest(),
                             "metric": "CER" if sample["language"] == "Thai" else "WER",
                             "errors": errors, "reference_units": len(reference), "error_rate": errors / len(reference),
                             "wall_seconds": round(time.perf_counter() - sample_started, 3),
                             "vad_applied": result.get("vad_applied"), "no_speech": result.get("no_speech")}
                    report["samples"].append(entry)
                    require(entry["error_rate"] <= .5, "Public clip transcript exceeds the loose functional error threshold")
            report.update(status="passed", stage="complete")
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, VerificationFailure) else "Unexpected validation exception; backend output withheld")
    report["wall_seconds"] = round(time.perf_counter() - started, 3)
    report["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
