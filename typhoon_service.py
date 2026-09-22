#!/usr/bin/env python3
import argparse
import atexit
import json
import os
import re
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from typhoon_backend import SERVICE_PID_FILE, SOCKET_FILE, get_active_profile, get_asr_backend, load_config, normalize_profile

CONFIG = load_config()
MODEL = None
TORCH = None
AUTO_MODEL_FOR_SEQ2SEQ_LM = None
AUTO_TOKENIZER = None
DEVICE = "cpu"
MODEL_LOCK = threading.Lock()
TRANSLATION_MODEL = None
TRANSLATION_TOKENIZER = None
TRANSLATION_LOCK = threading.Lock()
OWNS_SOCKET = False


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def configure_runtime() -> None:
    threads = CONFIG.get("TYPHOON_CPU_THREADS", str(os.cpu_count() or 4))
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(key, threads)

    hf_home = Path(CONFIG.get("TYPHOON_HF_HOME", str(Path(".cache") / "huggingface"))).expanduser()
    hf_home.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(hf_home / "hub"))
    os.environ.setdefault("MPLCONFIGDIR", str(hf_home.parent / "matplotlib"))


def import_runtime_modules() -> None:
    global TORCH

    if TORCH is not None:
        return

    configure_runtime()

    import torch  # type: ignore

    TORCH = torch

    threads = int(CONFIG.get("TYPHOON_CPU_THREADS", str(os.cpu_count() or 4)))
    try:
        torch.set_num_threads(threads)
    except Exception:
        pass
    try:
        torch.set_num_interop_threads(max(1, min(threads, 4)))
    except Exception:
        pass
    try:
        torch.set_grad_enabled(False)
    except Exception:
        pass


def import_translation_modules() -> None:
    global AUTO_MODEL_FOR_SEQ2SEQ_LM, AUTO_TOKENIZER

    if AUTO_MODEL_FOR_SEQ2SEQ_LM is not None and AUTO_TOKENIZER is not None:
        return

    configure_runtime()

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore

    AUTO_MODEL_FOR_SEQ2SEQ_LM = AutoModelForSeq2SeqLM
    AUTO_TOKENIZER = AutoTokenizer


def resolve_device() -> str:
    import_runtime_modules()

    requested = CONFIG.get("TYPHOON_DEVICE", "cpu").strip().lower()
    if requested == "auto":
        return "cuda" if TORCH.cuda.is_available() else "cpu"
    if requested == "cuda" and not TORCH.cuda.is_available():
        log("CUDA requested but unavailable; falling back to CPU")
        return "cpu"
    return requested or "cpu"


def _write_silence_wav(path: Path, duration_ms: int = 250, sample_rate: int = 16000) -> None:
    frame_count = int(sample_rate * (duration_ms / 1000))
    silence = (b"\x00\x00" * frame_count)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(silence)


def load_model() -> None:
    global DEVICE, MODEL

    if MODEL is not None:
        return

    import_runtime_modules()
    DEVICE = resolve_device()
    model_name = CONFIG["TYPHOON_MODEL"]

    log(f"Loading model: {model_name} on {DEVICE.upper()}")
    if get_asr_backend(CONFIG) == "qwen":
        from qwen_asr import Qwen3ASRModel

        MODEL = Qwen3ASRModel.from_pretrained(
            model_name,
            dtype=TORCH.float16 if DEVICE == "cuda" else TORCH.float32,
            device_map=DEVICE,
            max_inference_batch_size=1,
            max_new_tokens=1024,
        )
    else:
        import nemo.collections.asr as nemo_asr

        local = Path(model_name)
        if local.is_dir():
            local = local / "typhoon-asr-realtime.nemo"
        if local.is_file():
            MODEL = nemo_asr.models.ASRModel.restore_from(
                restore_path=str(local), map_location=DEVICE,
            )
        else:
            MODEL = nemo_asr.models.ASRModel.from_pretrained(
                model_name=model_name, map_location=DEVICE,
            )
        MODEL.eval()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        temp_path = Path(temp_audio.name)
    try:
        _write_silence_wav(temp_path)
        with MODEL_LOCK:
            with TORCH.inference_mode():
                transcribe_loaded(temp_path)
        log("Warm-up completed")
    finally:
        temp_path.unlink(missing_ok=True)


