"""Unfocused Wayland clipboard offers fall back to wl-clipboard, never clobbering user copies."""
import subprocess
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from phimthai import clipboard
from phimthai.clipboard import ClipboardTransaction, UTF8

APP = QApplication.instance() or QApplication([])


class FakeWayland:
    """Records wl-copy calls and serves wl-paste from an in-memory selection."""

    def __init__(self, selection=None, sensitive=True, programs=("wl-copy", "wl-paste")):
        self.selection = dict(selection or {})
        self.sensitive = sensitive
        self.programs = programs
        self.copies = []

    def which(self, name):
        return "/usr/bin/" + name if name in self.programs else None

    def run(self, args, input=None, **_options):
        self.copies.append(args)
        if "--sensitive" in args and not self.sensitive:
            raise subprocess.CalledProcessError(1, args)
        if "--clear" in args:
            self.selection = {}
        else:
            name = args[args.index("--type") + 1]
            self.selection = {name: input, **({"text/plain": input} if name == UTF8 else {})}
        return subprocess.CompletedProcess(args, 0)

    def read(self, args, limit=clipboard.SNAPSHOT_LIMIT, timeout=None):
        if "--list-types" in args:
            return "\n".join(self.selection).encode() if self.selection else None
        data = self.selection.get(args[args.index("--type") + 1])
        return None if data is None or len(data) > limit else data


class UnfocusedWaylandTests(unittest.TestCase):
    def setUp(self):
        APP.clipboard().clear()
        self.fake = FakeWayland({UTF8: "ก่อนหน้า".encode()})
        for target, value in (("is_wayland", lambda: True), ("_read", self.fake.read)):
            patcher = patch.object(clipboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module, target, value in ((clipboard.shutil, "which", self.fake.which),
                                      (clipboard.subprocess, "run", self.fake.run)):
            patcher = patch.object(module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertIsNone(APP.focusWindow())

    def test_offer_uses_sensitive_wl_copy_and_restores_previous(self):
        transaction = ClipboardTransaction()
        self.assertTrue(transaction.offer("สวัสดี hello"))
        self.assertEqual(transaction.mode, "wl-copy")
        self.assertEqual(self.fake.copies[0], ["/usr/bin/wl-copy", "--type", UTF8, "--sensitive"])
        self.assertEqual(self.fake.selection[UTF8], "สวัสดี hello".encode())
        self.assertTrue(transaction.owns_clipboard())
        transaction.restore()
        self.assertEqual(self.fake.selection[UTF8], "ก่อนหน้า".encode())
        self.assertFalse(transaction.owns_clipboard())

    def test_user_copy_during_offer_is_never_overwritten(self):
        transaction = ClipboardTransaction()
        transaction.offer("transcript")
        self.fake.selection = {UTF8: b"new user copy"}
        self.assertFalse(transaction.owns_clipboard())
        restored = []
        transaction.restored.connect(lambda: restored.append(True))
        transaction.restore()
        self.assertEqual(self.fake.selection, {UTF8: b"new user copy"})
        self.assertEqual(restored, [True])

    def test_empty_previous_clipboard_is_cleared_on_restore(self):
        self.fake.selection = {}
        transaction = ClipboardTransaction()
        self.assertTrue(transaction.offer("transcript"))
        transaction.restore()
        self.assertEqual(self.fake.copies[-1], ["/usr/bin/wl-copy", "--clear"])
        self.assertEqual(self.fake.selection, {})

    def test_non_text_previous_selection_is_restored_with_its_type(self):
        self.fake.selection = {"image/png": b"\x89PNG", "application/x-kde-onlyReplaceEmpty": b"1"}
        transaction = ClipboardTransaction()
        transaction.offer("transcript")
        transaction.restore()
        self.assertEqual(self.fake.copies[-1], ["/usr/bin/wl-copy", "--type", "image/png"])
        self.assertEqual(self.fake.selection, {"image/png": b"\x89PNG"})

    def test_old_wl_copy_without_sensitive_option_still_offers(self):
        self.fake.sensitive = False
        transaction = ClipboardTransaction()
        self.assertTrue(transaction.offer("transcript"))
        self.assertEqual(self.fake.copies[-1], ["/usr/bin/wl-copy", "--type", UTF8])
        self.assertTrue(transaction.owns_clipboard())

    def test_missing_wl_copy_reports_failure_for_manual_paste(self):
        self.fake.programs = ("wl-paste",)
        transaction = ClipboardTransaction()
        self.assertFalse(transaction.offer("transcript"))
        self.assertEqual(transaction.mode, "failed")
        self.assertFalse(transaction.owns_clipboard())
        self.assertEqual(self.fake.selection[UTF8], "ก่อนหน้า".encode())
        transaction.restore()
        self.assertEqual(self.fake.copies, [])

    def test_qt_owned_selection_is_never_read_through_wl_paste(self):
        APP.clipboard().setText("own copy")
        with patch.object(type(APP.clipboard()), "ownsClipboard", return_value=True), \
             patch.object(clipboard, "_read", side_effect=AssertionError("would deadlock")):
            transaction = ClipboardTransaction()
            transaction.offer("transcript")
            self.assertFalse(transaction.owns_clipboard())
        self.assertEqual(transaction.previous.text(), "own copy")


class QtPathTests(unittest.TestCase):
    def tearDown(self):
        APP.clipboard().clear()

    def test_non_wayland_offer_stays_in_qt_with_all_formats(self):
        data = QMimeData()
        data.setText("original")
        data.setData("application/test-binary", b"\x00\xff")
        APP.clipboard().setMimeData(data)
        with patch.object(clipboard.subprocess, "run", side_effect=AssertionError("no wl-copy")):
            transaction = ClipboardTransaction()
            self.assertTrue(transaction.offer("transcript"))
            self.assertEqual(transaction.mode, "qt")
            self.assertTrue(transaction.owns_clipboard())
            transaction.restore()
        self.assertEqual(bytes(APP.clipboard().mimeData().data("application/test-binary")), b"\x00\xff")


class BoundedReadTests(unittest.TestCase):
    def test_oversized_failed_or_slow_output_is_rejected(self):
        self.assertEqual(clipboard._read([sys.executable, "-c", "print('ok', end='')"]), b"ok")
        self.assertIsNone(clipboard._read([sys.executable, "-c", "print('x' * 100)"], limit=10))
        self.assertIsNone(clipboard._read([sys.executable, "-c", "raise SystemExit(1)"]))
        self.assertIsNone(clipboard._read([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2))
        self.assertIsNone(clipboard._read(["/nonexistent/wl-paste"]))


if __name__ == "__main__":
    unittest.main()
