"""Local model lifecycle using tiny data fixtures; no downloads or inference."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from phimthai import external_models, models
from phimthai.settings import Settings, data_dir


ROOT = Path(__file__).resolve().parents[1]


class ExternalModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-external-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.original_catalog = dict(models.CATALOG)
        self.original_verified = dict(models.VERIFIED)
        self.addCleanup(self.restore_module_state)
        models.VERIFIED.clear()
        models.refresh_catalog()
        self.source = self.make_qwen("downloaded-qwen")

    def restore_module_state(self):
        models.CATALOG.clear()
        models.CATALOG.update(self.original_catalog)
        models.VERIFIED.clear()
        models.VERIFIED.update(self.original_verified)

    def make_qwen(self, name):
        folder = self.root / name
        folder.mkdir()
        self.write_json(folder / "config.json", {"model_type": "qwen3_asr"})
        self.write_json(folder / "tokenizer_config.json", {"tokenizer_class": "Qwen2Tokenizer"})
        self.write_json(folder / "tokenizer.json", {"version": "1.0", "model": {"type": "BPE"}})
        # Import checks file structure/integrity, not ASR. Never load these weights.
        (folder / "model.safetensors").write_bytes(b"tiny synthetic weights; never infer")
        return folder

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def contents(folder):
        return {str(path.relative_to(folder)): path.read_bytes()
                for path in folder.rglob("*") if path.is_file()}

    def assert_no_published_import(self):
        directory = data_dir() / "models"
        self.assertEqual(list(directory.glob("local-*")), [])
        self.assertEqual(list(directory.glob(".import-*")), [])
        self.assertEqual(external_models.load_specs(), {})

    def import_qwen(self):
        identifier = external_models.import_folder(self.source)
        models.refresh_catalog()
        return identifier, models.model_dir(identifier)

    def test_import_copies_data_preserves_source_and_assigns_local_identity(self):
        (self.source / "custom_model.py").write_text("raise RuntimeError('must never execute')")
        self.write_json(self.source / "verified.json", {"revision": "forged-upstream"})
        self.write_json(self.source / "model-spec.json", {"id": "qwen-0.6b", "origin": "upstream"})
        original = self.contents(self.source)
        events = []

        identifier = external_models.import_folder(self.source, events.append)
        models.refresh_catalog()
        destination = models.model_dir(identifier)

        self.assertRegex(identifier, r"^local-[0-9a-f]{32}$")
        self.assertEqual(models.CATALOG[identifier].origin, "local")
        self.assertEqual(models.CATALOG[identifier].backend, "qwen")
        self.assertTrue(models.CATALOG[identifier].revision.startswith("local-"))
        self.assertNotIn(models.CATALOG[identifier].revision,
                         {spec.revision for spec in models.BUILTIN_CATALOG.values()})
        self.assertEqual(self.contents(self.source), original)
        self.assertFalse((destination / "custom_model.py").exists())
        for name in ("config.json", "tokenizer_config.json", "tokenizer.json", "model.safetensors"):
            self.assertEqual((destination / name).read_bytes(), original[name])
            self.assertFalse((destination / name).is_symlink())
            self.assertFalse((destination / name).samefile(self.source / name))
        self.assertEqual(models.local_model(identifier, verify=True), destination)
        self.assertEqual(Settings(model=identifier, device="cpu").validate().model, identifier)
        self.assertEqual(sum(bool(event.get("done")) for event in events), 1)
        self.assertEqual(events[-1]["model_id"], identifier)
        self.assertEqual(events[-1]["completed"], events[-1]["total"])

    def test_registered_identity_is_available_in_a_fresh_worker_process(self):
        identifier, destination = self.import_qwen()
        environment = dict(os.environ, PYTHONPATH=str(ROOT))
        code = """
import json, sys
from phimthai.models import CATALOG, local_model
from phimthai.settings import Settings
identifier = sys.argv[1]
settings = Settings(model=identifier, device='cpu').validate()
print(json.dumps({'id': settings.model, 'origin': CATALOG[identifier].origin,
                  'path': str(local_model(identifier, verify=True))}))
