"""Vulkan failure/ownership regressions; no GPU model or desktop is accessed."""
import contextlib
from dataclasses import asdict, replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from phimthai import vulkan_backend as backend
from phimthai import worker
from phimthai.models import CATALOG
from phimthai.settings import Settings


GPU = {"name": "Vulkan0", "description": "AMD Radeon 840M Graphics (RADV KRACKAN1)",
       "gpu_index": 0, "type": 2, "is_gpu": True}


class VulkanBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-vulkan-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.audio = self.root / "speech.wav"
        self.audio.write_bytes(b"mock audio; no actual inference")
        self.settings = Settings(model="whisper-turbo-vulkan", device="gpu", profile="raw", cpu_threads=1)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(backend, SERVER=None, LOG=None, KEY=None,
            BASE_URL=None, ACTUAL_DEVICE=None, DEVICE_DESCRIPTION=""))
        self.stack.enter_context(patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }))
        self.service = types.ModuleType("typhoon_service")
        self.service.CONFIG = {}
        self.service.read_duration = Mock(return_value=5.0)
        self.service.postprocess_text = lambda text, profile: text.strip()
        self.service.translate_text = Mock(return_value="translated")
        self.stack.enter_context(patch.dict(sys.modules, {"typhoon_service": self.service}))
        self.addCleanup(self._clear_backend)

    def _clear_backend(self):
        # Preserve failed cleanup assertions while still closing test-owned handles.
        handle = backend.LOG
        try:
            backend.stop()
        finally:
            if handle and not handle.closed:
                handle.close()

    def _startup_fixture(self, log=b"whisper_backend_init_gpu: using Vulkan0 backend\n",
                         health=b'{"status":"ok"}'):
        process = Mock()
        process.poll.return_value = None
        process.wait.return_value = 0
        def spawn(command, **kwargs):
            kwargs["stderr"].write(log)
            kwargs["stderr"].flush()
            return process
        popen = self.stack.enter_context(patch.object(backend.subprocess, "Popen", side_effect=spawn))
        self.stack.enter_context(patch.object(backend, "runtime_path", return_value=self.root / "whisper-server"))
        socket_factory = self.stack.enter_context(patch.object(backend.socket, "socket"))
        socket_factory.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 43210)
        opener = self.stack.enter_context(patch.object(backend, "OPENER"))
        opener.open.side_effect = lambda *a, **k: io.BytesIO(health)
        self.stack.enter_context(patch.object(backend.time, "sleep"))
        return process, popen

    def test_probe_contains_malformed_json_and_wrong_shapes(self):
        with patch.object(backend, "runtime_path", return_value=self.root / "whisper-server"), \
             patch.object(backend.subprocess, "run") as run:
            for payload in ("{broken", "null", "[]", '{"devices":null}',
                            '{"devices":[null,42,"text"]}'):
                with self.subTest(payload=payload):
                    run.return_value = Mock(stdout=payload)
                    self.assertEqual(backend.gpu_devices(), [])
            run.side_effect = subprocess.TimeoutExpired("probe", 10)
            self.assertEqual(backend.gpu_devices(), [])

    def test_probe_rejects_software_and_inconsistent_gpu_metadata(self):
        invalid = [dict(GPU, is_gpu=False), dict(GPU, gpu_index=True),
                   dict(GPU, gpu_index=-1), dict(GPU, name=None),
                   dict(GPU, description=None), dict(GPU, name=""),
                   dict(GPU, description=""), dict(GPU, type=0),
                   dict(GPU, description="llvmpipe (LLVM 21)")]
        with patch.object(backend, "runtime_path", return_value=self.root / "whisper-server"), \
             patch.object(backend.subprocess, "run") as run:
            for device in invalid:
                with self.subTest(device=device):
                    run.return_value = Mock(stdout=json.dumps({"devices": [device, GPU]}))
                    self.assertEqual(backend.gpu_devices(), [GPU])

    def test_probe_removes_software_device_override_without_mutating_environment(self):
        with patch.dict(os.environ, {"GGML_VK_VISIBLE_DEVICES": "2"}), \
             patch.object(backend, "runtime_path", return_value=self.root / "whisper-server"), \
             patch.object(backend.subprocess, "run", return_value=Mock(stdout=json.dumps({"devices": [GPU]}))) as run:
            self.assertEqual(backend.gpu_devices(), [GPU])
            self.assertNotIn("GGML_VK_VISIBLE_DEVICES", run.call_args.kwargs["env"])
            self.assertEqual(os.environ["GGML_VK_VISIBLE_DEVICES"], "2")

    def test_failed_gpu_start_clears_label_and_stops_owned_process(self):
        process, _ = self._startup_fixture(log=b"using Vulkan0 backend\nfailed to initialize Vulkan0 backend\n")
        backend.ACTUAL_DEVICE = "vulkan"
        backend.DEVICE_DESCRIPTION = "old GPU"
        with self.assertRaises(RuntimeError):
            backend.start(self.root / "model.bin", self.settings, GPU)
        process.terminate.assert_called_once()
        self.assertIsNone(backend.SERVER)
        self.assertIsNone(backend.ACTUAL_DEVICE)
        self.assertEqual(backend.DEVICE_DESCRIPTION, "")
        self.assertIsNone(backend.LOG)

    def test_requested_gpu_flag_alone_never_labels_cpu_as_gpu(self):
        process, _ = self._startup_fixture(log=b"use gpu = 1\nno GPU found\n")
        with self.assertRaises(RuntimeError):
            backend.start(self.root / "model.bin", self.settings, GPU)
        self.assertIsNone(backend.ACTUAL_DEVICE)
        process.terminate.assert_called_once()

    def test_malformed_health_stops_process_and_clears_label(self):
        process, _ = self._startup_fixture(health=b"null")
        with self.assertRaises(RuntimeError):
            backend.start(self.root / "model.bin", self.settings, GPU)
        process.terminate.assert_called_once()
        self.assertIsNone(backend.SERVER)
        self.assertIsNone(backend.ACTUAL_DEVICE)
        self.assertIsNone(backend.LOG)

    def test_popen_failure_closes_log_and_resets_connection_state(self):
        _, popen = self._startup_fixture()
        handle = tempfile.TemporaryFile()
        self.addCleanup(handle.close)
        with patch.object(backend.tempfile, "TemporaryFile", return_value=handle):
            popen.side_effect = OSError("runtime disappeared")
            with self.assertRaises((OSError, RuntimeError)):
                backend.start(self.root / "model.bin", self.settings, GPU)
        self.assertTrue(handle.closed)
        self.assertIsNone(backend.LOG)
        self.assertIsNone(backend.BASE_URL)
        self.assertIsNone(backend.ACTUAL_DEVICE)

    def test_successful_warm_start_reuses_only_matching_device_and_model(self):
        _, popen = self._startup_fixture()
        backend.start(self.root / "model.bin", self.settings, GPU)
        backend.start(self.root / "model.bin", self.settings, GPU)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(backend.ACTUAL_DEVICE, "vulkan")
        self.assertEqual(backend.DEVICE_DESCRIPTION, GPU["description"])
        backend.start(self.root / "model.bin", self.settings)
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(backend.ACTUAL_DEVICE, "cpu")
        self.assertIn("--no-gpu", popen.call_args.args[0])

    def test_stop_escalates_stubborn_process_and_is_idempotent(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("owned-server", 3), 0]
        handle = tempfile.TemporaryFile()
        backend.SERVER, backend.LOG = process, handle
        backend.ACTUAL_DEVICE, backend.KEY = "vulkan", ("old",)
        backend.stop()
        backend.stop()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertTrue(handle.closed)
        self.assertIsNone(backend.KEY)
        self.assertIsNone(backend.ACTUAL_DEVICE)

    def test_stop_reaps_real_test_owned_subprocess(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def reap():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        self.addCleanup(reap)
        backend.SERVER = process
        backend.stop()
        self.assertIsNotNone(process.poll())
        self.assertIsNone(backend.SERVER)

    def test_invalid_transcription_responses_are_controlled_failures(self):
        backend.BASE_URL = "http://127.0.0.1:43210/test"
        with patch.object(backend, "OPENER") as opener:
            for payload in (b"null", b"[]", b'{"text":null}', b'{"text":42}', b'{"error":"failed"}'):
                with self.subTest(payload=payload):
                    opener.open.return_value = io.BytesIO(payload)
                    with self.assertRaises(RuntimeError):
                        backend.request_transcription(self.audio, self.settings)

    def test_transcription_passes_language_but_never_whisper_translation(self):
        backend.BASE_URL = "http://127.0.0.1:43210/test"
        with patch.object(backend, "OPENER") as opener:
            opener.open.return_value = io.BytesIO(json.dumps({"text": " สวัสดี hello \n"}).encode())
            result = backend.request_transcription(self.audio, replace(self.settings, language="Thai", profile="th_to_eng"))
            self.assertEqual(result, "สวัสดี hello")
            body = opener.open.call_args.args[0].data
            self.assertIn(b'name="language"\r\n\r\nth\r\n', body)
            self.assertIn(b'name="translate"\r\n\r\nfalse\r\n', body)

    def _worker_case(self, *, startup_failure=False, cpu_failure=False):
        attempts = []
        def start(model, settings, gpu=None):
            attempts.append((model, gpu))
            if gpu and startup_failure:
                raise RuntimeError("GPU initialization failed")
            backend.ACTUAL_DEVICE = "vulkan" if gpu else "cpu"
            backend.DEVICE_DESCRIPTION = GPU["description"] if gpu else "CPU"
        def request(path, settings):
            if backend.ACTUAL_DEVICE == "vulkan" or cpu_failure:
                raise RuntimeError("inference failed")
            return "สวัสดี hello"
        incoming = {"id": "one-original-job", "action": "transcribe", "audio": str(self.audio),
                    "settings": asdict(self.settings)}
        output = io.StringIO()
        with patch.object(backend, "gpu_devices", return_value=[GPU]), \
             patch.object(backend, "start", side_effect=start), \
             patch.object(backend, "request_transcription", side_effect=request) as inference, \
             patch.object(worker, "local_model", return_value=self.root / "model"), \
             patch.object(worker, "run", side_effect=worker.run_inference), \
             patch("phimthai.performance.record") as record, \
             patch.object(worker.os, "getpgrp", return_value=-1), \
             patch.object(sys, "stdin", io.StringIO(json.dumps(incoming) + "\n")), \
             contextlib.redirect_stdout(output):
            worker.main()
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[0], {"event": "ready"})
        self.assertEqual(len(events), 2, "one request must emit exactly one result, including fallback")
        result = events[1]
        self.assertEqual(result["id"], incoming["id"])
        self.assertEqual(len(attempts), 2)
        expected_model = self.root / "model" / CATALOG[self.settings.model].files[0]
        self.assertEqual([model for model, _ in attempts], [expected_model, expected_model])
        self.assertEqual(attempts[0][1], GPU)
        self.assertIsNone(attempts[1][1])
        self.assertEqual(inference.call_count, 1 if startup_failure else 2)
        if cpu_failure:
            self.assertFalse(result["ok"])
            self.assertNotIn("device", result)
            record.assert_not_called()
        else:
            self.assertTrue(result["ok"])
            self.assertEqual(result["device"], "cpu")
            self.assertEqual(result["model"], CATALOG[self.settings.model].repo)
            self.assertIn("same model on CPU", result["warning"])
            self.assertEqual(record.call_args.args[1], "cpu")

    def test_gpu_start_failure_returns_one_cpu_result_using_same_model(self):
        self._worker_case(startup_failure=True)

    def test_gpu_inference_failure_returns_one_cpu_result_using_same_model(self):
        self._worker_case()

    def test_failed_cpu_retry_returns_one_error_without_gpu_label(self):
        self._worker_case(cpu_failure=True)

    def test_cancellation_exception_does_not_start_cpu_retry(self):
        with patch.object(backend, "gpu_devices", return_value=[GPU]), \
             patch.object(backend, "start") as start, \
             patch.object(backend, "request_transcription", side_effect=KeyboardInterrupt), \
             patch.object(backend, "stop"):
            with self.assertRaises(KeyboardInterrupt):
                backend.transcribe(self.audio, self.root, self.settings)
        self.assertEqual(start.call_count, 1)


