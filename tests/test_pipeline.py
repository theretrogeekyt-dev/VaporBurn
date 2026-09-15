#!/usr/bin/env python3
"""
tests/test_pipeline.py
End-to-end unit and integration test for VaporBurn helper scripts.
Simulates mock game backups, executable discovery, asset sanitization,
checksum manifests, and ISO disc distribution logic.
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.discover_exe import (
    discover_primary_executable,
    find_steam_appid,
    find_redistributables,
    find_save_data,
    find_goldberg_locations,
)
from scripts.sanitize_and_hash import (
    scan_and_sanitize,
    should_exclude,
)
from scripts.iso_packager import (
    plan_discs,
    sanitize_volid,
)


class TestVaporBurnPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.game_root = Path(self.test_dir.name) / "Cyberpunk 2077"
        self.game_root.mkdir(parents=True, exist_ok=True)

        # 1. Create mock game executables
        self.bin_dir = self.game_root / "bin" / "x64"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.shipping_exe = self.bin_dir / "Cyberpunk2077.exe"
        self.shipping_exe.write_bytes(b"MOCK_GAME_BINARY" * 1000000) # ~16MB

        # Generic root launcher
        self.root_launcher = self.game_root / "REDprelauncher.exe"
        self.root_launcher.write_bytes(b"LAUNCHER" * 1000) # small stub

        # Crash handler (should be blacklisted)
        self.crash_exe = self.bin_dir / "CrashReportClient.exe"
        self.crash_exe.write_bytes(b"CRASH" * 1000)

        # 2. Steam API & AppID
        (self.bin_dir / "steam_api64.dll").write_bytes(b"STEAM_API64")
        (self.bin_dir / "steam_appid.txt").write_text("1091500\n", encoding="utf-8")

        # 3. Bloat files (should be stripped by sanitizer)
        (self.bin_dir / "crash_dump.dmp").write_bytes(b"DUMP_DATA")
        (self.bin_dir / "cache.dxvk-cache").write_bytes(b"SHADER_CACHE")
        (self.bin_dir / "game.log").write_text("Crash log\n", encoding="utf-8")
        (self.game_root / "chunk.downloading").write_bytes(b"TEMP_CHUNK")
        (self.game_root / ".DS_Store").write_bytes(b"MAC_JUNK")

        # 4. Redistributables
        self.redist_dir = self.game_root / "_CommonRedist" / "vcredist" / "2019"
        self.redist_dir.mkdir(parents=True, exist_ok=True)
        (self.redist_dir / "vcredist_x64.exe").write_bytes(b"VCREDIST_64")

        self.dx_dir = self.game_root / "_CommonRedist" / "DirectX" / "Jun2010"
        self.dx_dir.mkdir(parents=True, exist_ok=True)
        (self.dx_dir / "DXSETUP.exe").write_bytes(b"DIRECTX_SETUP")

        # 5. Goldberg Save files
        self.saves_dir = self.game_root / "saves" / "76561197960287930" / "1091500"
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        (self.saves_dir / "manualsave_0.dat").write_bytes(b"SAVE_DATA_0")
        (self.saves_dir / "quicksave.dat").write_bytes(b"SAVE_DATA_1")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_executable_discovery(self):
        """Verify smart executable discovery selects real binary over launcher and blacklists."""
        primary = discover_primary_executable(self.game_root, "Cyberpunk 2077")
        self.assertIsNotNone(primary)
        # Should pick bin/x64/Cyberpunk2077.exe, NOT REDprelauncher.exe or CrashReportClient.exe
        self.assertIn("Cyberpunk2077.exe", primary["name"])
        self.assertEqual(primary["rel_dir"], "bin\\x64")

    def test_steam_appid_discovery(self):
        """Verify steam_appid.txt is properly read."""
        app_id = find_steam_appid(self.game_root)
        self.assertEqual(app_id, "1091500")

    def test_redistributables_detection(self):
        """Verify DirectX and VC++ packages are found."""
        redists = find_redistributables(self.game_root)
        redist_ids = [r["id"] for r in redists]
        self.assertIn("directx", redist_ids)
        self.assertIn("vcredist_x64", redist_ids)

    def test_goldberg_and_saves_detection(self):
        """Verify Goldberg DLLs and save directory are discovered."""
        goldberg_info = find_goldberg_locations(self.game_root)
        self.assertTrue(goldberg_info["has_goldberg"])
        self.assertIn("bin/x64", goldberg_info["dll_locations"])

        save_info = find_save_data(self.game_root)
        self.assertTrue(save_info["has_saves"])
        self.assertEqual(save_info["file_count"], 2)

    def test_sanitization_and_exclusion(self):
        """Verify bloat files are stripped and valid files are hashed."""
        self.assertTrue(should_exclude("bin/x64/crash.dmp"))
        self.assertTrue(should_exclude("cache.dxvk-cache"))
        self.assertTrue(should_exclude("logs/game.log"))
        self.assertTrue(should_exclude("chunk.downloading"))
        self.assertTrue(should_exclude(".DS_Store"))

        # Valid files must not be excluded
        self.assertFalse(should_exclude("bin/x64/Cyberpunk2077.exe"))
        self.assertFalse(should_exclude("steam_appid.txt"))
        self.assertFalse(should_exclude("_CommonRedist/DirectX/Jun2010/DXSETUP.exe"))

        stage_dir = Path(self.test_dir.name) / "staging"
        kept, kept_bytes, excluded_bytes = scan_and_sanitize(
            source_dir=self.game_root,
            stage_dir=stage_dir,
            use_hardlinks=True
        )

        kept_rel_paths = [k[0].replace("\\", "/") for k in kept]
        self.assertTrue(any("Cyberpunk2077.exe" in p for p in kept_rel_paths))
        self.assertFalse(any("crash_dump.dmp" in p for p in kept_rel_paths))
        self.assertFalse(any("cache.dxvk-cache" in p for p in kept_rel_paths))
        self.assertFalse(any("chunk.downloading" in p for p in kept_rel_paths))
        self.assertGreater(excluded_bytes, 0)
        self.assertGreater(kept_bytes, 0)

    def test_disc_planning(self):
        """Verify disc layout for single and multi-disc configurations."""
        vol_single = sanitize_volid("Cyberpunk 2077: Phantom Liberty", 1, 1)
        self.assertTrue(len(vol_single) <= 32)
        self.assertIn("CYBERPUNK", vol_single)

        vol_disc2 = sanitize_volid("Cyberpunk 2077", 2, 3)
        self.assertTrue(vol_disc2.endswith("_D2"))

        # Test multi-disc distribution
        mock_stage = Path(self.test_dir.name) / "mock_installer"
        mock_stage.mkdir(parents=True, exist_ok=True)
        setup_exe = mock_stage / "setup.exe"
        setup_exe.write_bytes(b"SETUP" * 1000)

        bins = []
        for i in range(1, 5):
            bin_f = mock_stage / f"setup-{i}.bin"
            # 50MB each
            bin_f.write_bytes(b"BIN" * (50 * 1024 * 1024 // 3))
            bins.append(bin_f)

        all_installer_files = [setup_exe] + bins
        temp_disc_root = Path(self.test_dir.name) / "disc_staging"

        # Plan with 120MB per disc limit -> should split across 2 discs
        discs = plan_discs(all_installer_files, disc_size_mb=120, temp_disc_root=temp_disc_root)
        self.assertEqual(len(discs), 2)
        self.assertEqual(discs[0]["disc_number"], 1)
        self.assertEqual(discs[1]["disc_number"], 2)


if __name__ == "__main__":
    unittest.main()

