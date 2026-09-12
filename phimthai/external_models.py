"""Import supported model data; never execute or download external model code."""
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from .settings import data_dir

LOCAL_ID = re.compile(r"local-[0-9a-f]{32}\Z")
SUFFIXES = {".json", ".safetensors", ".txt", ".model", ".xml", ".bin", ".spm"}


def load_specs():
    """Read only app-owned registrations, never infer an upstream identity."""
    from .models import ModelSpec
    result = {}
    for path in (data_dir() / "models").glob("local-*/model-spec.json"):
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                continue
            if not LOCAL_ID.fullmatch(path.parent.name) or value.get("id") != path.parent.name:
                continue
            if value.get("origin") != "local" or value.get("backend") not in {"qwen", "openvino", "vulkan"}:
                continue
            if value.get("kind") != "asr" or not isinstance(value.get("revision"), str):
                continue
            for key in ("languages", "devices", "files"):
                value[key] = tuple(value[key])
            if value["backend"] == "vulkan" and value["files"] != ("ggml-large-v3-turbo-q5_0.bin",):
                continue
            result[value["id"]] = ModelSpec(**value)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return result


def inspect_folder(folder):
    """Recognize data formats implemented by our existing inference backends."""
    if not folder.is_dir():
        raise ValueError("เลือกโฟลเดอร์โมเดลที่ดาวน์โหลดไว้")
    config_path = folder / "config.json"
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    if not isinstance(config, dict) or config.get("auto_map"):
        raise ValueError("ไม่รองรับโมเดลที่ต้องรันโค้ดภายนอก (auto_map)")
    if config.get("model_type") == "qwen3_asr":
        backend, memory = "qwen", 7
    elif config.get("model_type") == "whisper" and (folder / "openvino_encoder_model.xml").is_file():
        backend, memory = "openvino", 4
    elif (folder / "ggml-large-v3-turbo-q5_0.bin").is_file():
        backend, memory = "vulkan", 3
    else:
        raise ValueError("รองรับ Qwen3-ASR (SafeTensors), Whisper OpenVINO หรือ Whisper Turbo GGML Q5 เท่านั้น")
    files = {}
    # Standard supported snapshots have root-level assets. Deliberately omit
    # caches, scripts and arbitrary nested content from the imported package.
    for source in folder.iterdir():
        if source.name in {"verified.json", "model-spec.json"} or source.suffix not in SUFFIXES:
            continue
        if not source.is_file():
            continue
        if backend == "qwen" and source.suffix == ".bin":
            raise ValueError("Qwen ภายนอกต้องใช้ SafeTensors ไม่รองรับน้ำหนัก pickle / .bin")
        if source.suffix == ".json":
            document = json.loads(source.read_text())
            if isinstance(document, dict) and document.get("auto_map"):
                raise ValueError("ไม่รองรับโมเดลที่ต้องรันโค้ดภายนอก (auto_map)")
            if source.name.endswith(".index.json"):
                for name in document.get("weight_map", {}).values():
                    if Path(name).name != name or not (folder / name).is_file():
                        raise ValueError("ไฟล์น้ำหนักโมเดลไม่ครบ หรือมีพาธที่ไม่รองรับ")
        files[source.name] = source
    from .models import required_files
    if not required_files(files, backend):
        raise ValueError("ไฟล์โมเดลไม่ครบ ต้องมี config, tokenizer และน้ำหนักของรูปแบบที่เลือก")
    if backend in {"qwen", "openvino"} and not (
        "tokenizer.json" in files or {"vocab.json", "merges.txt"}.issubset(files)
    ):
        raise ValueError("ขาด tokenizer.json หรือ vocab.json + merges.txt")
    return backend, memory, files


def import_folder(source, progress=lambda event: None):
    from .models import ModelSpec, digest
    folder = Path(source).expanduser().resolve()
    backend, memory, files = inspect_folder(folder)
    destination = data_dir() / "models"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    total = sum(path.stat().st_size for path in files.values())
    if shutil.disk_usage(destination).free < total * 1.1 + 10_000_000:
        raise RuntimeError(f"ต้องมีพื้นที่ว่างเพิ่มประมาณ {total * 1.1 / 1e9:.2f} GB สำหรับนำเข้าโมเดล")
    identifier = "local-" + uuid.uuid4().hex
    completed, verified = 0, {}
    with tempfile.TemporaryDirectory(prefix=f".import-{os.getpid()}-", dir=destination) as temporary:
        staging = Path(temporary)
        for name, path in files.items():
            # Hugging Face snapshot symlinks are resolved into owned copies.
            # Never copy a FIFO/device, even if the source changed since inspection.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as incoming:
                before = os.fstat(incoming.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("นำเข้าได้เฉพาะไฟล์โมเดลปกติ")
                with (staging / name).open("wb") as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        outgoing.write(chunk)
                        completed += len(chunk)
                        progress({"file": name, "completed": completed, "total": total, "importing": True})
                after = os.fstat(incoming.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("ไฟล์ต้นฉบับเปลี่ยนระหว่างนำเข้า กรุณาลองใหม่")
            verified[name] = {"size": (staging / name).stat().st_size, "sha256": digest(staging / name)}
        inspect_folder(staging)  # Validate the copies, not only the source paths.
        import hashlib
        revision = "local-" + hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
        spec = ModelSpec(identifier, folder.name[:100] + " · นำเข้าเอง", "Local model", revision, memory,
                         license="ตรวจสิทธิ์จากแหล่งที่คุณดาวน์โหลด", backend=backend,
                         devices=("cpu", "gpu", "npu") if backend == "openvino" else ("cpu", "gpu"),
                         download_gb=total / 1e9, status="นำเข้าเอง · ตรวจไฟล์แล้ว ยังไม่รับรองความแม่นยำ",
                         files=("ggml-large-v3-turbo-q5_0.bin",) if backend == "vulkan" else (), origin="local")
        (staging / "verified.json").write_text(json.dumps({"version": 2, "revision": revision, "files": verified}))
        (staging / "model-spec.json").write_text(json.dumps(asdict(spec), ensure_ascii=False))
        staging.rename(destination / identifier)
    progress({"done": True, "model_id": identifier, "completed": completed, "total": total, "importing": True})
    return identifier


def cleanup_interrupted_import(process_id):
    """The parent calls this after its own import worker has stopped."""
    if not isinstance(process_id, int) or process_id <= 0:
        return
    for path in (data_dir() / "models").glob(f".import-{process_id}-*"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
