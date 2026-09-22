"""Pinned model catalog and verified, resumable Hugging Face downloads."""
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .settings import data_dir


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    repo: str
    revision: str
    memory_gb: int
    license: str = "Apache-2.0"
    backend: str = "qwen"
    languages: tuple = ("Thai", "English", "28 other languages")
    devices: tuple = ("cpu", "gpu")
    download_gb: float = 0.0
    kind: str = "asr"
    status: str = "experimental"
    files: tuple = ()
    origin: str = "catalog"
    tags: tuple = ()


CATALOG = {
    "typhoon-realtime": ModelSpec("typhoon-realtime", "Typhoon ASR Realtime", "scb10x/typhoon-asr-realtime",
                           "2c58a30ba9a3bf92d095a5df91bec6996f04c3a1", 4, license="CC-BY-4.0", backend="typhoon",
                           languages=("Thai",), download_gb=0.462, files=("typhoon-asr-realtime.nemo",),
                           status="Default Thai model from version 1.0", tags=("เบาที่สุด", "ค่าเริ่มต้น")),
    "qwen-0.6b": ModelSpec("qwen-0.6b", "Qwen3-ASR 0.6B", "Qwen/Qwen3-ASR-0.6B",
                           "5eb144179a02acc5e5ba31e748d22b0cf3e303b0", 7, download_gb=1.89, status="CPU tested on Fedora KDE",
                           tags=("ดีที่สุด", "Optional")),
    "qwen-1.7b": ModelSpec("qwen-1.7b", "Qwen3-ASR 1.7B", "Qwen/Qwen3-ASR-1.7B",
                           "7278e1e70fe206f11671096ffdd38061171dd6e5", 12, download_gb=4.71, tags=("ดีที่สุด", "Optional")),
    "whisper-tiny-ov": ModelSpec("whisper-tiny-ov", "Whisper Tiny INT8 · OpenVINO", "OpenVINO/whisper-tiny-int8-ov",
                           "a850762d97243dee30f46ca309720541af619ab0", 2, backend="openvino", languages=("Thai", "English", "multilingual"), devices=("cpu", "gpu", "npu"), download_gb=0.048, status="CPU tested; low Thai accuracy in initial samples. Intel NPU unverified"),
    "whisper-turbo-ov": ModelSpec("whisper-turbo-ov", "Whisper Turbo INT8 · OpenVINO", "OpenVINO/whisper-large-v3-turbo-int8-ov",
                           "b568445dd5dc8c695bde596f8acbb4694fd6ba64", 4, license="MIT", backend="openvino", languages=("Thai", "English", "multilingual"), devices=("cpu", "gpu", "npu"), download_gb=0.828, status="CPU tested on Fedora; Intel GPU/NPU need hardware verification"),
    "translate-th-en": ModelSpec("translate-th-en", "Thai → English translation", "Helsinki-NLP/opus-mt-th-en",
                           "0fff80be1c3f40d6180efd59f566ece956ace689", 2, backend="marian", languages=("Thai to English",), download_gb=0.311, kind="translation", status="CPU tested with short segments; long-input coverage tested, review translation accuracy"),
    "whisper-turbo-amd": ModelSpec("whisper-turbo-amd", "Whisper Turbo · AMD NPU", "FastFlowLM/Whisper-V3-Turbo-NPU2",
                           "594eecd2d80b20cbb04ef0099162335d1dd1899a", 2, license="MIT", backend="fastflowlm",
                           devices=("npu",), download_gb=0.653, status="Experimental: needs patched FastFlowLM 1.0.5. Thai accuracy below Qwen in initial samples"),
    "whisper-turbo-vulkan": ModelSpec("whisper-turbo-vulkan", "Whisper Turbo Q5 · CPU / Vulkan GPU", "ggerganov/whisper.cpp",
                           "5359861c739e955e79d9a303bcbc70fb988958b1", 3, license="MIT", backend="vulkan",
                           languages=("Thai", "English", "multilingual"), devices=("cpu", "gpu"), download_gb=0.574,
                           files=("ggml-large-v3-turbo-q5_0.bin",), status="Experimental; requires packaged whisper.cpp runtime"),
}
VERIFIED = {}
BUILTIN_CATALOG = dict(CATALOG)


def refresh_catalog():
    from .external_models import load_specs
    CATALOG.clear()
    CATALOG.update(BUILTIN_CATALOG)
    CATALOG.update(load_specs())


def digest(path, algorithm="sha256", git_blob=False):
    sha = hashlib.new(algorithm)
    if git_blob:
        sha.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def required_files(files, backend="qwen"):
    if backend == "typhoon":
        return "typhoon-asr-realtime.nemo" in files
    if backend == "vulkan":
        return "ggml-large-v3-turbo-q5_0.bin" in files
    if backend == "fastflowlm":
        return all(name in files for name in ("config.json", "model.q4nx", "tokenizer.json", "tokenizer_config.json"))
    if backend == "openvino":
        return all(name in files for name in ("config.json", "openvino_encoder_model.xml", "openvino_encoder_model.bin", "openvino_decoder_model.xml", "openvino_decoder_model.bin"))
    if backend == "marian":
        return all(name in files for name in ("config.json", "source.spm", "target.spm", "pytorch_model.bin"))
    return "config.json" in files and any(name.endswith(".safetensors") for name in files) and "tokenizer_config.json" in files


