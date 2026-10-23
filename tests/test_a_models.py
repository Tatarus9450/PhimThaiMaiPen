"""Model verification is persisted across processes and invalidated by any stat change."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phimthai import models
from phimthai.models import CATALOG, STAT_FILE, local_model


class PersistedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, {"XDG_DATA_HOME": self.temp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.saved = dict(models.VERIFIED)
        models.VERIFIED.clear()
        self.addCleanup(lambda: (models.VERIFIED.clear(), models.VERIFIED.update(self.saved)))
        self.model_id = "qwen-0.6b"
        self.directory = models.model_dir(self.model_id)
        self.directory.mkdir(parents=True)
        contents = {"config.json": b"{}", "tokenizer_config.json": b"{}", "model.safetensors": b"weights" * 100}
        files = {}
        for name, content in contents.items():
            (self.directory / name).write_bytes(content)
            files[name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        (self.directory / "verified.json").write_text(json.dumps(
            {"version": 2, "revision": CATALOG[self.model_id].revision, "files": files}))

    def new_process(self):
        models.VERIFIED.clear()

    def test_signature_persisted_and_trusted_in_new_process(self):
        with patch.object(models, "digest", wraps=models.digest) as digest:
            self.assertEqual(local_model(self.model_id, verify=True), self.directory)
            self.assertEqual(digest.call_count, 3)
            self.assertTrue((self.directory / STAT_FILE).is_file())
            self.new_process()
            self.assertEqual(local_model(self.model_id, verify=True), self.directory)
            self.assertEqual(digest.call_count, 3)

    def test_mtime_change_forces_rehash(self):
        local_model(self.model_id, verify=True)
        self.new_process()
        weights = self.directory / "model.safetensors"
        stat = weights.stat()
        os.utime(weights, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        with patch.object(models, "digest", wraps=models.digest) as digest:
            self.assertEqual(local_model(self.model_id, verify=True), self.directory)
            self.assertEqual(digest.call_count, 3)

    def test_same_size_tamper_in_new_process_is_rejected(self):
        local_model(self.model_id, verify=True)
        self.new_process()
        weights = self.directory / "model.safetensors"
        weights.write_bytes(b"WEIGHTS" * 100)
        self.assertIsNone(local_model(self.model_id, verify=True))

    def test_corrupt_stat_file_falls_back_to_hashing(self):
        local_model(self.model_id, verify=True)
        (self.directory / STAT_FILE).write_text("not json")
        self.new_process()
        with patch.object(models, "digest", wraps=models.digest) as digest:
            self.assertEqual(local_model(self.model_id, verify=True), self.directory)
            self.assertEqual(digest.call_count, 3)


if __name__ == "__main__":
    unittest.main()
