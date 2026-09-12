"""Native installer boundaries; all destinations and executables are test-owned."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("phimthai_installer", ROOT / "scripts/install-app.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)
NAMES = ("space here", "dollar$HOME $(nothing)", "single' double\" tick`",
         "back\\slash", "percent%F%U", "all space'\"$`\\%F")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-installer-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        environment = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}
        for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            directory = self.base / key
            directory.mkdir(mode=0o700)
            environment[key] = str(directory)
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def launcher_fixture(self, name):
        home = self.base / name
        home.mkdir()
        capture = home / "arguments.jsonl"
        payload = home / "capture.py"
        payload.write_text("import json,sys\nfrom pathlib import Path\n"
                           f"with Path({str(capture)!r}).open('a') as handle:\n"
                           "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n")
        python = home / "python fixture"
        python.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " "
                          + shlex.quote(str(payload)) + ' "$@"\n')
        python.chmod(0o755)
        launcher, desktop = INSTALLER.install_launchers(python, home / "data")
        return launcher, desktop, capture

    def test_launcher_preserves_interpreter_identity_and_literal_arguments(self):
        arguments = ["a b", "q'u", "$(false)", "%F", 'double"quote', "back\\slash"]
        for name in NAMES:
            with self.subTest(path=name):
                launcher, _, capture = self.launcher_fixture(name)
                subprocess.run([str(launcher), *arguments], check=True, timeout=10)
                self.assertEqual(json.loads(capture.read_text()), ["-m", "phimthai", *arguments])

    def test_icon_upgrade_installs_png_and_retires_only_the_owned_svg(self):
        data = self.base / "icon upgrade"
        legacy = data / "icons/hicolor/scalable/apps" / (INSTALLER.APP_ID + ".svg")
        legacy.parent.mkdir(parents=True)
        legacy.write_text("old application icon")
        unrelated = legacy.with_name("another.application.svg")
        unrelated.write_text("keep unrelated icon")

        INSTALLER.install_launchers(Path(sys.executable), data)

        icon = data / "icons/hicolor/512x512/apps" / (INSTALLER.APP_ID + ".png")
        source = ROOT / "phimthai/assets" / icon.name
        self.assertEqual(icon.read_bytes(), source.read_bytes())
        self.assertFalse(legacy.exists())
        self.assertEqual(unrelated.read_text(), "keep unrelated icon")
        # Reinstalling must also succeed once the legacy file is gone.
        INSTALLER.install_launchers(Path(sys.executable), data)
        self.assertTrue(icon.is_file())

    def test_failed_png_install_preserves_the_legacy_icon(self):
        data = self.base / "failed icon upgrade"
        legacy = data / "icons/hicolor/scalable/apps" / (INSTALLER.APP_ID + ".svg")
        legacy.parent.mkdir(parents=True)
        legacy.write_text("keep until replacement succeeds")
        with mock.patch.object(INSTALLER.shutil, "copyfile", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                INSTALLER.install_launchers(Path(sys.executable), data)
        self.assertEqual(legacy.read_text(), "keep until replacement succeeds")

    def test_desktop_main_and_record_actions_preserve_special_paths(self):
        gi_python = None
        for candidate in dict.fromkeys((sys.executable, "/usr/bin/python3")):
            if Path(candidate).exists() and subprocess.run(
                [candidate, "-c", "from gi.repository import Gio"],
                capture_output=True, timeout=10,
            ).returncode == 0:
                gi_python = candidate
                break
        if gi_python is None:
            self.skipTest("Gio Python bindings are needed for actual desktop-entry launch validation")
        fixtures = []
        for name in NAMES:
            _, desktop, capture = self.launcher_fixture(name)
            if shutil.which("desktop-file-validate"):
                result = subprocess.run(["desktop-file-validate", str(desktop)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            fixtures.append((str(desktop), str(capture)))
        probe = """
import json,pathlib,sys,time
from gi.repository import Gio
for desktop,capture in json.loads(sys.argv[1]):
    app = Gio.DesktopAppInfo.new_from_filename(desktop)
    assert app is not None, desktop
    app.launch([], None)
    app.launch_action('Record', None)
    path = pathlib.Path(capture)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if path.exists() and len(path.read_text().splitlines()) >= 2:
            break
        time.sleep(.02)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert sorted(rows) == [['-m','phimthai'],['-m','phimthai','--toggle']], (desktop,rows)
