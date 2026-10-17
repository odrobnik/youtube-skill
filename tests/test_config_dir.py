"""Offline tests for where youtube.py keeps config and sign-in. Run: python3 -m unittest discover tests"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # keep scripts/ free of __pycache__
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "youtube.py"


def load_script():
    """A separate copy of youtube.py, imported with its config folder in a temporary directory."""
    spec = importlib.util.spec_from_file_location("youtube_config_dir_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"YOUTUBE_SKILL_CONFIG_DIR": tmp}):
        spec.loader.exec_module(module)  # never resolves the real config folder
    return module


class ConfigDirTest(unittest.TestCase):
    youtube = load_script()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.state = Path(tmp.name) / "state"
        self.legacy = self.home / ".openclaw" / "youtube"
        self.moved = self.state / "youtube"

    def config_dir(self, state=True, custom=None):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            for name in ("YOUTUBE_SKILL_CONFIG_DIR", "OPENCLAW_STATE_DIR"):
                os.environ.pop(name, None)
            if state:
                os.environ["OPENCLAW_STATE_DIR"] = str(self.state)
            if custom:
                os.environ["YOUTUBE_SKILL_CONFIG_DIR"] = custom
            return self.youtube._config_dir()

    def put(self, folder, name):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("{}")

    def test_default_folder(self):
        self.assertEqual(self.config_dir(state=False), self.legacy)

    def test_custom_folder_wins(self):
        self.put(self.legacy, "config.json")
        self.assertEqual(self.config_dir(custom=str(self.home / "custom")), self.home / "custom")

    def test_new_setup_uses_the_state_folder(self):
        self.assertEqual(self.config_dir(), self.moved)
        self.legacy.mkdir(parents=True)  # an empty old folder holds nothing to keep
        self.assertEqual(self.config_dir(), self.moved)

    def test_old_folder_stays_in_use_until_its_files_move(self):
        self.put(self.legacy, "tokens.json")
        self.assertEqual(self.config_dir(), self.legacy)
        self.moved.mkdir(parents=True)  # created ahead, still empty
        self.assertEqual(self.config_dir(), self.legacy)
        self.put(self.moved, "config.json")
        self.assertEqual(self.config_dir(), self.moved)


if __name__ == "__main__":
    unittest.main()
