#!/usr/bin/env python3
"""Verify KDE Record -> installed launcher -> single-instance IPC -> start/stop.

Run only after closing the real app. Uses the real application entry point with
synthetic WAV Recorder, a submit spy (no ASR worker), and settings-save spy.
No physical keypress, microphone, clipboard write or shortcut rewrite is made.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import wave


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def child(directory):
    from unittest.mock import patch
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["XDG_CONFIG_HOME"] = str(directory / "config")
    from PySide6.QtCore import QObject, QTimer, Signal, qVersion
    from PySide6.QtWidgets import QApplication
    import phimthai.app as application
    from phimthai.models import CATALOG, local_model
    from phimthai.settings import Settings, save_settings
    from phimthai import __version__

    model = next((key for key, spec in CATALOG.items()
                  if spec.kind == "asr" and local_model(key) is not None), None)
    if model is None:
        raise RuntimeError("An installed model must pass the application's normal recording gate")
    save_settings(Settings(model=model, profile="smart", paste_mode="review", remember_desktop=False,
                           keep_history=False, keep_audio_history=False, onboarding_done=True))
    report = {"pid": os.getpid(), "qt": qVersion(), "version": __version__,
              "application_module": application.__file__, "application_sha256": digest(Path(application.__file__)),
              "model_gate": model, "substitutions": ["Recorder", "JobController.submit", "application.save_settings"],
              "events": [], "mode_changes": [], "saved_profiles": [],
              "asr_submissions": 0, "physical_microphone_opened": False}
    report_path = directory / "child.json"

    class MediaFixture(QObject):
        audioInputsChanged = Signal()

    class RecorderFixture(QObject):
        level = Signal(int)
        failed = Signal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.media_devices = MediaFixture(self)
            self.active = False

        def start(self, path, microphone=""):
            if self.active:
                raise RuntimeError("Duplicate recording start")
            # Deliberately synthetic silence. Never passed to a speech model.
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 1600)
            self.active = True
            report["events"].append("recorder_start")
            report["audio_path"] = str(path)
            write(report_path, report)

        def stop(self):
            if not self.active:
                return False
            self.active = False
            report["events"].append("recorder_stop")
            write(report_path, report)
            return True

    def finish():
        window = next((widget for widget in QApplication.topLevelWidgets()
                       if isinstance(widget, application.MainWindow)), None)
        if window:
            report["final_recording"] = window.recording
            report["final_busy"] = window.jobs.busy
            report["transcript_characters"] = len(window.editor.toPlainText())
            report["worker_pid"] = window.jobs.worker_pid
            report["temp_directory"] = window.temp.name
            report["shortcut_hint"] = window.shortcut_hint.text()
            write(report_path, report)
            window.quit()

    def submit(controller, settings, **payload):
        report["asr_submissions"] += 1
        report["events"].append("asr_submit_boundary")
        report["submission_action"] = payload.get("action")
        report["submitted_audio_is_fixture"] = payload.get("audio") == report.get("audio_path")
        write(report_path, report)
        return "synthetic-shortcut-proof"

    def save(settings):
        report["saved_profiles"].append(settings.profile)
        write(report_path, report)

    def observe_modes():
        window = next(widget for widget in QApplication.topLevelWidgets()
                      if isinstance(widget, application.MainWindow))
        report["initial_profile"] = window.profile.currentData()
        def changed(*_args):
            report["mode_changes"].append(window.profile.currentData())
            write(report_path, report)
            if len(report["mode_changes"]) == 3:
                QTimer.singleShot(1500, finish)
        window.profile.currentIndexChanged.connect(changed)
        write(report_path, report)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(finish)
    # Start after QApplication exists via a timer created by the real Recorder.
    original_init = RecorderFixture.__init__
    def initialize(self, parent=None):
        original_init(self, parent)
        timer.start(20_000)
        report["fixture_armed"] = True
        write(report_path, report)
        QTimer.singleShot(0, observe_modes)
    RecorderFixture.__init__ = initialize
    with patch.object(application, "Recorder", RecorderFixture), \
         patch.object(application.JobController, "submit", submit), \
         patch.object(application, "save_settings", save):
        result = application.main()
    report["exit_code"] = result
    report["temp_directory_removed"] = not Path(report.get("temp_directory", "/nonexistent")).exists()
    write(report_path, report)
    return result


def controller(args):
    from phimthai import APP_ID, kde
    launcher = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "phimthai/bin/phimthai"
    def status():
        result = subprocess.run([str(launcher), "--status"], capture_output=True, text=True, timeout=6)
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError("Installed launcher has no usable --status response") from exc
    initial = status()
    if initial.get("running"):
        raise RuntimeError("Close the real application first; this proof must never toggle an existing app")
    settings = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "phimthai/settings.json"
    desktop = launcher.parents[2] / "applications" / (APP_ID + ".desktop")
    shortcuts = settings.parents[1] / "kglobalshortcutsrc"
    protected = [settings, desktop, shortcuts]
    hashes = {str(path): digest(path) for path in protected}
    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "scope": "Real KDE service action and installed launcher/IPC; offscreen app with synthetic Recorder and submit spy",
              "physical_keypress": False, "initial": initial, "states": [], "invocations": 0, "mode_invocations": 0,
              "launcher": str(launcher), "protected_sha256_before": hashes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, report)
    process = None
    with tempfile.TemporaryDirectory(prefix="phimthai-shortcut-route-") as temporary:
        directory = Path(temporary)
        try:
            with (directory / "child.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(directory)],
                    cwd="/tmp", stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                def await_state(recording, profile=None):
                    deadline = time.monotonic() + 8
                    last = {}
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError("Proof application exited before the expected state")
                        last = status()
                        if last.get("pid") != process.pid:
                            if last.get("running"):
                                raise RuntimeError("Another app owns the IPC endpoint; refusing to invoke Record")
                        elif (last.get("recording") is recording and last.get("shortcut") == "Meta+H"
                              and (profile is None or last.get("profile") == profile)):
                            report["states"].append(last)
                            write(args.output, report)
                            return
                        time.sleep(0.1)
                    raise RuntimeError(f"Recording state {recording} was not observed: {last}")
                await_state(False, "smart")
                armed = json.loads((directory / "child.json").read_text())
                if not armed.get("fixture_armed") or armed["pid"] != process.pid:
                    raise RuntimeError("Synthetic recorder was not armed; no action may be invoked")
                async def invoke(bus, action="Record", trigger="Meta+H"):
                    owner = (await kde._call(bus, "action", "i", [kde._key(trigger)[0]]))[0]
                    if owner[:2] != [kde.COMPONENT, action]:
                        raise RuntimeError(f"{trigger} is not owned by the new native {action} action")
                    path = (await kde._call(bus, "getComponent", "s", [kde.COMPONENT]))[0]
                    await kde._call(bus, "invokeShortcut", "s", [action], path=path,
                                    interface="org.kde.kglobalaccel.Component")
                for expected in (True, False):
                    # This calls the registered service command; no desktop or
                    # launcher redirection is introduced by the proof.
                    asyncio.run(kde._connected(invoke))
                    report["invocations"] += 1
                    write(args.output, report)
                    await_state(expected)
                for profile in ("raw", "th_to_eng", "smart"):
                    asyncio.run(kde._connected(invoke, "CycleMode", "Meta+Shift+H"))
                    report["mode_invocations"] += 1
                    write(args.output, report)
                    await_state(False, profile)
                process.wait(timeout=8)
            report["child"] = json.loads((directory / "child.json").read_text())
            report["child_log"] = (directory / "child.log").read_text()
            report["process_exit_code"] = process.returncode
            report["protected_sha256_after"] = {str(path): digest(path) for path in protected}
            report["protected_files_unchanged"] = hashes == report["protected_sha256_after"]
            report["passed"] = (process.returncode == 0 and report["invocations"] == 2 and
                report["mode_invocations"] == 3 and report["child"]["initial_profile"] == "smart" and
                report["child"]["mode_changes"] == ["raw", "th_to_eng", "smart"] and
                report["child"]["saved_profiles"] == ["raw", "th_to_eng", "smart"] and
                report["child"]["events"] == ["recorder_start", "recorder_stop", "asr_submit_boundary"] and
                report["child"]["asr_submissions"] == 1 and report["child"]["worker_pid"] == 0 and
                report["child"]["submitted_audio_is_fixture"] and report["child"]["transcript_characters"] == 0 and
                report["child"]["temp_directory_removed"] and report["protected_files_unchanged"])
            write(args.output, report)
            return 0 if report["passed"] else 1
        except Exception as exc:
            report["error"] = str(exc)
            if (directory / "child.json").exists():
                report["child"] = json.loads((directory / "child.json").read_text())
            if (directory / "child.log").exists():
                report["child_log"] = (directory / "child.log").read_text()
            write(args.output, report)
            return 1
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Start isolated fixture only when the real app is closed")
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "docs/evidence/kde-shortcut-route.json")
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    if not args.run:
        parser.error("Pass --run after closing the real app")
    return controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