"""
        result = subprocess.run([gi_python, "-c", probe, json.dumps(fixtures)],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_venv_aliases_are_rejected_before_mutation(self):
        project = self.base / "project"
        legacy = project / ".venv"
        legacy.mkdir(parents=True)
        (legacy / "pyvenv.cfg").write_text("test fixture\n")
        (project / "docs").mkdir()
        alias = self.base / "legacy alias"
        alias.symlink_to(legacy, target_is_directory=True)
        for destination in (legacy, project / "docs/../.venv", alias):
            with self.subTest(destination=str(destination)), \
                 mock.patch.object(INSTALLER, "ROOT", project), \
                 mock.patch.object(INSTALLER, "find_python", return_value=sys.executable), \
                 mock.patch.object(INSTALLER.shutil, "which", return_value="/usr/bin/true"), \
                 mock.patch.object(INSTALLER, "run") as run, \
                 mock.patch.object(sys, "argv", ["install-app.py", "--venv", str(destination)]), \
                 contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as stopped:
                    INSTALLER.main()
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("reserved for the legacy workflow", errors.getvalue())
                run.assert_not_called()

    def test_existing_nonvenv_is_rejected_before_mutation(self):
        destination = self.base / "documents"
        destination.mkdir()
        with mock.patch.object(INSTALLER, "find_python", return_value=sys.executable), \
             mock.patch.object(INSTALLER.shutil, "which", return_value="/usr/bin/true"), \
             mock.patch.object(INSTALLER, "run") as run, \
             mock.patch.object(sys, "argv", ["install-app.py", "--venv", str(destination)]), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as stopped:
                INSTALLER.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("not a virtual environment", errors.getvalue())
            run.assert_not_called()

    def test_help_and_missing_python_need_no_installation(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install-app.py"), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-launcher", result.stdout)
        with self.assertRaisesRegex(RuntimeError, "Python 3.11"):
            INSTALLER.find_python(str(self.base / "missing-python"))

    def test_cpu_selection_replaces_same_version_cuda_without_network(self):
        """Exercise pip's actual candidate selection, using tiny metadata-only fixtures."""
        destination = self.base / "venv"
        destination.mkdir()
        (destination / "pyvenv.cfg").write_text("test fixture\n")
        command = []

        class StopBeforeInstall(Exception):
            pass

        def capture_command(arguments, **kwargs):
            command.extend(str(item) for item in arguments)
            raise StopBeforeInstall()

        with mock.patch.object(INSTALLER, "find_python", return_value=sys.executable), \
             mock.patch.object(INSTALLER.shutil, "which", return_value="/usr/bin/true"), \
             mock.patch.object(INSTALLER, "run", side_effect=capture_command), \
             mock.patch.object(sys, "argv", ["install-app.py", "--venv", str(destination), "--no-launcher"]):
            with self.assertRaises(StopBeforeInstall):
                INSTALLER.main()
        pin = next(argument for argument in command if argument.startswith("torch=="))
        version = pin.split("==")[1].split("+")[0]
        existing = self.base / f"torch-{version}+cu128.dist-info"
        existing.mkdir()
        (existing / "METADATA").write_text(f"Metadata-Version: 2.1\nName: torch\nVersion: {version}+cu128\n")
        wheels = self.base / "wheels"
        wheels.mkdir()
        with zipfile.ZipFile(wheels / f"torch-{version}+cpu-py3-none-any.whl", "w") as wheel:
            prefix = f"torch-{version}+cpu.dist-info/"
            wheel.writestr(prefix + "METADATA", f"Metadata-Version: 2.1\nName: torch\nVersion: {version}+cpu\n")
            wheel.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            wheel.writestr(prefix + "RECORD", "")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--no-index",
                                 "--no-deps", "--find-links", str(wheels), "--upgrade", pin],
                                env=dict(os.environ, PYTHONPATH=str(self.base), PIP_DISABLE_PIP_VERSION_CHECK="1"),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Would install torch-{version}+cpu", result.stdout)


if __name__ == "__main__":
    unittest.main()
