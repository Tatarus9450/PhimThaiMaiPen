"""Backend routing and profile regression checks; no model download required."""
import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import typhoon_service as service
from typhoon_backend import get_asr_backend


class BackendTests(unittest.TestCase):
    def test_existing_typhoon_config_still_uses_nemo(self):
        self.assertEqual(get_asr_backend({"TYPHOON_MODEL": "scb10x/typhoon-asr-realtime"}), "typhoon")
        self.assertEqual(get_asr_backend({"TYPHOON_MODEL": "Qwen/Qwen3-ASR-0.6B"}), "qwen")
        self.assertEqual(get_asr_backend({"TYPHOON_ASR_BACKEND": "qwen", "TYPHOON_MODEL": "/models/local"}), "qwen")
        with self.assertRaises(ValueError):
            get_asr_backend({"TYPHOON_ASR_BACKEND": "typo"})

    def test_qwen_language_detection_and_override(self):
        model = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "MODEL", model), patch.dict(service.CONFIG, {"TYPHOON_ASR_BACKEND": "qwen"}):
            audio = Path(directory) / "sample.wav"
            service._write_silence_wav(audio, duration_ms=31000)
            for language, expected in [("auto", None), ("Thai", "Thai"), ("English", "English")]:
                with patch.dict(service.CONFIG, {"TYPHOON_ASR_LANGUAGE": language}):
                    service.transcribe_loaded(audio)
                    kwargs = model.transcribe.call_args.kwargs
                    self.assertEqual(kwargs["language"], expected)
                    lengths = [len(chunk[0]) for chunk in kwargs["audio"]]
                    self.assertGreater(len(lengths), 1)
                    self.assertEqual(sum(lengths), 31 * 16000)
                    self.assertTrue(all(length <= 15 * 16000 for length in lengths))
                    self.assertTrue(all(chunk[1] == 16000 for chunk in kwargs["audio"]))

    def test_all_chunk_transcripts_are_preserved(self):
        self.assertEqual(service.extract_text([SimpleNamespace(text="สวัสดี"), SimpleNamespace(text="Hello")]), "สวัสดี Hello")
        self.assertEqual(service.extract_text(["legacy transcript"]), "legacy transcript")
        self.assertEqual(service.extract_text([]), "")

    def test_typhoon_does_not_receive_qwen_arguments(self):
        model = Mock()
        with patch.object(service, "MODEL", model), patch.dict(service.CONFIG, {"TYPHOON_ASR_BACKEND": "typhoon"}):
            service.transcribe_loaded(Path("sample.wav"))
            model.transcribe.assert_called_once_with(audio=["sample.wav"])

    def test_profiles_preserve_mixed_text_and_translate_only_when_requested(self):
        text = "วันนี้ทดสอบ Python and English"
        for profile in ("raw", "smart", "th_to_eng"):
            with self.subTest(profile=profile):
                processed = Mock()
                torch = SimpleNamespace(inference_mode=nullcontext)
                with patch.object(service, "load_model"), patch.object(service, "TORCH", torch), \
                     patch.object(service, "prepare_audio", return_value=processed), \
                     patch.object(service, "read_duration", return_value=2.0), \
                     patch.object(service, "transcribe_loaded", return_value=[SimpleNamespace(text=text, language="Thai")]), \
                     patch.object(service, "load_replacements", return_value=[]), \
                     patch.object(service, "translate_text", return_value="Testing Python and English today") as translate:
                    result = service.transcribe_audio(Path("input.wav"), profile)
                    self.assertEqual(result["source_text"], text)
                    self.assertEqual(result["language"], "Thai")
                    self.assertEqual(result["translation_applied"], profile == "th_to_eng")
                    if profile == "th_to_eng":
                        translate.assert_called_once_with(text)
                        self.assertEqual(result["text"], "Testing Python and English today")
                    else:
                        translate.assert_not_called()
                        self.assertEqual(result["text"], text)
                    processed.unlink.assert_called_once_with(missing_ok=True)

    def test_inference_failure_cleans_prepared_audio(self):
        processed = Mock()
        with patch.object(service, "load_model"), \
             patch.object(service, "TORCH", SimpleNamespace(inference_mode=nullcontext)), \
             patch.object(service, "prepare_audio", return_value=processed), \
             patch.object(service, "read_duration", return_value=1.0), \
             patch.object(service, "transcribe_loaded", side_effect=RuntimeError("inference failed")):
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                service.transcribe_audio(Path("input.wav"), "raw")
            processed.unlink.assert_called_once_with(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
