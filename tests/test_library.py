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

    def test_candidates_in_game_inspection(self):
        """Verify that inspect_game_folder provides full ranked candidates list."""
        info = inspect_game_folder(self.game_dir)
        self.assertIn("candidates", info)
        self.assertGreater(len(info["candidates"]), 0)
        top = info["candidates"][0]
        self.assertEqual(top["rel_path"], "hl2.exe")
        self.assertTrue(top["is_recommended"])
        self.assertEqual(info["primary_exe"], "hl2.exe")

    def test_multi_exe_heuristic_ranking(self):
        """Verify that a shipping binary beats a small root launcher and config tool."""
        multi_dir = self.root / "UnrealGame"
        multi_dir.mkdir(parents=True, exist_ok=True)
        (multi_dir / "Launcher.exe").write_bytes(b"LAUNCHER" * 500) # small stub
        (multi_dir / "Config.exe").write_bytes(b"CONFIG" * 500)
        
        bin_dir = multi_dir / "Binaries" / "Win64"
        bin_dir.mkdir(parents=True, exist_ok=True)
        shipping_exe = bin_dir / "UnrealGame-Win64-Shipping.exe"
        shipping_exe.write_bytes(b"SHIPPING_EXE" * 500000) # ~6MB

        info = inspect_game_folder(multi_dir)
        self.assertIsNotNone(info["candidates"])
        # Unreal shipping exe must be ranked #1
        self.assertEqual(info["candidates"][0]["name"], "UnrealGame-Win64-Shipping.exe")
        self.assertTrue(info["candidates"][0]["is_recommended"])
        self.assertIn("Unreal Shipping", info["candidates"][0]["tag"])
        self.assertEqual(info["primary_exe"], "Binaries\\Win64\\UnrealGame-Win64-Shipping.exe")

    def test_dependency_dir_exclusions(self):
        """Verify that Steamworks Shared, DirectX, and redist folders are excluded."""
        sw_dir = self.root / "Steamworks Shared"
        sw_dir.mkdir(parents=True, exist_ok=True)
        (sw_dir / "DXSETUP.exe").write_bytes(b"DXSETUP")
        (sw_dir / "steam_appid.txt").write_text("228980\n", encoding="utf-8")

        redist_dir = self.root / "_CommonRedist"
        redist_dir.mkdir(parents=True, exist_ok=True)
        (redist_dir / "vcredist_x64.exe").write_bytes(b"VCREDIST")

        dx_dir = self.root / "DirectX"
        dx_dir.mkdir(parents=True, exist_ok=True)
        (dx_dir / "dxsetup.exe").write_bytes(b"DXSETUP")

        self.assertFalse(is_valid_game_dir(sw_dir))
        self.assertFalse(is_valid_game_dir(redist_dir))
        self.assertFalse(is_valid_game_dir(dx_dir))

    def test_library_deduplication(self):
        """Verify scan_input_library removes duplicate game listings and dependencies."""
        import app.library
        orig_input = app.library.INPUT_DIR
        try:
            app.library.INPUT_DIR = self.root

            # Create duplicates
            dup_hl2 = self.root / "Half-Life 2 [220]"
            dup_hl2.mkdir(parents=True, exist_ok=True)
            (dup_hl2 / "hl2.exe").write_bytes(b"HL2" * 100)
            (dup_hl2 / "steam_appid.txt").write_text("220\n", encoding="utf-8")

            dup_cp = self.root / "Cyberpunk 2077_backup"
            dup_cp.mkdir(parents=True, exist_ok=True)
            (dup_cp / "Cyberpunk2077.exe").write_bytes(b"CP" * 100)
            (dup_cp / "steam_appid.txt").write_text("1091500\n", encoding="utf-8")

            # Dependency folder in input
            dep_dir = self.root / "Steamworks Shared (228980)"
            dep_dir.mkdir(parents=True, exist_ok=True)
            (dep_dir / "DXSETUP.exe").write_bytes(b"DX")
            (dep_dir / "steam_appid.txt").write_text("228980\n", encoding="utf-8")

            games = scan_input_library()
            titles = [g["title"] for g in games]
            app_ids = [g["app_id"] for g in games if g["app_id"]]

            # Verify no duplicates
            self.assertEqual(len(app_ids), len(set(app_ids)))
            self.assertEqual(len(titles), len(set(titles)))

            # Verify Steamworks Shared is not present
            self.assertNotIn("228980", app_ids)
            self.assertFalse(any("steamworks" in t.lower() for t in titles))

            # Verify legitimate games exist
            self.assertIn("Half Life 2", titles)
            self.assertIn("Cyberpunk 2077", titles)
        finally:
            app.library.INPUT_DIR = orig_input


if __name__ == "__main__":
    unittest.main()