def _translate_chunk_loaded(text: str) -> str:
    if not text.strip():
        return ""

    inputs = TRANSLATION_TOKENIZER(
        text,
        return_tensors="pt",
        truncation=False,
        max_length=512,
    )
    if DEVICE == "cuda":
        inputs = {key: value.to(DEVICE) for key, value in inputs.items()}

    input_ids = inputs.get("input_ids")
    max_new_tokens = 64
    if input_ids is not None:
        max_new_tokens = max(64, min(512, int(input_ids.shape[-1]) * 2))

    with TRANSLATION_LOCK:
        with TORCH.inference_mode():
            generated = TRANSLATION_MODEL.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
            )

    eos = getattr(TRANSLATION_MODEL.generation_config, "eos_token_id", None)
    endings = set(eos if isinstance(eos, list) else [eos])
    tokens = generated[0].tolist()
    if len(tokens) >= max_new_tokens and not endings.intersection(tokens[1:]):
        # A decoder budget is not a successful translation. Retry smaller
        # source pieces rather than silently accepting an unfinished output.
        if len(text) <= 1:
            raise RuntimeError("Translation exceeded its output limit")
        cut = len(text) // 2
        space = text.rfind(" ", 0, cut)
        if space > cut // 2:
            cut = space + 1
        return " ".join(_translate_chunk_loaded(part) for part in (text[:cut], text[cut:]) if part.strip())

    decoded = TRANSLATION_TOKENIZER.batch_decode(
        generated,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=True,
    )
    translated = decoded[0].strip() if decoded else ""
    translated = re.sub(r"\s+", " ", translated).strip()
    translated = re.sub(r"\s+([,.;:!?%])", r"\1", translated)
    return translated


def _translate_text_loaded(text: str) -> str:
    """Translate every input token; split before tokenization can truncate it."""
    if not text.strip():
        return ""
    # Token boundaries are measured with the actual translation tokenizer.
    # Split strings rather than decode/re-encode IDs to preserve the source.
    # Marian is sentence-oriented. Its 512-token encoder limit is not a
    # reliable paragraph size: 475-token Thai chunks omitted whole clauses in
    # our coverage probe, while short chunks retained all 25 numeric markers.
    budget = 40
    pieces = re.split(r"(?<=[.!?。！？])\s+|\n+", text.strip())
    chunks = []
    for piece in pieces:
        remaining = piece
        while remaining:
            if len(TRANSLATION_TOKENIZER.encode(remaining)) <= budget:
                chunks.append(remaining)
                break
            low, high = 1, len(remaining)
            while low < high:
                mid = (low + high + 1) // 2
                if len(TRANSLATION_TOKENIZER.encode(remaining[:mid])) <= budget:
                    low = mid
                else:
                    high = mid - 1
            cut = low
            space = remaining.rfind(" ", 0, cut)
            if space > cut // 2:
                cut = space + 1
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
    return " ".join(_translate_chunk_loaded(chunk) for chunk in chunks if chunk.strip())


def load_translation_model() -> None:
    global DEVICE, TRANSLATION_MODEL, TRANSLATION_TOKENIZER

    if TRANSLATION_MODEL is not None and TRANSLATION_TOKENIZER is not None:
        return

    import_runtime_modules()
    import_translation_modules()

    DEVICE = resolve_device()
    model_name = CONFIG.get("TYPHOON_TRANSLATE_MODEL", "Helsinki-NLP/opus-mt-th-en")

    log(f"Loading translation model: {model_name} on {DEVICE.upper()}")
    TRANSLATION_TOKENIZER = AUTO_TOKENIZER.from_pretrained(model_name)
    TRANSLATION_MODEL = AUTO_MODEL_FOR_SEQ2SEQ_LM.from_pretrained(model_name)
    if DEVICE == "cuda":
        TRANSLATION_MODEL.to(DEVICE)
    TRANSLATION_MODEL.eval()

    _translate_text_loaded("สวัสดีครับ")
    log("Translation warm-up completed")


def prepare_audio(input_path: Path) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(f"Audio file not found: {input_path}")

    with tempfile.NamedTemporaryFile(prefix="voice_agent_", suffix=".wav", delete=False) as tmp:
        output_path = Path(tmp.name)

    timeout = float(CONFIG.get("TYPHOON_FFMPEG_TIMEOUT", "30"))
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, timeout=timeout)
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    return output_path


def read_duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as handle:
        frames = handle.getnframes()
        frame_rate = handle.getframerate() or 1
    return frames / frame_rate


def load_replacements() -> list[tuple[str, str]]:
    if "TYPHOON_REPLACEMENTS_TEXT" in CONFIG:
        contents = CONFIG["TYPHOON_REPLACEMENTS_TEXT"]
    else:
        replacement_path = Path(CONFIG["TYPHOON_REPLACEMENTS_FILE"])
        if not replacement_path.exists():
            return []
        contents = replacement_path.read_text(encoding="utf-8", errors="ignore")

    replacements: list[tuple[str, str]] = []
    for line in contents.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in stripped:
            source, target = stripped.split("\t", 1)
        elif "=>" in stripped:
            source, target = stripped.split("=>", 1)
        else:
            continue
        if source.strip():
            replacements.append((source.strip(), target.strip()))
    return replacements


def postprocess_text(text: str, profile: str) -> str:
    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.;:!?%])", r"\1", cleaned)
    cleaned = re.sub(r"([([{])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([)\]}])", r"\1", cleaned)

    if normalize_profile(profile) in {"smart", "th_to_eng"}:
        for source, target in load_replacements():
            cleaned = cleaned.replace(source, target)

    return cleaned.strip()


def translate_text(text: str) -> str:
    if not text.strip():
        return ""

    load_translation_model()
    return _translate_text_loaded(text)


