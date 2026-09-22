"""Language compatibility and NPU fallback never download optional models."""
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

import typhoon_service as service
from phimthai import fastflowlm_backend, worker
from phimthai.models import CATALOG
from phimthai.settings import DEFAULT_MODEL, Settings


class NpuFallbackTests(unittest.TestCase):
    def setUp(self):
        self.paths = {
            "whisper-turbo-amd": Path("/synthetic/npu"),
            DEFAULT_MODEL: Path("/synthetic/typhoon"),
        }
        self.cpu_calls = []

        def transcribe(audio, profile):
            self.cpu_calls.append({key: service.CONFIG[key] for key in
                                   ("TYPHOON_MODEL", "TYPHOON_ASR_BACKEND", "TYPHOON_ASR_LANGUAGE")})
            return {"ok": True, "text": "fixture transcript", "source_text": "fixture transcript",
                    "device": "cpu", "audio_duration": 3, "processing_time": 1}

        self.npu_transcribe = Mock(side_effect=RuntimeError("NPU unavailable"))
        for patcher in (
            patch.dict(service.CONFIG, {}),
            patch("phimthai.worker.local_model", side_effect=lambda model, **_: self.paths.get(model)),
            patch.object(service, "import_runtime_modules"),
            patch.object(service, "transcribe_audio", side_effect=transcribe),
            patch("phimthai.worker.select_device", return_value=("cpu", "")),
            patch("phimthai.performance.record"),
            patch.object(fastflowlm_backend, "transcribe", self.npu_transcribe),
            patch.object(fastflowlm_backend, "stop"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def transcribe(self, language):
        settings = Settings(model="whisper-turbo-amd", device="npu", language=language, profile="raw")
        return worker.run_inference({"action": "transcribe", "audio": "/synthetic/speech.wav",
                                     "settings": asdict(settings)})

    def assert_cpu_model(self, model, language):
        self.assertEqual(self.cpu_calls, [{"TYPHOON_MODEL": str(self.paths[model]),
                                          "TYPHOON_ASR_BACKEND": CATALOG[model].backend,
                                          "TYPHOON_ASR_LANGUAGE": language}])

    def test_english_without_qwen_requests_optional_download_without_typhoon_inference(self):
        with self.assertRaisesRegex(RuntimeError, "Download Qwen3-ASR 0.6B"):
            self.transcribe("English")
        self.assertEqual(self.cpu_calls, [])
        self.npu_transcribe.assert_not_called()

    def test_english_with_qwen_uses_qwen_cpu_and_names_actual_model(self):
        self.paths["qwen-0.6b"] = Path("/synthetic/qwen")
        result = self.transcribe("English")
        self.assert_cpu_model("qwen-0.6b", "English")
        self.assertEqual(result["model"], CATALOG["qwen-0.6b"].repo)
        self.assertIn("Qwen3-ASR 0.6B on CPU", result["warning"])
        self.assertNotIn("Thai speech only", result["warning"])

    def test_auto_without_qwen_uses_typhoon_and_warns_thai_only(self):
        result = self.transcribe("auto")
        self.npu_transcribe.assert_called_once()
        self.assert_cpu_model(DEFAULT_MODEL, "auto")
        self.assertEqual(result["model"], CATALOG[DEFAULT_MODEL].repo)
        self.assertIn("Typhoon ASR Realtime on CPU", result["warning"])
        self.assertIn("Thai speech only", result["warning"])

    def test_auto_with_qwen_prefers_installed_multilingual_fallback(self):
        self.paths["qwen-0.6b"] = Path("/synthetic/qwen")
        result = self.transcribe("auto")
        self.assert_cpu_model("qwen-0.6b", "auto")
        self.assertIn("Qwen3-ASR 0.6B on CPU", result["warning"])

    def test_auto_without_either_model_requests_typhoon_download(self):
        self.paths.pop(DEFAULT_MODEL)
        with self.assertRaisesRegex(RuntimeError, "Download Typhoon ASR Realtime"):
            self.transcribe("auto")
        self.assertEqual(self.cpu_calls, [])


class TyphoonLanguageTests(unittest.TestCase):
    def test_english_is_rejected_before_loading_or_switching_models(self):
        settings = Settings(model=DEFAULT_MODEL, language="English")
        with patch("phimthai.worker.local_model") as local, \
                patch.object(service, "import_runtime_modules") as runtime, \
                patch.object(service, "transcribe_audio") as transcribe:
            with self.assertRaisesRegex(RuntimeError, "Typhoon รองรับเสียงภาษาไทยเท่านั้น.*เลือก Qwen"):
                worker.run_inference({"action": "transcribe", "audio": "/synthetic/english.wav",
                                      "settings": asdict(settings)})
            local.assert_not_called()
            runtime.assert_not_called()
            transcribe.assert_not_called()

    def test_text_translation_ignores_asr_language_and_does_not_require_asr_model(self):
        settings = Settings(model=DEFAULT_MODEL, language="English")
        with patch.dict(service.CONFIG, {}), \
                patch("phimthai.worker.local_model", return_value=Path("/synthetic/translation")) as local, \
                patch.object(service, "import_runtime_modules"), \
                patch("phimthai.worker.select_device", return_value=("cpu", "")), \
                patch.object(service, "transcribe_audio") as transcribe, \
                patch.object(service, "translate_text", return_value="Hello") as translate, \
                patch("phimthai.performance.record"):
            result = worker.run_inference({"action": "translate", "text": "สวัสดี",
                                           "settings": asdict(settings)})
            local.assert_called_once_with("translate-th-en", verify=True)
            transcribe.assert_not_called()
            translate.assert_called_once_with("สวัสดี")
            self.assertTrue(result["ok"])
            self.assertEqual(result["text"], "Hello")
            self.assertEqual(result["model"], CATALOG["translate-th-en"].repo)


if __name__ == "__main__":
    unittest.main()