def check_files(directory, files, verify, backend="qwen"):
    if not isinstance(files, dict) or not required_files(files, backend):
        return False
    signature = []
    for name, metadata in files.items():
        path = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or not isinstance(metadata, dict):
            return False
        expected = metadata.get("sha256", "")
        if len(expected) != 64 or not path.is_file() or path.stat().st_size != metadata.get("size"):
            return False
        stat = path.stat()
        signature.append((name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, expected))
    if verify and VERIFIED.get(str(directory)) != signature:
        for name, metadata in files.items():
            if digest(directory / name) != metadata["sha256"]:
                return False
        VERIFIED[str(directory)] = signature
    return True


def model_dir(model_id):
    if model_id not in CATALOG:
        raise ValueError("Unknown model")
    return data_dir() / "models" / ("Whisper-V3-Turbo-NPU2" if model_id == "whisper-turbo-amd" else model_id)


def local_model(model_id, verify=False):
    spec = CATALOG[model_id]
    directory = model_dir(model_id)
    manifest = directory / "verified.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text())
            if data.get("version") == 2 and data.get("revision") == spec.revision and check_files(directory, data.get("files"), verify, spec.backend):
                return directory
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None
    # Reuse this user's existing Qwen cache without copying gigabytes. Managed
    # downloads remain under XDG_DATA_HOME and survive application updates.
    legacy = Path(__file__).resolve().parent.parent / ".cache/huggingface/hub"
    cached = legacy / ("models--" + spec.repo.replace("/", "--")) / "snapshots" / spec.revision
    if cached.is_dir() and required_files({p.name for p in cached.iterdir()}, spec.backend):
        if verify:
            signature = [(str(p), p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in cached.iterdir() if p.is_file()]
            if VERIFIED.get(str(cached)) != signature:
                for path in cached.iterdir():
                    if path.is_file():
                        blob = path.resolve().name
                        if not path.is_symlink() or len(blob) not in {40, 64}:
                            return None
                        if digest(path, "sha1" if len(blob) == 40 else "sha256", len(blob) == 40) != blob:
                            return None
                VERIFIED[str(cached)] = signature
        return cached
    return None


def installed_size(model_id):
    path = local_model(model_id)
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path else 0


def download(model_id, progress=lambda event: None):
    from huggingface_hub import HfApi, hf_hub_download
    spec = CATALOG[model_id]
    if spec.origin == "local":
        raise ValueError("โมเดลนำเข้าเองไม่มีแหล่งดาวน์โหลดอัตโนมัติ ให้นำเข้าจากโฟลเดอร์ต้นฉบับอีกครั้ง")
    target = model_dir(model_id)
    target.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(spec.repo, revision=spec.revision, files_metadata=True)
    files = [f for f in info.siblings if (f.rfilename in spec.files if spec.files else
             f.rfilename.endswith((".json", ".safetensors", ".txt", ".model", ".xml", ".bin", ".spm", ".q4nx")) and not f.rfilename.startswith("."))]
    total = sum(f.size or 0 for f in files)
    existing = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    remaining = max(0, total - existing)
    if shutil.disk_usage(target).free < remaining * 1.1 + 10_000_000:
        raise RuntimeError(f"Need approximately {remaining * 1.1 / 1e9:.1f} GB additional free disk space")
    completed = 0
    verified = {}
    for file in files:
        progress({"file": file.rfilename, "completed": completed, "total": total})
        path = Path(hf_hub_download(spec.repo, file.rfilename, revision=spec.revision, local_dir=target))
        expected = file.lfs.sha256 if file.lfs else file.blob_id
        for attempt in range(2):
            actual = digest(path, "sha256" if file.lfs else "sha1", not file.lfs)
            if actual == expected:
                break
            path.unlink(missing_ok=True)
            if attempt:
                raise RuntimeError(f"Integrity check failed: {file.rfilename}. Retry Download to repair.")
            path = Path(hf_hub_download(spec.repo, file.rfilename, revision=spec.revision, local_dir=target, force_download=True))
        verified[file.rfilename] = {"size": path.stat().st_size, "sha256": actual if file.lfs else digest(path)}
        completed += path.stat().st_size
    if not required_files(verified, spec.backend):
        raise RuntimeError("Model repository is missing required files")
    manifest = {"version": 2, "revision": spec.revision, "files": verified}
    pending = target / "verified.json.tmp"
    pending.write_text(json.dumps(manifest, indent=2))
    pending.replace(target / "verified.json")
    progress({"completed": completed, "total": total, "done": True})


def remove(model_id):
    target = model_dir(model_id)
    if target.exists():
        shutil.rmtree(target)
    if model_id.startswith("local-"):
        CATALOG.pop(model_id, None)


def main():
    import sys
    try:
        progress = lambda e: print(json.dumps(e), flush=True)
        if sys.argv[1] == "--import":
            from .external_models import import_folder
            import_folder(sys.argv[2], progress)
        else:
            download(sys.argv[1], progress)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        raise SystemExit(1)


refresh_catalog()

if __name__ == "__main__":
    main()
