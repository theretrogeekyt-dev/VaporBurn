#!/usr/bin/env python3
"""
tests/test_library.py
Tests for app/library.py, app/config.py, non-game exclusion (@eaDir),
and Steam manifest metadata extraction.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library import format_size, inspect_game_folder, get_dir_size, scan_input_library
from app.config import DEFAULT_SETTINGS
from scripts.discover_exe import is_valid_game_dir, extract_steam_manifest_info, is_system_or_ignored_dir


class TestAppModules(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # 1. Valid Game Directory with Steam AppID file
        self.game_dir = self.root / "Half-Life 2"
        self.game_dir.mkdir(parents=True, exist_ok=True)
        (self.game_dir / "hl2.exe").write_bytes(b"HL2_EXE" * 1000)
        (self.game_dir / "steam_api.dll").write_bytes(b"STEAM_API")
        (self.game_dir / "steam_appid.txt").write_text("220\n", encoding="utf-8")

        # Saves
        self.saves = self.game_dir / "saves" / "76561197960287930" / "220"
        self.saves.mkdir(parents=True, exist_ok=True)
        (self.saves / "save1.sav").write_bytes(b"SAV")

        # 2. Valid Game with appmanifest_*.acf (VaporFetch standard)
        self.cp_dir = self.root / "Cyberpunk 2077"
        self.cp_dir.mkdir(parents=True, exist_ok=True)
        (self.cp_dir / "Cyberpunk2077.exe").write_bytes(b"CP_EXE" * 1000)
        manifest_content = '''"AppState"
{
    "appid"       "1091500"
    "name"        "Cyberpunk 2077"
    "installdir"  "Cyberpunk 2077"
}
'''
        (self.cp_dir / "appmanifest_1091500.acf").write_text(manifest_content, encoding="utf-8")

        # 3. Non-game directory: Synology DSM @eaDir thumbnail folder
        self.eadir = self.root / "@eaDir"
        self.eadir.mkdir(parents=True, exist_ok=True)
        (self.eadir / "@tmp").write_bytes(b"SYNOLOGY_INDEX")
        (self.eadir / "thumb.jpg").write_bytes(b"THUMB")

        # 4. Non-game directory: NAS recycle bin
        self.recycle = self.root / "#recycle"
        self.recycle.mkdir(parents=True, exist_ok=True)

        # 5. Non-game directory: Empty directory
        self.empty_dir = self.root / "RandomEmptyFolder"
        self.empty_dir.mkdir(parents=True, exist_ok=True)

        # 6. Non-Steam standalone game (no AppID)
        self.drm_free_dir = self.root / "IndieGame"
        self.drm_free_dir.mkdir(parents=True, exist_ok=True)
        (self.drm_free_dir / "Game.exe").write_bytes(b"INDIE_EXE" * 1000)

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

    def test_steam_manifest_parsing(self):
        """Verify that appmanifest_<appid>.acf accurately extracts AppID and official title."""
        info = extract_steam_manifest_info(self.cp_dir)
        self.assertEqual(info["app_id"], "1091500")
        self.assertEqual(info["title"], "Cyberpunk 2077")

        game_data = inspect_game_folder(self.cp_dir)
        self.assertEqual(game_data["app_id"], "1091500")
        self.assertEqual(game_data["title"], "Cyberpunk 2077")
        self.assertIn("1091500/header.jpg", game_data["banner_url"])

    def test_non_game_system_dir_exclusions(self):
        """Verify that @eaDir, #recycle, and empty folders are excluded and not treated as games."""
        self.assertTrue(is_system_or_ignored_dir("@eaDir"))
        self.assertTrue(is_system_or_ignored_dir("#recycle"))
        self.assertTrue(is_system_or_ignored_dir("lost+found"))
        self.assertTrue(is_system_or_ignored_dir("$RECYCLE.BIN"))

        self.assertFalse(is_valid_game_dir(self.eadir))
        self.assertFalse(is_valid_game_dir(self.recycle))
        self.assertFalse(is_valid_game_dir(self.empty_dir))

        # Valid games must pass
        self.assertTrue(is_valid_game_dir(self.game_dir))
        self.assertTrue(is_valid_game_dir(self.cp_dir))
        self.assertTrue(is_valid_game_dir(self.drm_free_dir))

    def test_drm_free_game_no_spacewar_default(self):
        """Verify that games without Steam AppID do NOT default to 480 / Spacewar."""
        info = inspect_game_folder(self.drm_free_dir)
        self.assertEqual(info["app_id"], "")
        self.assertEqual(info["title"], "Indie Game")
        self.assertNotIn("480", info["banner_url"])
        self.assertIn("default_banner.svg", info["banner_url"])

    def test_default_settings(self):
        self.assertIn("default_disc_type", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["default_disc_type"], "single")
        self.assertEqual(DEFAULT_SETTINGS["default_player_name"], "VaporPlayer")
        self.assertEqual(DEFAULT_SETTINGS["default_language"], "english")


if __name__ == "__main__":
    unittest.main()