class VulkanPackagingTests(unittest.TestCase):
    def test_generated_wrappers_preserve_paths_and_arguments_with_spaces(self):
        root = Path(__file__).resolve().parents[1]
        modules = json.loads((root / "packaging/whisper-vulkan.json").read_text())
        scripts = [s for m in modules for s in m["sources"]
                   if s.get("type") == "script" and s["dest-filename"].endswith("-wrapper")]
        self.assertEqual(len(scripts), 3)
        with tempfile.TemporaryDirectory(prefix="phimthai wrapper ") as directory:
            runtime = Path(directory)
            (runtime / "bin").mkdir()
            for source in scripts:
                with self.subTest(wrapper=source["dest-filename"]):
                    name = source["dest-filename"].removesuffix("-wrapper")
                    program = runtime / "bin" / name
                    program.write_text(f"#!{sys.executable}\nimport json,os,sys\nprint(json.dumps([sys.argv[1:],os.environ['LD_LIBRARY_PATH']]))\n")
                    program.chmod(0o755)
                    wrapper = runtime / name
                    wrapper.write_text("#!/bin/sh\n" + "\n".join(source["commands"]) + "\n")
                    wrapper.chmod(0o755)
                    args = ["a path with spaces", 'literal"quote', "ไทย"]
                    result = subprocess.run([str(wrapper), *args], cwd="/tmp", text=True,
                                            capture_output=True, check=True, timeout=5)
                    values, library_path = json.loads(result.stdout)
                    self.assertEqual(values, args)
                    self.assertEqual(library_path.split(os.pathsep)[0], str(runtime / "lib"))


if __name__ == "__main__":
    unittest.main()
