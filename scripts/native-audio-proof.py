#!/usr/bin/env python3
"""Prove native capture/discard using only owned virtual PulseAudio devices.

Run with the native application's Python. The disconnect fixture moves only its
own recording stream to its own null-sink monitor before removing the selected
remap source, preventing migration onto the host's physical default microphone.
This proves discard after source removal, not timing against automatic migration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def pactl(*arguments):
    return subprocess.check_output(["pactl", *arguments], text=True, timeout=5,
                                   env=dict(os.environ, LC_ALL="C")).strip()


def module_ids():
    # PipeWire's pactl JSON module objects can omit index; short output has IDs.
    return {line.split(None, 1)[0] for line in pactl("list", "short", "modules").splitlines()
            if line.split() and line.split(None, 1)[0].isdigit()}


def child(args):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_AUDIO_BACKEND"] = "pulseaudio"
    directory = Path(args.directory)
    os.environ["XDG_CONFIG_HOME"] = str(directory / "config")
    os.environ["XDG_DATA_HOME"] = str(directory / "data")
    sys.path.insert(0, str(ROOT))
    from unittest.mock import Mock, patch
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtMultimedia import QMediaDevices
    from PySide6.QtWidgets import QApplication
    from phimthai.app import MainWindow
    import phimthai.audio
    import phimthai.pulse_guard

    if qVersion() != args.expect_qt or not shutil.which("pactl"):
        raise RuntimeError("Expected native Qt version and pactl are required")
    app = QApplication([])
    deadline = time.monotonic() + 5
    device = None
    while device is None and time.monotonic() < deadline:
        app.processEvents()
        device = next((d for d in QMediaDevices.audioInputs()
                       if bytes(d.id()).decode() == args.source), None)
        time.sleep(0.025)
    if device is None:
        raise RuntimeError("Owned virtual source is absent; no fallback allowed")
    with patch.object(MainWindow, "setup_tray"), \
         patch.object(MainWindow, "refresh_diagnostics"), \
         patch.object(MainWindow, "refresh_models"), \
         patch.object(MainWindow, "refresh_device_choices"):
        window = MainWindow()
    # Spy on the real UI's ASR submission boundary. Never start a model worker.
    window.jobs.submit = Mock()
    selected = bytes(device.id()).hex()
    window.refresh_microphones()
    index = window.microphone.findData(selected)
    if index < 0:
        window.close()
        raise RuntimeError("Owned source missing from the UI; no default fallback")
    window.microphone.setCurrentIndex(index)
    if window.current_settings().microphone != selected:
        window.close()
        raise RuntimeError("Could not select the exact owned source")
    recorder = window.recorder
    levels, errors, error_observations = [], [], []
    finished = False
    started = time.monotonic()
    recorder.level.connect(levels.append)

    def failed(message):
        errors.append(message)
        error_observations.append({
            "monotonic": time.monotonic(), "recording": window.recording,
            "source_stopped": recorder.source is None,
            "guard_stopped": recorder.pulse_guard is None,
            "asr_submissions": window.jobs.submit.call_count,
        })
        QTimer.singleShot(0, finish)

    recorder.failed.connect(failed)

    def finish():
        nonlocal finished
        if finished:
            return
        finished = True
        if window.recording:
            window.finish_recording()
        captured = recorder.stop()
        audio = window.audio_path
        details = None
        if audio and audio.exists():
            with wave.open(str(audio), "rb") as recorded:
                details = {"duration": recorded.getnframes() / recorded.getframerate(),
                           "frames": recorded.getnframes(), "rate": recorded.getframerate(),
                           "channels": recorded.getnchannels(), "sample_width": recorded.getsampwidth(),
                           "sha256": digest(audio)}
        libraries = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines()
                            if "/libQt6Multimedia.so." in line})
        result = {
            "mode": args.child, "qt_version": qVersion(), "python": sys.executable,
            "module": phimthai.audio.__file__, "module_sha256": digest(phimthai.audio.__file__),
            "guard_sha256": digest(phimthai.pulse_guard.__file__),
            "qt_libraries": {path: digest(path) for path in libraries},
            "source": args.source, "source_id": selected, "captured": captured,
            "capture_failed": recorder.capture_failed, "recording": window.recording,
            "errors": errors, "error_observations": error_observations,
            "maximum_level_percent": max(levels or [0]), "audio": details,
            "asr_submissions": window.jobs.submit.call_count,
            "source_stopped": recorder.source is None,
            "guard_stopped": recorder.pulse_guard is None,
            "temporary_audio_removed_after_error": bool(errors) and (not audio or not audio.exists()),
            "wall_seconds": time.monotonic() - started,
        }
        if args.child == "capture":
            passed = captured and not errors and max(levels or [0]) > 0 and window.jobs.submit.call_count == 1
        else:
            passed = (not captured and bool(errors) and recorder.capture_failed and
                      not window.recording and recorder.source is None and recorder.pulse_guard is None and
                      window.jobs.submit.call_count == 0 and result["temporary_audio_removed_after_error"])
        result["passed"] = passed
        save(directory / (args.child + ".json"), result)
        window.close()
        app.exit(0 if passed else 1)

    try:
        with patch("phimthai.app.local_model", return_value=directory):
            window.toggle_record()
        if not window.recording or not recorder.pulse_guard or not recorder.pulse_guard.process:
            raise RuntimeError("Recorder or native PulseSourceGuard did not start")
        guard = recorder.pulse_guard
        save(directory / "ready.json", {
            "pid": os.getpid(), "guard_pid": int(guard.process.processId()),
            "guard_identity": guard.identity, "source_id": selected,
            "guard_start_ticks": Path(f"/proc/{int(guard.process.processId())}/stat").read_text().split(") ", 1)[1].split()[19],
        })

        if args.child == "monitor_exit":
            def stop_owned_subscription():
                active = recorder.pulse_guard
                if active and active.process:
                    save(directory / "monitor-exit-action.json", {
                        "monotonic": time.monotonic(), "pid": int(active.process.processId()),
                    })
                    active.process.kill()
            QTimer.singleShot(1000, stop_owned_subscription)
        QTimer.singleShot(int(args.duration * 1000) if args.child == "capture" else 8000, finish)
        return app.exec()
    finally:
        window.close()


def parent(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_audio = Path(args.input).resolve()
    # Publisher FLEURS WAVs use float PCM, unsupported by Python 3.11 wave.
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", str(source_audio)], text=True, timeout=10))
    before = {kind: pactl("get-default-" + kind) for kind in ("source", "sink")}
    name = "phimthai_native_proof_" + uuid.uuid4().hex[:12]
    report = {"date": "2026-09-12", "scope": "Native offscreen MainWindow + actual Recorder/PulseSourceGuard; ASR submission boundary spied, no model inference",
              "input": str(source_audio), "input_sha256": digest(source_audio), "input_duration": duration,
              "virtual_sink": name, "virtual_source": name + "_source", "defaults_before": before,
              "host_defaults_changed_by_script": False, "physical_microphone_selected": False,
              "tests": [], "owned_module_ids": [], "cleanup": {}, "error": None, "complete": False,
              "disconnect_fixture_limit": "Before source removal, only this child's source-output is moved onto its own null-sink monitor. This prevents physical-default migration. It tests removal/discard, not which notification wins an automatic stream-migration race."}
    save(output, report)
    modules = []
    process = player = None
    source_module = None
    with tempfile.TemporaryDirectory(prefix="phimthai-native-audio-proof-") as temporary:
        directory = Path(temporary)
        report["temporary_directory"] = str(directory)
        save(output, report)
        try:
            modules.append(pactl("load-module", "module-null-sink", f"sink_name={name}"))
            for mode in ("capture", "disconnect", "monitor_exit"):
                if source_module is None:
                    source_module = pactl("load-module", "module-remap-source", f"master={name}.monitor",
                                          f"source_name={name}_source")
                    modules.append(source_module)
                report["owned_module_ids"].extend(m for m in modules if m not in report["owned_module_ids"])
                current = {kind: pactl("get-default-" + kind) for kind in ("source", "sink")}
                if current != before:
                    raise RuntimeError("Host defaults changed; refusing capture")
                (directory / "ready.json").unlink(missing_ok=True)
                command = [sys.executable, str(Path(__file__).resolve()), "--child", mode,
                           "--source", name + "_source", "--directory", str(directory),
                           "--duration", str(duration + 0.8), "--expect-qt", args.expect_qt]
                environment = dict(os.environ, PULSE_SOURCE=name + "_source", PULSE_SINK=name)
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, env=environment, start_new_session=True)
                deadline = time.monotonic() + 15
                while not (directory / "ready.json").exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not (directory / "ready.json").exists():
                    raise RuntimeError("Native recorder did not become ready")
                ready = json.loads((directory / "ready.json").read_text())
                if ready["pid"] != process.pid:
                    raise RuntimeError("Unexpected proof child identity")
                player = subprocess.Popen(["paplay", "--device=" + name, str(source_audio)],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
                action = None
                if mode == "disconnect":
                    time.sleep(1)
                    sources = json.loads(pactl("--format=json", "list", "sources"))
                    owned = next(s for s in sources if s["name"] == name + "_source")
                    monitor = next(s for s in sources if s["name"] == name + ".monitor")
                    streams = json.loads(pactl("--format=json", "list", "source-outputs"))
                    streams = [s for s in streams if s["source"] == owned["index"] and
                               str(s.get("properties", {}).get("application.process.id")) == str(process.pid)]
                    if len(streams) != 1:
                        raise RuntimeError("Cannot identify exactly one owned recording stream; refusing removal")
                    stream_id = str(streams[0]["index"])
                    pactl("move-source-output", stream_id, name + ".monitor")
                    moved = next(s for s in json.loads(pactl("--format=json", "list", "source-outputs"))
                                 if str(s["index"]) == stream_id)
                    if moved["source"] != monitor["index"]:
                        raise RuntimeError("Owned recording stream did not reach the safe virtual monitor")
                    action = {"source_output": stream_id, "safe_monitor_index": monitor["index"],
                              "removed_source_index": owned["index"], "monotonic": time.monotonic()}
                    pactl("unload-module", source_module)
                    modules.remove(source_module)
                    source_module = None
                stdout, stderr = process.communicate(timeout=max(20, duration + 8))
                result_path = directory / (mode + ".json")
                result = json.loads(result_path.read_text()) if result_path.exists() else {}
                result.update({"child_exit": process.returncode, "ready": ready, "action": action,
                               "stderr": stderr, "stdout": stdout, "player_pid": player.pid})
                try:
                    fields = Path(f"/proc/{ready['guard_pid']}/stat").read_text().split(") ", 1)[1].split()
                    result["guard_after_child_exit"] = "pid_reused" if fields[19] != ready["guard_start_ticks"] else fields[0]
                except OSError:
                    result["guard_after_child_exit"] = "absent"
                if mode == "monitor_exit" and (directory / "monitor-exit-action.json").exists():
                    result["action"] = json.loads((directory / "monitor-exit-action.json").read_text())
                report["tests"].append(result)
                save(output, report)
                if player.poll() is None:
                    player.terminate()
                player.wait(timeout=5)
                player = None
                if process.returncode or not result.get("passed"):
                    raise RuntimeError(f"Native {mode} test failed; see saved evidence")
                process = None
            report["complete"] = True
        except Exception as exc:
            report["error"] = str(exc)
        finally:
            # Stop the child before removing virtual devices. Never expose a
            # surviving capture stream to the host's physical default source.
            for owned_process in (process, player):
                if owned_process and owned_process.poll() is None:
                    try:
                        os.killpg(owned_process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    owned_process.wait(timeout=5)
            cleanup_errors = []
            for module in reversed(modules):
                try:
                    pactl("unload-module", module)
                except Exception as exc:
                    cleanup_errors.append(str(exc))
            remaining = module_ids()
            report["cleanup"] = {"owned_modules_removed": not bool(remaining.intersection(report["owned_module_ids"])),
                                 "errors": cleanup_errors, "child_stopped": process is None or process.poll() is not None,
                                 "player_stopped": player is None or player.poll() is not None,
                                 "owned_guards_reaped": all(t.get("guard_after_child_exit") in {"absent", "pid_reused"} for t in report["tests"])}
            report["defaults_after"] = {kind: pactl("get-default-" + kind) for kind in ("source", "sink")}
            report["defaults_preserved"] = report["defaults_after"] == before
            report["complete"] = report["complete"] and report["cleanup"]["owned_modules_removed"] and report["cleanup"]["owned_guards_reaped"] and report["defaults_preserved"] and not cleanup_errors
            save(output, report)
    report["temporary_directory_removed"] = not directory.exists()
    save(output, report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=["capture", "disconnect", "monitor_exit"])
    parser.add_argument("--source")
    parser.add_argument("--directory")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--expect-qt", default="6.11.2")
    parser.add_argument("--input", default=str(ROOT / ".cache/benchmark/10021525843523202225.wav"))
    parser.add_argument("--output", default=str(ROOT / "docs/evidence/native-audio.json"))
    args = parser.parse_args()
    return child(args) if args.child else parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
