"""Parent-owned whisper.cpp server with verified hardware-GPU startup and CPU fallback."""
import atexit
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from .settings import data_dir

SERVER = LOG = KEY = BASE_URL = None
ACTUAL_DEVICE = None
DEVICE_DESCRIPTION = ""
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def runtime_path():
    for directory in (Path("/app/libexec/whisper-vulkan"), data_dir() / "runtimes/whisper-vulkan"):
        path = directory / "whisper-server"
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def environment():
    values = dict(os.environ)
    # The upstream default excludes software Vulkan and duplicate physical GPUs.
    values.pop("GGML_VK_VISIBLE_DEVICES", None)
    return values


def gpu_devices():
    runtime = runtime_path()
    if runtime is None:
        return []
    try:
        probe = subprocess.run([str(runtime.parent / "whisper-vulkan-devices")],
            env=environment(), capture_output=True, text=True, timeout=10, check=True)
        payload = json.loads(probe.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
            return []
        return [device for device in payload["devices"]
                if isinstance(device, dict) and device.get("is_gpu") is True
                and type(device.get("gpu_index")) is int and device["gpu_index"] >= 0
                and type(device.get("type")) is int and device["type"] in {1, 2}
                and isinstance(device.get("name"), str) and device["name"].strip()
                and isinstance(device.get("description"), str) and device["description"].strip()
                and not any(name in device["description"].lower() for name in ("llvmpipe", "lavapipe", "swiftshader"))]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []


def stop():
    global SERVER, LOG, KEY, BASE_URL, ACTUAL_DEVICE, DEVICE_DESCRIPTION
    process, SERVER = SERVER, None
    if process:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    if LOG:
        LOG.close()
    LOG = KEY = BASE_URL = ACTUAL_DEVICE = None
    DEVICE_DESCRIPTION = ""


atexit.register(stop)


def start(model, settings, gpu=None):
    global SERVER, LOG, KEY, BASE_URL, ACTUAL_DEVICE, DEVICE_DESCRIPTION
    requested_key = (str(model), settings.cpu_threads, gpu["gpu_index"] if gpu else None)
    if SERVER and SERVER.poll() is None and KEY == requested_key:
        return
    stop()
    runtime = runtime_path()
    if runtime is None:
        raise RuntimeError("Whisper CPU/Vulkan runtime is not installed")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    route = "/phimthai-" + uuid.uuid4().hex
    BASE_URL = f"http://127.0.0.1:{port}{route}"
    command = [str(runtime), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
               "--request-path", route, "--threads", str(settings.cpu_threads), "--language", "auto"]
    command += ["--device", str(gpu["gpu_index"])] if gpu else ["--no-gpu"]
    # Anonymous log file: startup evidence is readable without retaining transcripts.
    LOG = tempfile.TemporaryFile()
    try:
        SERVER = subprocess.Popen(command, env=environment(), stdout=subprocess.DEVNULL, stderr=LOG)
    except OSError:
        stop()
        raise
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if SERVER.poll() is not None:
            stop()
            raise RuntimeError("Whisper server stopped during model startup")
        try:
            with OPENER.open(BASE_URL + "/health", timeout=0.5) as response:
                payload = json.load(response)
                if not isinstance(payload, dict):
                    stop()
                    raise RuntimeError("Invalid health response from Whisper worker")
                ready = payload.get("status") == "ok"
        except (urllib.error.URLError, TimeoutError, ValueError):
            ready = False
        if ready:
            log = os.pread(LOG.fileno(), 300_000, 0).decode(errors="replace")
            if gpu and (f"using {gpu['name']} backend" not in log
                        or f"failed to initialize {gpu['name']} backend" in log or "no GPU found" in log):
                stop()
                raise RuntimeError("Whisper could not initialize the selected hardware GPU")
            ACTUAL_DEVICE = "vulkan" if gpu else "cpu"
            DEVICE_DESCRIPTION = gpu["description"] if gpu else "CPU"
            KEY = requested_key
            return
        time.sleep(0.1)
    stop()
    raise RuntimeError("Whisper model startup timed out")


def request_transcription(path, settings):
    boundary = "phimthai-" + uuid.uuid4().hex
    fields = {"language": {"Thai": "th", "English": "en"}.get(settings.language, "auto"),
              "translate": "false", "response_format": "json"}
    body = b"".join((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
                    for key, value in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
             'Content-Type: audio/wav\r\n\r\n').encode() + Path(path).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(BASE_URL + "/inference", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with OPENER.open(request, timeout=300) as response:
        result = json.load(response)
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("Invalid response from Whisper worker")
    return result["text"].strip()


def transcribe(path, model_directory, settings):
    from .models import CATALOG
    import typhoon_service as service
    if settings.device == "npu":
        raise RuntimeError("This model uses CPU or Vulkan GPU; select the AMD NPU model for NPU use")
    devices = gpu_devices() if settings.device == "gpu" else []
    selected = "vulkan" if settings.device == "gpu" and devices else "cpu"
    warning = "Compatible hardware GPU unavailable; using CPU" if settings.device == "gpu" and not devices else ""
    model = model_directory / CATALOG[settings.model].files[0]
    gpu = devices[0] if selected == "vulkan" else None
    load_started = time.perf_counter()
    try:
        start(model, settings, gpu)
        load_time = time.perf_counter() - load_started
        started = time.perf_counter()
        text = request_transcription(path, settings)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError):
        if gpu is None:
            raise
        stop()
        start(model, settings)
        load_time = time.perf_counter() - load_started
        started = time.perf_counter()
        text = request_transcription(path, settings)
        warning = "Vulkan GPU failed; completed this job with the same model on CPU"
    return {"ok": True, "text": text, "device": ACTUAL_DEVICE, "device_description": DEVICE_DESCRIPTION,
            "backend": "whisper.cpp", "warning": warning, "load_time": load_time,
            "processing_time": time.perf_counter() - started, "audio_duration": service.read_duration(Path(path))}
