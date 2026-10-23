import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_every_subpackage_is_listed(self):
        # The Flatpak installs a wheel; an unlisted subpackage is silently dropped.
        listed = set(tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["packages"])
        found = {".".join(path.parent.relative_to(ROOT).parts)
                 for path in (ROOT / "phimthai").rglob("__init__.py")
                 if "__pycache__" not in path.parts}
        self.assertEqual(found - listed, set())


if __name__ == "__main__":
    unittest.main()
