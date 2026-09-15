#!/usr/bin/env python3
"""
tests/test_library.py
Tests for app/library.py, app/config.py, and app/job_manager.py data structures.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library import format_size, inspect_game_folder, get_dir_size
from app.config import DEFAULT_SETTINGS


class TestAppModules(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Create a mock game directory
        self.game_dir = self.root / "Half-Life 2"
        self.game_dir.mkdir(parents=True, exist_ok=True)
        (self.game_dir / "hl2.exe").write_bytes(b"HL2_EXE" * 1000)
        (self.game_dir / "steam_api.dll").write_bytes(b"STEAM_API")
        (self.game_dir / "steam_appid.txt").write_text("220\n", encoding="utf-8")

        # Saves
        self.saves = self.game_dir / "saves" / "76561197960287930" / "220"
        self.saves.mkdir(parents=True, exist_ok=True)
        (self.saves / "save1.sav").write_bytes(b"SAV")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_format_size(self):
        self.assertEqual(format_size(500), "500.0 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1024 * 1024 * 5), "5.0 MB")
        self.assertEqual(format_size(1024 * 1024 * 1024 * 2), "2.0 GB")

    def test_inspect_game_folder(self):
        info = inspect_game_folder(self.game_dir)
        self.assertEqual(info["folder_name"], "Half-Life 2")
        self.assertEqual(info["title"], "Half Life 2")
        self.assertEqual(info["app_id"], "220")
        self.assertIn("220/header.jpg", info["banner_url"])
        self.assertTrue(info["has_goldberg"])
        self.assertTrue(info["has_saves"])
        self.assertEqual(info["save_count"], 1)
        self.assertGreater(info["size_bytes"], 0)

    def test_default_settings(self):
        self.assertIn("default_disc_type", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["default_disc_type"], "single")
        self.assertEqual(DEFAULT_SETTINGS["default_player_name"], "VaporPlayer")
        self.assertEqual(DEFAULT_SETTINGS["default_language"], "english")


if __name__ == "__main__":
    unittest.main()

