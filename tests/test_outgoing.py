import unittest

from translator.outgoing import ClipboardGuard


class GuardTests(unittest.TestCase):
    def test_requires_dota_foreground_and_explicit_valid_source(self):
        g = ClipboardGuard()
        self.assertIsNone(g.begin("hello", 1, False))
        self.assertIsNone(g.begin("", 1, True))
        self.assertIsNone(g.begin("hello", -1, True))

    def test_clipboard_or_focus_change_blocks_copy(self):
        g = ClipboardGuard()
        context = g.begin("hello", 10, True)
        self.assertFalse(g.can_copy(context, 11, True))
        self.assertFalse(g.can_copy(context, 10, False))
        self.assertTrue(g.can_copy(context, 10, True))

    def test_duplicate_hotkey_and_translated_clipboard_ignored(self):
        g = ClipboardGuard()
        self.assertIsNotNone(g.begin("hello", 1, True))
        self.assertIsNone(g.begin("hello", 1, True))
        g.copied("привет")
        self.assertIsNone(g.begin("привет", 2, True))

    def test_stale_result_does_not_overwrite_clipboard(self):
        now = [0]
        g = ClipboardGuard(clock=lambda: now[0])
        context = g.begin("hello", 10, True)
        now[0] = 91
        self.assertFalse(g.can_copy(context, 10, True))