def extract_text(result) -> str:
    if not result:
        return ""
    return " ".join(
        item if isinstance(item, str) else str(getattr(item, "text", item))
        for item in result
    ).strip()


def transcribe_loaded(audio_path: Path):
    if get_asr_backend(CONFIG) == "qwen":
        import soundfile as sf
        from qwen_asr.inference.utils import split_audio_into_chunks

        # Re-detect language around quiet boundaries every ~10s. Long mixed
        # passages can otherwise be transliterated into the dominant language.
        # prepare_audio (and warm-up) supplies mono 16 kHz audio.
        samples, sample_rate = sf.read(str(audio_path), dtype="float32")
        if not len(samples):
            return []
        chunks = [(chunk, sample_rate) for chunk, _ in split_audio_into_chunks(
            samples, sample_rate, max_chunk_sec=10.0,
        )]
        language = CONFIG.get("TYPHOON_ASR_LANGUAGE", "auto").strip()
        return MODEL.transcribe(
            audio=chunks,
            language=None if language.lower() in {"", "auto"} else language,
        )
    return MODEL.transcribe(audio=[str(audio_path)])


def transcribe_audio(audio_path: Path, profile: str | None = None) -> dict:
    load_model()

    active_profile = normalize_profile(profile or get_active_profile(CONFIG))
    processed_path = prepare_audio(audio_path)

    try:
        audio_duration = read_duration(processed_path)
        start = time.perf_counter()
        with MODEL_LOCK:
            with TORCH.inference_mode():
                raw_result = transcribe_loaded(processed_path)

        source_text = postprocess_text(extract_text(raw_result), active_profile)
        text = translate_text(source_text) if active_profile == "th_to_eng" else source_text
        processing_time = time.perf_counter() - start

        return {
            "ok": True,
            "text": text,
            "source_text": source_text,
            "profile": active_profile,
            "device": DEVICE,
            "model": CONFIG["TYPHOON_MODEL"],
            "backend": get_asr_backend(CONFIG),
            "language": getattr(raw_result[0], "language", "") if raw_result else "",
            "translate_model": CONFIG.get("TYPHOON_TRANSLATE_MODEL", "Helsinki-NLP/opus-mt-th-en"),
            "translation_applied": active_profile == "th_to_eng",
            "audio_duration": audio_duration,
            "processing_time": processing_time,
            "rtf": (processing_time / audio_duration) if audio_duration else 0.0,
        }
    finally:
        processed_path.unlink(missing_ok=True)


class TyphoonHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw_request = self.rfile.readline()
            if not raw_request:
                return

            request = json.loads(raw_request.decode("utf-8"))
            action = request.get("action")

            if action == "ping":
                response = {
                    "ok": True,
                    "profile": get_active_profile(CONFIG),
                    "device": DEVICE,
                    "model": CONFIG["TYPHOON_MODEL"],
                    "backend": get_asr_backend(CONFIG),
                    "translate_model": CONFIG.get("TYPHOON_TRANSLATE_MODEL", "Helsinki-NLP/opus-mt-th-en"),
                }
            elif action == "translate":
                source_text = str(request.get("text", ""))
                response = {
                    "ok": True,
                    "text": translate_text(source_text),
                    "source_text": source_text,
                    "device": DEVICE,
                    "translate_model": CONFIG.get("TYPHOON_TRANSLATE_MODEL", "Helsinki-NLP/opus-mt-th-en"),
                }
            elif action == "transcribe":
                audio_path = Path(request["audio_path"]).resolve()
                response = transcribe_audio(audio_path, request.get("profile"))
            else:
                response = {"ok": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")


class TyphoonServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def cleanup() -> None:
    if OWNS_SOCKET:
        SOCKET_FILE.unlink(missing_ok=True)
    try:
        current_pid = SERVICE_PID_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        current_pid = ""
    if current_pid == str(os.getpid()):
        SERVICE_PID_FILE.unlink(missing_ok=True)


def handle_signal(_signum, _frame) -> None:
    raise SystemExit(0)


def main() -> int:
    global OWNS_SOCKET

    parser = argparse.ArgumentParser(description="Persistent Typhoon ASR worker")
    parser.add_argument(
        "--preload-only",
        action="store_true",
        help="Download and warm the ASR model, then exit",
    )
    parser.add_argument(
        "--preload-translation",
        action="store_true",
        help="Download and warm the Thai-to-English translation model, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    atexit.register(cleanup)

    if args.preload_only:
        load_model()
    if args.preload_translation:
        load_translation_model()
    if args.preload_only or args.preload_translation:
        return 0

    load_model()

    SOCKET_FILE.unlink(missing_ok=True)
    SERVICE_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    OWNS_SOCKET = True

    log(f"Typhoon service ready on {SOCKET_FILE}")
    with TyphoonServer(str(SOCKET_FILE), TyphoonHandler) as server:
        server.serve_forever()

    return 0


if __name__ == "__main__":
    sys.exit(main())
