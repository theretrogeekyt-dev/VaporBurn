#!/usr/bin/env python3
"""
scripts/discover_exe.py
Smart discovery of primary game executable, Steam App ID, game title,
Goldberg emulator settings locations, save data, and redistributables.
Part of the VaporBurn package.
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

# Executable filename patterns to ignore completely (case-insensitive)
BLACKLIST_PATTERNS = [
    r"^crashreportclient.*\.exe$",
    r"^unitycrashhandler.*\.exe$",
    r"^crashpad_handler.*\.exe$",
    r"^werfault.*\.exe$",
    r"^dxsetup\.exe$",
    r"^vcredist.*\.exe$",
    r"^vc_redist.*\.exe$",
    r"^oalinst\.exe$",
    r"^dotnet.*\.exe$",
    r"^netfx.*\.exe$",
    r"^ue[0-9]*prereqsetup.*\.exe$",
    r"^unins[0-9]*\.exe$",
    r"^uninstall.*\.exe$",
    r"^setup.*\.exe$",
    r"^install.*\.exe$",
    r"^updater.*\.exe$",
    r"^patcher.*\.exe$",
    r"^dedicatedserver.*\.exe$",
    r"^.*server\.exe$",
    r"^editor.*\.exe$",
    r"^benchmark.*\.exe$",
    r"^7z.*\.exe$",
    r"^quickvfv\.exe$",
]

COMPILED_BLACKLIST = [re.compile(pat, re.IGNORECASE) for pat in BLACKLIST_PATTERNS]


def is_blacklisted(filename: str) -> bool:
    for pattern in COMPILED_BLACKLIST:
        if pattern.search(filename):
            return True
    return False


def normalize_title(raw_name: str) -> str:
    """Cleans directory name into a human-friendly game title."""
    cleaned = re.sub(r"[_\-\.]+", " ", raw_name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else raw_name


def find_steam_appid(game_root: Path) -> Optional[str]:
    """Scans for steam_appid.txt or appid.txt in common locations."""
    candidates = list(game_root.rglob("steam_appid.txt")) + list(game_root.rglob("appid.txt"))
    for cand in candidates:
        try:
            content = cand.read_text(encoding="utf-8", errors="ignore").strip()
            match = re.search(r"^\d+", content)
            if match:
                return match.group(0)
        except Exception:
            continue
    return None


def find_goldberg_locations(game_root: Path) -> Dict[str, Any]:
    """Finds all steam_api.dll / steam_api64.dll instances and check for Goldberg."""
    dll_locations = []
    steam_api_files = list(game_root.rglob("steam_api*.dll"))
    
    for dll in steam_api_files:
        rel_dir = dll.parent.relative_to(game_root)
        rel_dir_str = str(rel_dir).replace("\\", "/")
        if rel_dir_str == ".":
            rel_dir_str = ""
        if rel_dir_str not in dll_locations:
            dll_locations.append(rel_dir_str)

    # Check for existing steam_settings directory
    has_steam_settings = any(game_root.rglob("steam_settings"))
    
    return {
        "dll_locations": dll_locations,
        "has_goldberg": len(dll_locations) > 0 or has_steam_settings,
    }


def find_save_data(game_root: Path) -> Dict[str, Any]:
    """Looks for existing Goldberg save data in backup folder."""
    save_patterns = [
        "saves",
        "save",
        "Goldberg SteamEmu Saves",
        "Goldberg Saves",
        "AppData/Roaming/Goldberg SteamEmu Saves",
    ]
    
    for pattern in save_patterns:
        target = game_root / pattern
        if target.exists() and target.is_dir():
            rel_path = str(target.relative_to(game_root)).replace("\\", "/")
            # Count files in save directory
            save_files = [f for f in target.rglob("*") if f.is_file()]
            if save_files:
                return {
                    "has_saves": True,
                    "save_dir_rel": rel_path,
                    "file_count": len(save_files),
                }
    return {
        "has_saves": False,
        "save_dir_rel": "",
        "file_count": 0,
    }


def find_redistributables(game_root: Path) -> List[Dict[str, str]]:
    """Detects standard redistributable installers."""
    redists = []
    redist_dirs = ["_CommonRedist", "Redistributables", "redist", "Redist", "Prerequisites", "installers"]
    
    found_dirs = []
    for d in redist_dirs:
        target = game_root / d
        if target.exists() and target.is_dir():
            found_dirs.append(target)
            
    # Also search entire tree if not found in top dirs
    search_dirs = found_dirs if found_dirs else [game_root]
    
    # 1. DirectX
    dx_setups = []
    for sdir in search_dirs:
        dx_setups.extend(list(sdir.rglob("DXSETUP.exe")) + list(sdir.rglob("dxsetup.exe")))
    if dx_setups:
        best_dx = dx_setups[0]
        rel_path = str(best_dx.relative_to(game_root)).replace("/", "\\")
        redists.append({
            "id": "directx",
            "name": "DirectX End-User Runtimes (June 2010)",
            "exe_rel": rel_path,
            "params": "/silent",
            "description": "Installs legacy DirectX 9.0c / 10 / 11 runtimes",
            "default_checked": True
        })
        
    # 2. Visual C++ (x64 and x86)
    vc_files = []
    for sdir in search_dirs:
        for f in sdir.rglob("*.exe"):
            f_lower = f.name.lower()
            if "vcredist" in f_lower or "vc_redist" in f_lower:
                vc_files.append(f)
                
    seen_archs = set()
    for vc in vc_files:
        v_name = vc.name.lower()
        rel_path = str(vc.relative_to(game_root)).replace("/", "\\")
        if "x64" in v_name and "x64" not in seen_archs:
            seen_archs.add("x64")
            redists.append({
                "id": "vcredist_x64",
                "name": f"Visual C++ Redistributable (x64) - {vc.name}",
                "exe_rel": rel_path,
                "params": "/install /passive /norestart",
                "description": "Microsoft Visual C++ 64-bit runtime",
                "default_checked": True
            })
        elif ("x86" in v_name or "32" in v_name) and "x86" not in seen_archs:
            seen_archs.add("x86")
            redists.append({
                "id": "vcredist_x86",
                "name": f"Visual C++ Redistributable (x86) - {vc.name}",
                "exe_rel": rel_path,
                "params": "/install /passive /norestart",
                "description": "Microsoft Visual C++ 32-bit runtime",
                "default_checked": True
            })

    # 3. OpenAL
    oal_files = []
    for sdir in search_dirs:
        oal_files.extend(list(sdir.rglob("oalinst.exe")))
    if oal_files:
        best_oal = oal_files[0]
        rel_path = str(best_oal.relative_to(game_root)).replace("/", "\\")
        redists.append({
            "id": "openal",
            "name": "OpenAL Audio Installer",
            "exe_rel": rel_path,
            "params": "/s",
            "description": "OpenAL 3D sound driver",
            "default_checked": False
        })
        
    return redists


def discover_primary_executable(game_root: Path, game_folder_name: str) -> Optional[Dict[str, Any]]:
    """Heuristic scoring to discover the primary game executable."""
    all_exes = [f for f in game_root.rglob("*.exe") if f.is_file()]
    if not all_exes:
        return None

    scores = {}
    normalized_game_name = re.sub(r"[^a-zA-Z0-9]", "", game_folder_name).lower()

    for exe in all_exes:
        if is_blacklisted(exe.name):
            continue

        score = 0
        exe_lower = exe.name.lower()
        parent_lower = str(exe.parent.relative_to(game_root)).lower()
        size_mb = exe.stat().st_size / (1024 * 1024)

        # 1. Unreal Engine Shipping Binary (+150)
        if "-win64-shipping.exe" in exe_lower or "-shipping.exe" in exe_lower:
            score += 150
        elif "-win32-shipping.exe" in exe_lower:
            score += 130
        elif "-win64.exe" in exe_lower:
            score += 110

        # 2. Co-location with steam_api.dll / steam_api64.dll (+90)
        if (exe.parent / "steam_api64.dll").exists() or (exe.parent / "steam_api.dll").exists():
            score += 90

        # 3. Path structure heuristic (+50 for Binaries/Win64, bin/x64)
        if "binaries/win64" in parent_lower or "binaries\\win64" in parent_lower:
            score += 60
        elif "bin/x64" in parent_lower or "bin\\x64" in parent_lower or "bin64" in parent_lower:
            score += 45
        elif parent_lower == ".":
            score += 30

        # 4. Name match with game folder name (+40)
        clean_exe_stem = re.sub(r"[^a-zA-Z0-9]", "", exe.stem).lower()
        if normalized_game_name and (clean_exe_stem in normalized_game_name or normalized_game_name in clean_exe_stem):
            score += 50

        # 5. File size weight (actual game executables are usually > 10MB)
        # Launcher stubs are typically 100KB - 3MB
        if size_mb > 10:
            score += min(int(size_mb), 40)
        elif size_mb < 2:
            score -= 10

        # 6. Generic launcher penalty if other executables exist
        if exe_lower in ["launcher.exe", "gamelauncher.exe", "start.exe"]:
            score -= 20

        scores[exe] = (score, size_mb)

    if not scores:
        # If all were blacklisted, pick the largest non-crashhandler exe
        fallback = [f for f in all_exes if "crash" not in f.name.lower() and "unins" not in f.name.lower()]
        if fallback:
            best_exe = max(fallback, key=lambda f: f.stat().st_size)
        else:
            best_exe = all_exes[0]
        score, size_mb = 0, best_exe.stat().st_size / (1024 * 1024)
    else:
        best_exe = max(scores.keys(), key=lambda k: scores[k][0])
        score, size_mb = scores[best_exe]

    rel_exe = str(best_exe.relative_to(game_root)).replace("/", "\\")
    rel_dir = str(best_exe.parent.relative_to(game_root)).replace("/", "\\")
    if rel_dir == ".":
        rel_dir = ""

    return {
        "rel_path": rel_exe,
        "name": best_exe.name,
        "rel_dir": rel_dir,
        "size_mb": round(size_mb, 2),
        "score": score,
    }


def main():
    parser = argparse.ArgumentParser(description="VaporBurn Smart Discovery")
    parser.add_argument("--game-dir", required=True, help="Path to input game directory")
    parser.add_argument("--output-json", help="Path to write discovery results JSON")
    parser.add_argument("--game-title", help="Explicit game title override")
    parser.add_argument("--app-id", help="Explicit Steam App ID override")
    parser.add_argument("--main-exe", help="Explicit main executable relative path override")

    args = parser.parse_args()
    game_root = Path(args.game_dir).resolve()

    if not game_root.exists() or not game_root.is_dir():
        print(f"Error: Game directory does not exist: {game_root}", file=sys.stderr)
        sys.exit(1)

    folder_name = game_root.name
    game_title = args.game_title or normalize_title(folder_name)
    app_id = args.app_id or find_steam_appid(game_root) or "480"

    print(f"[Discovery] Analyzing game directory: {game_root}")
    print(f"[Discovery] Detected Game Title: {game_title}")
    print(f"[Discovery] Detected Steam App ID: {app_id}")

    # Primary executable
    if args.main_exe:
        custom_exe = (game_root / args.main_exe).resolve()
        if custom_exe.exists():
            rel_exe = str(custom_exe.relative_to(game_root)).replace("/", "\\")
            rel_dir = str(custom_exe.parent.relative_to(game_root)).replace("/", "\\")
            primary_exe = {
                "rel_path": rel_exe,
                "name": custom_exe.name,
                "rel_dir": "" if rel_dir == "." else rel_dir,
                "size_mb": round(custom_exe.stat().st_size / (1024 * 1024), 2),
                "score": 9999,
            }
        else:
            print(f"Warning: Specified --main-exe '{args.main_exe}' not found! Falling back to auto-discovery.", file=sys.stderr)
            primary_exe = discover_primary_executable(game_root, folder_name)
    else:
        primary_exe = discover_primary_executable(game_root, folder_name)

    if primary_exe:
        print(f"[Discovery] Primary Executable: {primary_exe['rel_path']} ({primary_exe['size_mb']} MB, score={primary_exe['score']})")
    else:
        print("[Discovery] Warning: No suitable executable found in game directory!")

    # Goldberg analysis
    goldberg_info = find_goldberg_locations(game_root)
    print(f"[Discovery] Goldberg DLL locations: {goldberg_info['dll_locations']}")

    # Save data
    save_info = find_save_data(game_root)
    if save_info["has_saves"]:
        print(f"[Discovery] Detected existing saves in: {save_info['save_dir_rel']} ({save_info['file_count']} files)")
    else:
        print("[Discovery] No included save data detected in backup.")

    # Redistributables
    redists = find_redistributables(game_root)
    print(f"[Discovery] Detected {len(redists)} redistributable package(s): {[r['name'] for r in redists]}")

    results = {
        "game_title": game_title,
        "folder_name": folder_name,
        "app_id": app_id,
        "primary_exe": primary_exe,
        "goldberg": goldberg_info,
        "saves": save_info,
        "redistributables": redists,
    }

    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"[Discovery] Wrote discovery metadata to {out_path}")

    # Also output key=value to stdout for shell sourcing if needed
    print(f"DISCOVERED_TITLE={game_title}")
    print(f"DISCOVERED_APP_ID={app_id}")
    if primary_exe:
        print(f"DISCOVERED_EXE_REL={primary_exe['rel_path']}")
        print(f"DISCOVERED_EXE_NAME={primary_exe['name']}")
        print(f"DISCOVERED_EXE_DIR={primary_exe['rel_dir']}")


if __name__ == "__main__":
    main()
