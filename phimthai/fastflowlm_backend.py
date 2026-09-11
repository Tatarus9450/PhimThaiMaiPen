"""Optional patched FastFlowLM worker. Server belongs to the speech job process."""
import atexit
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .settings import data_dir

SERVER = None
PORT = None


def runtime_path():
    # Never run an arbitrary downloaded executable from model metadata.
    for path in (Path("/app/libexec/fastflowlm/flm"), data_dir() / "runtimes/fastflowlm/flm"):
        if path.is_file() and os.access(path, os.X_OK) and (path.parent / "phimthai-runtime.json").is_file():
            return path
    return None


def available():
    return bool(runtime_path() and os.access("/dev/accel/accel0", os.R_OK | os.W_OK))


def stop():
    global SERVER, PORT
    if SERVER:
        SERVER.terminate()
        try:
            SERVER.wait(timeout=3)
        except subprocess.TimeoutExpired:
            SERVER.kill()
            SERVER.wait(timeout=3)
    SERVER = None
    PORT = None


atexit.register(stop)


def start(settings):
    global SERVER, PORT
    if SERVER and SERVER.poll() is None:
        return
    stop()
    runtime = runtime_path()
    if not available():
        raise RuntimeError("AMD NPU or the tested FastFlowLM runtime is unavailable")
    marker = json.loads((runtime.parent / "phimthai-runtime.json").read_text())
    if marker.get("profile") != "phimthai-language-prefix-and-timestamp-fix" or hashlib.sha256((runtime.parent / "flm-real").read_bytes()).hexdigest() != marker.get("binary_sha256"):
        raise RuntimeError("FastFlowLM runtime verification failed")
    environment = dict(os.environ, FLM_MODEL_PATH=str(data_dir()), XDG_CONFIG_HOME=str(data_dir() / "runtime-config"))
    # The kernel API and model layout are validated before starting a server.
    validation = subprocess.run([str(runtime), "validate", "--json"], env=environment,
        cwd=runtime.parent, capture_output=True, text=True, timeout=30)
    if validation.returncode:
        raise RuntimeError("FastFlowLM NPU validation failed. See Diagnostics.")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        PORT = probe.getsockname()[1]
    SERVER = subprocess.Popen([str(runtime), "serve", "--asr", "1", "--host", "127.0.0.1",
        "--port", str(PORT), "--cors", "0", "--pmode", "powersaver" if settings.preference == "power" else "performance"],
        cwd=runtime.parent, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if SERVER.poll() is not None:
            stop()
            raise RuntimeError("FastFlowLM server stopped during startup")
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    stop()
    raise RuntimeError("FastFlowLM server startup timed out")


def transcribe(path, settings):
    started = time.perf_counter()
    start(settings)
    # Ignore proxy environment variables for this parent-owned loopback server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    boundary = "phimthai-" + uuid.uuid4().hex
    audio = Path(path).read_bytes()
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-v3\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n').encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/audio/transcriptions", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with opener.open(request, timeout=300) as response:
        result = json.load(response)
    if not isinstance(result.get("text"), str):
        raise RuntimeError("Invalid transcription response from NPU worker")
    import typhoon_service as service
    return {"ok": True, "text": result["text"].strip(), "device": "npu", "backend": "fastflowlm",
            "processing_time": time.perf_counter() - started, "audio_duration": service.read_duration(Path(path)),
            "warning": "Experimental AMD NPU: review Thai text carefully; Qwen CPU was more accurate in initial samples"}
