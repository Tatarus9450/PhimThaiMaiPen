"""Optional OpenVINO Whisper worker; device names describe real execution."""
import time
from pathlib import Path

PIPELINE = None
DEVICE = None


def transcribe(path, model_path, settings):
    global PIPELINE, DEVICE
    import openvino_genai
    import soundfile
    import typhoon_service as service
    from .devices import openvino_devices
    from .performance import choose
    available = openvino_devices()
    requested = {"cpu": "CPU", "gpu": "GPU", "npu": "NPU"}.get(settings.device)
    warning = ""
    if settings.device == "auto":
        selected, warning = choose(settings.model, [d.lower() for d in available if d in {"CPU", "GPU"}], settings.preference)
        requested = selected.upper()
    if requested not in available:
        warning = f"{requested} unavailable for OpenVINO; using CPU"
        requested = "CPU"
    audio = service.prepare_audio(Path(path))
    try:
        samples, rate = soundfile.read(str(audio), dtype="float32")
        options = {"task": "transcribe", "max_new_tokens": 440, "return_timestamps": True}
        if settings.language != "auto":
            options["language"] = "<|th|>" if settings.language == "Thai" else "<|en|>"
        started = time.perf_counter()
        try:
            if PIPELINE is None or DEVICE != requested:
                PIPELINE = openvino_genai.WhisperPipeline(str(model_path), requested)
                DEVICE = requested
            decoded = PIPELINE.generate(samples, **options)
        except RuntimeError:
            if requested == "CPU":
                raise
            PIPELINE = None
            PIPELINE = openvino_genai.WhisperPipeline(str(model_path), "CPU")
            DEVICE = "CPU"
            decoded = PIPELINE.generate(samples, **options)
            warning = f"{requested} inference failed; completed on CPU"
        return {"ok": True, "text": " ".join(decoded.texts).strip(), "device": DEVICE.lower(),
                "backend": "openvino", "warning": warning, "audio_duration": len(samples) / rate,
                "processing_time": time.perf_counter() - started}
    finally:
        audio.unlink(missing_ok=True)
