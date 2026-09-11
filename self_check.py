#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from typhoon_backend import (
    BASE,
    config_bool,
    ensure_service,
    get_asr_backend,
    get_service_python,
    load_config,
    ping_service,
    send_request,
    stop_service,
    transcribe_audio,
)


@dataclass
class CheckResult:
    name: str
    status: str
    message_th: str
    message_en: str
    details: str = ""


CONFIG = load_config()
SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "x11").strip().lower() or "x11"
if SESSION_TYPE not in {"x11", "wayland"}:
    SESSION_TYPE = "x11"


def bi(thai: str, english: str) -> str:
    return f"{thai} / {english}"


def print_result(result: CheckResult) -> None:
    prefix = {
        "pass": "[PASS]",
        "warn": "[WARN]",
        "fail": "[FAIL]",
    }[result.status]
    print(f"{prefix} {bi(result.message_th, result.message_en)}")
    if result.details:
        print(f"       {result.details}")


def result(status: str, name: str, thai: str, english: str, details: str = "") -> CheckResult:
    item = CheckResult(
        name=name,
        status=status,
        message_th=thai,
        message_en=english,
        details=details,
    )
    return item


def run_subprocess(command: list[str], timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(BASE),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def check_config_file() -> CheckResult:
    config_path = BASE / "config.env"
    if not config_path.exists():
        return result(
            "fail",
            "config",
            "ไม่พบไฟล์ config.env",
            "config.env is missing",
            f"Run ./install.sh first. Expected: {config_path}",
        )

    return result(
        "pass",
        "config",
        "พบไฟล์ config.env แล้ว",
        "Found config.env",
        str(config_path),
    )


def check_runtime_commands() -> CheckResult:
    missing: list[str] = []

    common_commands = ["ffmpeg", "arecord", "aplay", "notify-send", "python3"]
    for command in common_commands:
        if shutil.which(command) is None:
            missing.append(command)

    if SESSION_TYPE == "wayland":
        for command in ("wl-copy", "wl-paste"):
            if shutil.which(command) is None:
                missing.append(command)
        if shutil.which("wtype") is None and shutil.which("ydotool") is None:
            missing.append("wtype|ydotool")
    else:
        for command in ("xclip", "xdotool", "xbindkeys"):
            if shutil.which(command) is None:
                missing.append(command)

    if missing:
        return result(
            "fail",
            "commands",
            "ยังขาดคำสั่ง runtime บางตัว",
            "Some runtime commands are missing",
            ", ".join(missing),
        )

    return result(
        "pass",
        "commands",
        f"คำสั่ง runtime ครบสำหรับ session แบบ {SESSION_TYPE}",
        f"Runtime commands are available for the {SESSION_TYPE} session",
    )


def check_venv_runtime() -> CheckResult:
    python_bin = get_service_python(CONFIG)
    if not python_bin.exists():
        return result(
            "fail",
            "venv",
            "ไม่พบ Python ใน virtualenv",
            "The virtualenv Python interpreter is missing",
            str(python_bin),
        )

    modules = [
        "torch",
        "torchaudio",
        "transformers",
        "sentencepiece",
    ]
    modules.extend(
        ["qwen_asr"] if get_asr_backend(CONFIG) == "qwen"
        else ["nemo.collections.asr", "typhoon_asr"]
    )
    code = (
        "import importlib\n"
        f"modules = {modules!r}\n"
        "for name in modules:\n"
        "    importlib.import_module(name)\n"
        "print('ok')\n"
    )
    proc = run_subprocess([str(python_bin), "-c", code], timeout=240.0)
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout).strip().splitlines()
        return result(
            "fail",
            "venv",
            "virtualenv หรือ Python dependencies ยังไม่พร้อม",
            "The virtualenv or Python dependencies are not ready",
            details[-1] if details else str(python_bin),
        )

    return result(
        "pass",
        "venv",
        "virtualenv และ Python dependencies พร้อมใช้งาน",
        "The virtualenv and Python dependencies are ready",
        str(python_bin),
    )


def check_popup_support() -> CheckResult:
    if not config_bool(CONFIG, "POPUP_ENABLED", True):
        return result(
            "pass",
            "popup",
            "ปิด popup ไว้ใน config อยู่แล้ว",
            "The popup is already disabled in config",
        )

    proc = run_subprocess([sys.executable, "-c", "import tkinter; print('ok')"], timeout=30.0)
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout).strip().splitlines()
        return result(
            "warn",
            "popup",
            "popup อาจไม่ทำงาน เพราะ tkinter ใช้ไม่ได้",
            "The popup may not work because tkinter is unavailable",
            details[-1] if details else "Install the tkinter package for your distro.",
        )

    return result(
        "pass",
        "popup",
        "popup พร้อมใช้งาน",
        "The popup runtime is available",
    )


