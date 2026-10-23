"""Worker warmup loads the in-process model without running a transcription."""
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

import typhoon_service as service
from phimthai import worker
from phimthai.settings import Settings


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.load = Mock()
        for patcher in (
            patch.dict(service.CONFIG, {}),
            patch("phimthai.worker.local_model", return_value=Path("/synthetic/model")),
            patch.object(service, "import_runtime_modules"),
            patch.object(service, "load_model", self.load),
            patch.object(service, "transcribe_audio", side_effect=AssertionError("no inference on warmup")),
            patch("phimthai.worker.select_device", return_value=("cpu", "")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def warm(self, **settings):
        return worker.run({"action": "warmup", "id": "w", "settings": asdict(Settings(**settings))})

    def test_typhoon_warmup_loads_model(self):
        result = self.warm(model="typhoon-realtime", language="Thai")
        self.assertEqual((result["ok"], result["warmup"], result["loaded"]), (True, True, True))
        self.load.assert_called_once()
        self.assertEqual(service.CONFIG["TYPHOON_MODEL"], "/synthetic/model")
        self.assertEqual(service.CONFIG["TYPHOON_ASR_BACKEND"], "typhoon")
        self.assertEqual(service.CONFIG["TYPHOON_DEVICE"], "cpu")

    def test_qwen_warmup_loads_model(self):
        self.assertTrue(self.warm(model="qwen-0.6b")["loaded"])
        self.assertEqual(service.CONFIG["TYPHOON_ASR_BACKEND"], "qwen")

    def test_other_backends_and_unsupported_language_noop(self):
        self.assertFalse(self.warm(model="whisper-tiny-ov")["loaded"])
        self.assertFalse(self.warm(model="typhoon-realtime", language="English")["loaded"])
        self.load.assert_not_called()

    def test_missing_model_raises(self):
        with patch("phimthai.worker.local_model", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Model missing"):
                self.warm(model="typhoon-realtime")


if __name__ == "__main__":
    unittest.main()
