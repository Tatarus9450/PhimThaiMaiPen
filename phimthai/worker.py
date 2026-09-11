"""One parent-owned worker processes requests sequentially; stdout is JSON only."""
import contextlib
from dataclasses import replace
import json
import os
import sys
import time
from pathlib import Path

from .devices import select_device
from .models import CATALOG, local_model
from .settings import Settings, data_dir


def run(request):
    if request["action"] != "transcribe":
        return run_inference(request)
    from .speech import prepare_speech
    settings = Settings(**request["settings"]).validate()
    with prepare_speech(request["audio"], settings.vad) as (path, metadata):
        if metadata["no_speech"]:
            return dict(metadata, ok=True, text="", model=CATALOG[settings.model].repo, device="none")
        result = run_inference(dict(request, audio=str(path)))
        result.update(metadata)
        return result


def run_inference(request):
    import typhoon_service as service
    settings = Settings(**request["settings"]).validate()
    spec = CATALOG[settings.model]
    path = local_model(settings.model, verify=True) if request["action"] != "translate" else None
    if request["action"] != "translate" and path is None:
        raise RuntimeError("Model missing or integrity check failed. Download or repair it in Models.")
    translation_path = None
    if request["action"] == "translate" or settings.profile == "th_to_eng":
        translation_path = local_model("translate-th-en", verify=True)
        if translation_path is None:
            raise RuntimeError("Download Thai → English translation in Models first")
    service.CONFIG.update({"TYPHOON_MODEL": str(path), "TYPHOON_ASR_BACKEND": spec.backend,
                           "TYPHOON_ASR_LANGUAGE": settings.language,
                           "TYPHOON_CPU_THREADS": str(settings.cpu_threads),
                           "TYPHOON_HF_HOME": str(data_dir() / "cache/huggingface")})
    if translation_path:
        service.CONFIG["TYPHOON_TRANSLATE_MODEL"] = str(translation_path)
    service.CONFIG["TYPHOON_REPLACEMENTS_TEXT"] = settings.dictionary
    warning = ""
    if spec.backend in {"openvino", "fastflowlm", "vulkan"} and request["action"] != "translate":
        if spec.backend == "openvino":
            from .openvino_backend import transcribe
            result = transcribe(request["audio"], path, settings)
        elif spec.backend == "vulkan":
            from .vulkan_backend import transcribe
            result = transcribe(request["audio"], path, settings)
        else:
            from . import fastflowlm_backend
            try:
                if settings.device != "npu":
                    raise RuntimeError("Experimental AMD NPU is not selected automatically")
                if settings.language != "auto":
                    raise RuntimeError("FastFlowLM currently supports automatic language detection only")
                result = fastflowlm_backend.transcribe(request["audio"], settings)
            except Exception as exc:
                fastflowlm_backend.stop()
                if local_model("qwen-0.6b") is None:
                    raise RuntimeError(f"{exc}. Download Qwen 0.6B to enable CPU fallback.") from exc
                fallback = replace(settings, model="qwen-0.6b", device="cpu")
                from dataclasses import asdict
                result = run_inference(dict(request, settings=asdict(fallback)))
                result["warning"] = f"AMD NPU unavailable ({exc}); completed with Qwen 0.6B on CPU"
                return result
        result["source_text"] = service.postprocess_text(result["text"], settings.profile)
        result["text"] = result["source_text"]
        if settings.profile == "th_to_eng":
            service.CONFIG["TYPHOON_DEVICE"] = "cpu"
            result["text"] = service.translate_text(result["text"])
            result["translation_device"] = "cpu"
    else:
        service.import_runtime_modules()
        requested = "cpu" if request["action"] == "translate" and settings.device == "npu" else settings.device
        device, warning = select_device(requested, service.TORCH, settings.model, settings.preference)
        service.CONFIG["TYPHOON_DEVICE"] = device
        try:
            if request["action"] == "translate":
                result = {"ok": True, "text": service.translate_text(request["text"]), "device": device}
            else:
                result = service.transcribe_audio(Path(request["audio"]), settings.profile)
        except (RuntimeError, MemoryError):
            if device != "cuda":
                raise
            service.MODEL = None
            service.TRANSLATION_MODEL = None
            service.TRANSLATION_TOKENIZER = None
            import gc
            gc.collect()
            service.TORCH.cuda.empty_cache()
            service.CONFIG["TYPHOON_DEVICE"] = "cpu"
            if request["action"] == "translate":
                result = {"ok": True, "text": service.translate_text(request["text"]), "device": "cpu"}
            else:
                result = service.transcribe_audio(Path(request["audio"]), settings.profile)
            warning = "GPU inference failed; completed this job on CPU"
    result["model"] = CATALOG["translate-th-en"].repo if request["action"] == "translate" else spec.repo
    result["warning"] = result.get("warning") or warning
    from .performance import record
    try:
        record(settings.model, result["device"], result)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Performance measurement could not be saved: {exc}", file=sys.stderr)
    return result


def main():
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # The Qt parent creates a fresh Unix session for us. If that parent dies,
    # terminate this entire owned group (including ffmpeg / FastFlowLM).
    if sys.platform == "linux" and os.getpgrp() == os.getpid():
        import ctypes
        import signal
        parent = os.getppid()
        signal.signal(signal.SIGTERM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
        ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0)
        if parent != os.getppid() or parent == 1:
            return
    print(json.dumps({"event": "ready"}), flush=True)
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            started = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                result = run(request)
            result.update({"id": request["id"], "elapsed": time.perf_counter() - started})
        except Exception as exc:
            result = {"id": request.get("id"), "ok": False, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