def check_service_health() -> CheckResult:
    started = time.perf_counter()
    ensure_service(wait=True, timeout=float(CONFIG["TYPHOON_STARTUP_TIMEOUT"]))
    healthy = ping_service(timeout=0.5)
    elapsed = time.perf_counter() - started

    if not healthy:
        return result(
            "fail",
            "service",
            "worker ถอดเสียง ไม่ตอบสนอง",
            "The ASR worker is not responding",
        )

    return result(
        "pass",
        "service",
        "worker ถอดเสียง พร้อมใช้งาน",
        "The ASR worker is ready",
        f"startup_check={elapsed:.2f}s",
    )


def write_silence_wav(path: Path, duration_ms: int = 600, sample_rate: int = 16000) -> None:
    frame_count = int(sample_rate * (duration_ms / 1000))
    silence = b"\x00\x00" * frame_count
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(silence)


def check_transcription_smoke() -> CheckResult:
    with tempfile.NamedTemporaryFile(prefix="voice_agent_smoke_", suffix=".wav", delete=False) as handle:
        wav_path = Path(handle.name)

    try:
        write_silence_wav(wav_path)
        response = transcribe_audio(wav_path, profile="raw", timeout=float(CONFIG["TYPHOON_REQUEST_TIMEOUT"]))
    finally:
        wav_path.unlink(missing_ok=True)

    text = str(response.get("text", ""))
    details = (
        f"profile={response.get('profile')} "
        f"text_len={len(text)} "
        f"audio={response.get('audio_duration', 0):.2f}s "
        f"rtf={response.get('rtf', 0.0):.2f}"
    )
    return result(
        "pass",
        "transcribe",
        "smoke test ฝั่งถอดเสียงผ่านแล้ว",
        "The transcription smoke test passed",
        details,
    )


def check_translation_smoke() -> CheckResult:
    timeout = float(CONFIG["TYPHOON_REQUEST_TIMEOUT"])
    try:
        response = send_request({"action": "translate", "text": "สวัสดีครับ"}, timeout=timeout)
    except Exception as exc:
        if "Unknown action: translate" not in str(exc):
            raise

        stop_service(timeout=5.0)
        ensure_service(wait=True, timeout=float(CONFIG["TYPHOON_STARTUP_TIMEOUT"]))
        response = send_request({"action": "translate", "text": "สวัสดีครับ"}, timeout=timeout)

    text = str(response.get("text", "")).strip()
    if not text:
        return result(
            "fail",
            "translate",
            "smoke test ฝั่งแปลภาษาล้มเหลว",
            "The translation smoke test failed",
            "The translation response was empty.",
        )

    has_ascii_letters = any("a" <= char.lower() <= "z" for char in text)
    if not has_ascii_letters:
        return result(
            "warn",
            "translate",
            "ได้ผลลัพธ์จากการแปล แต่ไม่เห็นตัวอักษรอังกฤษชัดเจน",
            "The translation returned text, but it does not clearly contain English letters",
            text,
        )

    return result(
        "pass",
        "translate",
        "smoke test ฝั่งแปลภาษาผ่านแล้ว",
        "The translation smoke test passed",
        text,
    )


def summarize(results: list[CheckResult], as_json: bool) -> int:
    failures = sum(1 for item in results if item.status == "fail")
    warnings = sum(1 for item in results if item.status == "warn")
    passes = sum(1 for item in results if item.status == "pass")

    if as_json:
        payload = {
            "ok": failures == 0,
            "summary": {
                "passes": passes,
                "warnings": warnings,
                "failures": failures,
                "session_type": SESSION_TYPE,
            },
            "results": [asdict(item) for item in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("")
        if failures == 0:
            print(bi("สรุป: self-check ผ่าน", "Summary: self-check passed"))
        else:
            print(bi("สรุป: self-check ไม่ผ่าน", "Summary: self-check failed"))
        print(
            bi(
                f"ผ่าน {passes} รายการ, เตือน {warnings}, ล้มเหลว {failures}",
                f"{passes} passed, {warnings} warnings, {failures} failures",
            )
        )

    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Phim Thai Mai Pen self-check / smoke test")
    parser.add_argument("--json", action="store_true", help="Print results as JSON")
    parser.add_argument(
        "--skip-translation",
        action="store_true",
        help="Skip the Thai-to-English translation smoke test",
    )
    args = parser.parse_args()

    checks = [
        check_config_file,
        check_runtime_commands,
        check_venv_runtime,
        check_popup_support,
        check_service_health,
        check_transcription_smoke,
    ]
    if not args.skip_translation:
        checks.append(check_translation_smoke)

    results: list[CheckResult] = []
    for check in checks:
        try:
            item = check()
        except Exception as exc:
            item = result(
                "fail",
                check.__name__,
                "เกิดข้อผิดพลาดระหว่าง self-check",
                "An error occurred during the self-check",
                str(exc),
            )
        results.append(item)
        if not args.json:
            print_result(item)

    return summarize(results, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
