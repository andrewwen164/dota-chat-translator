import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from translator.config import Settings


class SettingsTests(unittest.TestCase):
    def test_backup_before_replacement_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"GEMINI_MODEL": ""}):
            path = Path(d) / "settings.json"
            s = Settings()
            s.save(path)
            original = path.read_bytes()
            s.font_size = 20
            s.save(path)
            self.assertEqual(path.with_suffix(".json.bak").read_bytes(), original)
            self.assertEqual(Settings.load(path).font_size, 20)

    def test_failed_backup_does_not_replace_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            Settings().save(path)
            original = path.read_bytes()
            with patch("translator.config.shutil.copy2", side_effect=PermissionError()):
                with self.assertRaises(PermissionError):
                    Settings(font_size=21).save(path)
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_settings_not_silently_overwritten_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text('{"rpm": 0}')
            with self.assertRaises(ValueError):
                Settings.load(path)
            self.assertEqual(json.loads(path.read_text()), {"rpm": 0})