"""
        process = subprocess.run([sys.executable, "-c", code, identifier],
                                 cwd=self.root, env=environment, capture_output=True,
                                 text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), {
            "id": identifier, "origin": "local", "path": str(destination),
        })

    def test_snapshot_symlink_becomes_owned_regular_file(self):
        weights = self.source / "model.safetensors"
        blob = self.root / "hf-blob"
        weights.rename(blob)
        original = blob.read_bytes()
        weights.symlink_to(blob)

        identifier, destination = self.import_qwen()

        self.assertTrue(weights.is_symlink())
        self.assertEqual(blob.read_bytes(), original)
        self.assertFalse((destination / weights.name).is_symlink())
        blob.unlink()
        self.assertEqual((destination / weights.name).read_bytes(), original)
        self.assertEqual(models.local_model(identifier, verify=True), destination)

    def test_imported_hashes_match_copies_and_cached_verification_detects_corruption(self):
        identifier, destination = self.import_qwen()
        manifest = json.loads((destination / "verified.json").read_text())
        for name, entry in manifest["files"].items():
            value = (destination / name).read_bytes()
            self.assertEqual(entry["size"], len(value))
            self.assertEqual(entry["sha256"], hashlib.sha256(value).hexdigest())
        self.assertEqual(models.local_model(identifier, verify=True), destination)
        weights = destination / "model.safetensors"
        before = weights.stat()
        value = weights.read_bytes()
        weights.write_bytes(bytes([value[0] ^ 1]) + value[1:])
        os.utime(weights, ns=(before.st_atime_ns, before.st_mtime_ns))

        self.assertIsNone(models.local_model(identifier, verify=True))
        self.assertEqual((self.source / weights.name).read_bytes(), value)

    def test_unsupported_architecture_does_not_publish_anything(self):
        self.write_json(self.source / "config.json", {"model_type": "arbitrary_custom_model"})
        with self.assertRaises(ValueError):
            external_models.import_folder(self.source)
        self.assert_no_published_import()

    def test_remote_code_mapping_in_config_or_tokenizer_is_rejected(self):
        for filename in ("config.json", "tokenizer_config.json", "tokenizer.json"):
            with self.subTest(filename=filename):
                path = self.source / filename
                original = path.read_bytes()
                document = json.loads(original)
                document["auto_map"] = {"AutoModel": "custom_model.CustomModel"}
                self.write_json(path, document)
                with self.assertRaises(ValueError):
                    external_models.import_folder(self.source)
                path.write_bytes(original)
                self.assert_no_published_import()

    def test_missing_tokenizer_and_pickle_weights_are_rejected(self):
        tokenizer = self.source / "tokenizer.json"
        original = tokenizer.read_bytes()
        tokenizer.unlink()
        with self.assertRaises(ValueError):
            external_models.import_folder(self.source)
        self.assert_no_published_import()
        tokenizer.write_bytes(original)
        (self.source / "pytorch_model.bin").write_bytes(b"untrusted pickle must not load")
        with self.assertRaises(ValueError):
            external_models.import_folder(self.source)
        self.assert_no_published_import()

    def test_shard_traversal_absolute_path_and_missing_shard_are_rejected(self):
        outside = self.root / "outside.safetensors"
        outside.write_bytes(b"outside asset")
        for shard in ("../outside.safetensors", str(outside), "subdir/shard.safetensors", "missing.safetensors"):
            with self.subTest(shard=shard):
                self.write_json(self.source / "model.safetensors.index.json",
                                {"weight_map": {"encoder.weight": shard}})
                with self.assertRaises(ValueError):
                    external_models.import_folder(self.source)
                self.assert_no_published_import()
                self.assertEqual(outside.read_bytes(), b"outside asset")

    def test_failed_copy_preserves_existing_import_and_cleans_staging(self):
        identifier, destination = self.import_qwen()
        before = self.contents(destination)
        source_before = self.contents(self.source)

        def failed_progress(_event):
            raise OSError("simulated interrupted copy after writing a data chunk")

        with self.assertRaises(OSError):
            external_models.import_folder(self.source, failed_progress)

        self.assertEqual(self.contents(destination), before)
        self.assertEqual(self.contents(self.source), source_before)
        self.assertEqual({path.name for path in destination.parent.glob("local-*")}, {identifier})
        self.assertEqual(list(destination.parent.glob(".import-*")), [])
        self.assertEqual(models.local_model(identifier, verify=True), destination)

    def test_removing_import_leaves_original_and_other_models_intact(self):
        identifier, destination = self.import_qwen()
        other_identifier, other_destination = self.import_qwen()
        original = self.contents(self.source)
        other_original = self.contents(other_destination)

        models.remove(identifier)
        models.refresh_catalog()

        self.assertFalse(destination.exists())
        self.assertNotIn(identifier, models.CATALOG)
        self.assertEqual(self.contents(self.source), original)
        self.assertEqual(self.contents(other_destination), other_original)
        self.assertEqual(models.local_model(other_identifier, verify=True), other_destination)
        self.assertIn("qwen-0.6b", models.CATALOG)

    def test_malformed_registration_is_ignored_without_breaking_catalog_reload(self):
        folder = data_dir() / "models" / ("local-" + "a" * 32)
        folder.mkdir(parents=True)
        for value in ([], None, "invalid registration", {"id": folder.name}):
            with self.subTest(value=value):
                self.write_json(folder / "model-spec.json", value)
                models.refresh_catalog()
                self.assertNotIn(folder.name, models.CATALOG)
                self.assertIn("qwen-0.6b", models.CATALOG)


if __name__ == "__main__":
    unittest.main()
