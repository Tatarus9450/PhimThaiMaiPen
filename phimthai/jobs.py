"""Bounded jobs and parent-owned worker lifecycle for the native application."""
import json
import os
import signal
import sys
import tempfile
import uuid
from collections import deque
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Slot


class JobController(QObject):
    changed = Signal(str)
    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None, worker_module="phimthai.worker", temp_root=None):
        super().__init__(parent)
        self.pending = deque()
        self.active = None
        self.process = None
        self.signature = None
        self.buffer = b""
        self.worker_module = worker_module
        self.temp_root = temp_root
        self.worker_temp = None
        self.worker_pid = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)

    @property
    def busy(self):
        return self.active is not None or bool(self.pending)

    def submit(self, settings, **payload):
        if len(self.pending) >= 4:
            raise RuntimeError("Queue is full. Finish or cancel an existing job first.")
        job = dict(payload, id=uuid.uuid4().hex, settings=asdict(settings))
        self.pending.append(job)
        self.start_next()
        return job["id"]

    def start_next(self):
        if self.active:
            return
        if not self.pending:
            # Keep the model only while there is work. Releasing the owned
            # process also releases Torch/accelerator memory and thread pools.
            self.stop_worker()
            return
        self.active = self.pending.popleft()
        inference_keys = ("model", "device", "language", "cpu_threads", "dictionary", "preference")
        signature = json.dumps({key: self.active["settings"][key] for key in inference_keys}, sort_keys=True)
        if signature != self.signature:
            self.stop_worker()
            self.signature = signature
        if self.process is None:
            process = QProcess(self)
            self.process = process
            self.worker_temp = tempfile.TemporaryDirectory(prefix="worker-", dir=self.temp_root)
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("TMPDIR", self.worker_temp.name)
            # Set library limits before imports, including inherited BLAS
            # settings that would otherwise override the selected CPU budget.
            threads = str(self.active["settings"]["cpu_threads"])
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                environment.insert(key, threads)
            process.setProcessEnvironment(environment)
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession | QProcess.UnixProcessFlag.DisableCoreDumps
            process.setUnixProcessParameters(parameters)
            # QObject receivers avoid closures retaining the parent through a
            # child being deleted during rapid worker teardown/recreation.
            process.started.connect(self.worker_started)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardOutput.connect(self.read_output)
            process.readyReadStandardError.connect(self.read_error)
            process.finished.connect(self.worker_finished)
            process.errorOccurred.connect(self.worker_error)
            process.start(sys.executable, ["-m", self.worker_module])
        else:
            self.dispatch()
        self.changed.emit("Processing speech…")
        self.timer.start(600_000)

    def dispatch(self):
        if self.process is not None and self.active is not None:
            self.process.write((json.dumps(self.active, ensure_ascii=False) + "\n").encode())

    @Slot()
    def worker_started(self):
        process = self.sender()
        if process is self.process:
            self.worker_pid = int(process.processId())

    @Slot()
    def read_error(self):
        self.sender().readAllStandardError()

    @Slot()
    def read_output(self):
        process = self.sender()
        if process is not self.process:
            return
        self.buffer += bytes(process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                response = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(response, dict):
                continue
            if response.get("event") == "ready":
                self.dispatch()
            elif self.active and response.get("id") == self.active["id"]:
                self.timer.stop()
                response["settings"] = self.active["settings"]
                if self.active.get("action") == "transcribe":
                    response["source_audio"] = self.active.get("audio")
                self.active = None
                self.changed.emit("Ready")
                if response.get("ok"):
                    self.result.emit(response)
                else:
                    self.failed.emit(response.get("error", "Worker failed"))
                QTimer.singleShot(0, self, self.start_next)

    @Slot(QProcess.ProcessError)
    def worker_error(self, error):
        process = self.sender()
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self.cancel()
            self.failed.emit("Could not start the speech worker")

    @Slot(int, QProcess.ExitStatus)
    def worker_finished(self, code, status):
        process = self.sender()
        if process is not self.process:
            return
        self.process = None
        process.deleteLater()
        self.cleanup_worker()
        self.signature = None
        self.buffer = b""
        self.timer.stop()
        if self.active:
            self.active = None
            self.failed.emit(f"Speech worker stopped unexpectedly ({code}). You can retry.")
        QTimer.singleShot(0, self, self.start_next)

    def stop_worker(self):
        process, self.process = self.process, None
        self.buffer = b""
        if process:
            # Each worker owns its process group, including ffmpeg. Terminate
            # the group before deleting the parent-owned temporary directory.
            self.kill_group()
            process.kill()
            process.waitForFinished(3000)
            process.deleteLater()
        self.cleanup_worker()

    def kill_group(self):
        if self.worker_pid:
            try:
                os.killpg(self.worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.worker_pid = 0

    def cleanup_worker(self):
        self.kill_group()
        if self.worker_temp:
            self.worker_temp.cleanup()
            self.worker_temp = None

    def cancel(self):
        self.timer.stop()
        self.pending.clear()
        self.active = None
        self.stop_worker()
        self.changed.emit("Cancelled")

    def timeout(self):
        self.cancel()
        self.failed.emit("Speech processing timed out. Retry with a shorter recording or another model.")
