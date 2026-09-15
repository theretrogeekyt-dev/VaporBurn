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
    r"^unrealcefsubprocess.*\.exe$",
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
    r"^easyanticheat.*\.exe$",
    r"^eac_server.*\.exe$",
    r"^battleye.*\.exe$",
    r"^bootstrapper?.*\.exe$",
    r"^webhelper.*\.exe$",
]

COMPILED_BLACKLIST = [re.compile(pat, re.IGNORECASE) for pat in BLACKLIST_PATTERNS]


def is_blacklisted(filename: str) -> bool:
    for pattern in COMPILED_BLACKLIST:
        if pattern.search(filename):
            return True
    return False


def normalize_title(raw_name: str) -> str:
    """Cleans directory name into a human-friendly game title, splitting PascalCase."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_name)
    spaced = re.sub(r"([a-zA-Z])([0-9])", r"\1 \2", spaced)
    cleaned = re.sub(r"[_\-\.]+", " ", spaced)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else raw_name


SYSTEM_DIR_BLACKLIST = {
    "@eadir", "@tmp", "@sharebin", "#recycle", "#snapshot", "lost+found",
    "system volume information", "$recycle.bin", "recycler", "appdata",
    "saves", "goldberg saves", "redistributables", "_commonredist", "redist",
    "prerequisites", "steamapps", "depotcache", "downloading", "temp", "tmp"
}


def is_system_or_ignored_dir(name: str) -> bool:
    """Returns True if the directory name matches NAS or OS system folder patterns."""
    lower = name.lower().strip()
    if lower.startswith(("@", ".", "#", "$", "~")):
        return True
    return lower in SYSTEM_DIR_BLACKLIST


def extract_steam_manifest_info(game_root: Path) -> Dict[str, Optional[str]]:
    """
    Extracts official Steam AppID and title from Steam appmanifest_*.acf,
    steam_appid.txt, or folder name annotations.
    """
    # 1. Search for Steam appmanifest_*.acf (VaporFetch keeps these in game root)
    manifest_candidates = list(game_root.glob("appmanifest_*.acf")) + list(game_root.rglob("appmanifest_*.acf"))
    for manifest in manifest_candidates:
        try:
            fn_match = re.search(r"appmanifest_(\d+)\.acf", manifest.name, re.IGNORECASE)
            fn_appid = fn_match.group(1) if fn_match else None

            content = manifest.read_text(encoding="utf-8", errors="ignore")
            appid_match = re.search(r'"appid"\s+"(\d+)"', content, re.IGNORECASE)
            name_match = re.search(r'"name"\s+"([^"]+)"', content, re.IGNORECASE)

            appid = appid_match.group(1) if appid_match else fn_appid
            title = name_match.group(1) if name_match else None

            if appid:
                return {"app_id": appid, "title": title}
        except Exception:
            continue

    # 2. Search for steam_appid.txt or appid.txt
    txt_candidates = (
        list(game_root.glob("steam_appid.txt"))
        + list(game_root.glob("appid.txt"))
        + list(game_root.rglob("steam_appid.txt"))
        + list(game_root.rglob("appid.txt"))
    )
    for cand in txt_candidates:
        try:
            content = cand.read_text(encoding="utf-8", errors="ignore").strip()
            match = re.search(r"^\d+", content)
            if match:
                return {"app_id": match.group(0), "title": None}
        except Exception:
            continue

    # 3. Check for bracketed AppID in folder name: e.g. "Cyberpunk 2077 [1091500]"
    folder_match = re.search(r"[\[\(](\d{3,8})[\]\)]", game_root.name)
    if folder_match:
        clean_title = re.sub(r"[\[\(]\d{3,8}[\]\)]", "", game_root.name).strip()
        return {"app_id": folder_match.group(1), "title": normalize_title(clean_title)}

    return {"app_id": None, "title": None}


def find_steam_appid(game_root: Path) -> Optional[str]:
    """Returns detected Steam AppID, or None if unidentified (does NOT default to 480)."""
    return extract_steam_manifest_info(game_root).get("app_id")


def is_valid_game_dir(game_root: Path) -> bool:
    """
    Determines if a directory contains a valid game installation.
    Excludes NAS thumbnail folders like @eaDir, recycle bins, and empty folders.
    """
    if is_system_or_ignored_dir(game_root.name):
        return False

    if not game_root.is_dir():
        return False

    # Check for steam manifest or appid
    if extract_steam_manifest_info(game_root).get("app_id"):
        return True

    # Check for steam dlls
    if list(game_root.glob("steam_api*.dll")) or list(game_root.rglob("steam_api*.dll")):
        return True

    # Check for any valid executable that is not in the blacklist
    for exe in game_root.rglob("*.exe"):
        if not is_blacklisted(exe.name):
            return True

    return False


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


def inspect_pe_file(exe_path: Path) -> Dict[str, Any]:
    """Inspects a Windows PE executable header safely without third-party dependencies."""
    res = {
        "is_pe": False,
        "is_64bit": False,
        "is_gui": True,
        "is_cui": False,
        "has_3d_api": False,
    }
    try:
        with open(exe_path, "rb") as f:
            header = f.read(1024)
            if len(header) < 64 or header[:2] != b"MZ":
                return res

            pe_offset = int.from_bytes(header[0x3C:0x40], byteorder="little")
            if pe_offset + 24 > len(header) or header[pe_offset:pe_offset+4] != b"PE\0\0":
                return res

            res["is_pe"] = True
            machine = int.from_bytes(header[pe_offset+4:pe_offset+6], byteorder="little")
            res["is_64bit"] = (machine == 0x8664)  # IMAGE_FILE_MACHINE_AMD64

            opt_header_offset = pe_offset + 24
            if opt_header_offset + 70 <= len(header):
                subsystem = int.from_bytes(header[opt_header_offset+68:opt_header_offset+70], byteorder="little")
                res["is_gui"] = (subsystem == 2)  # IMAGE_SUBSYSTEM_WINDOWS_GUI
                res["is_cui"] = (subsystem == 3)  # IMAGE_SUBSYSTEM_WINDOWS_CUI (Console)

            # Check for DirectX, Vulkan, or gaming imports in the first 128KB
            f.seek(0)
            sample = f.read(131072).lower()
            res["has_3d_api"] = any(lib in sample for lib in [b"d3d11", b"d3d12", b"dxgi", b"vulkan", b"xinput", b"unityplayer"])
    except Exception:
        pass
    return res


def discover_all_executables(game_root: Path, game_folder_name: str) -> List[Dict[str, Any]]:
    """
    Ranks all executables in the game folder using PE header analysis,
    engine structure fingerprinting (Unreal, Unity, Godot, etc.),
    Steam API co-location, and launcher penalties.
    Returns a sorted list of candidates with tags and metadata.
    """
    all_exes = [f for f in game_root.rglob("*.exe") if f.is_file()]
    if not all_exes:
        return []

    # First check max size across binaries to detect launcher vs main game size difference
    max_size_mb = max((f.stat().st_size for f in all_exes), default=0) / (1024 * 1024)

    normalized_game_name = re.sub(r"[^a-zA-Z0-9]", "", game_folder_name).lower()
    candidates = []

    for exe in all_exes:
        if is_blacklisted(exe.name):
            continue

        score = 0
        tags = []
        exe_lower = exe.name.lower()
        exe_stem = exe.stem.lower()
        parent_dir = exe.parent
        parent_lower = str(parent_dir.relative_to(game_root)).lower()
        size_mb = round(exe.stat().st_size / (1024 * 1024), 2)

        # 1. PE Header Analysis
        pe_info = inspect_pe_file(exe)
        if pe_info["is_pe"]:
            if pe_info["is_64bit"]:
                score += 35
                tags.append("x64")
            else:
                tags.append("x86")

            if pe_info["is_gui"]:
                score += 40
            elif pe_info["is_cui"]:
                # Console binary: very likely a server, updater, or command-line tool
                score -= 180
                tags.append("Console Utility")

            if pe_info["has_3d_api"]:
                score += 70
                tags.append("3D/DirectX")

        # 2. Engine Detection & Fingerprinting
        # Unreal Engine 4 / 5
        if "-win64-shipping.exe" in exe_lower or "-shipping.exe" in exe_lower:
            score += 220
            tags.append("Unreal Shipping")
        elif "-win32-shipping.exe" in exe_lower:
            score += 170
            tags.append("Unreal Shipping (x86)")
        elif "-win64.exe" in exe_lower:
            score += 130
            tags.append("Unreal Bin64")

        # Unity Engine (check for <Game>_Data folder or UnityPlayer.dll)
        data_dir_name = f"{exe.stem}_Data"
        if (parent_dir / data_dir_name).exists() and (parent_dir / data_dir_name).is_dir():
            score += 250
            tags.append("Unity Main Binary")
        elif (parent_dir / "UnityPlayer.dll").exists():
            score += 90
            tags.append("Unity Engine")

        # Godot Engine (check for <Game>.pck)
        if (parent_dir / f"{exe.stem}.pck").exists():
            score += 200
            tags.append("Godot Main Binary")

        # 3. Co-location with Steam API & Goldberg
        has_steam_dll = (parent_dir / "steam_api64.dll").exists() or (parent_dir / "steam_api.dll").exists()
        if has_steam_dll:
            score += 120
            tags.append("Steam API")

        if (parent_dir / "steam_appid.txt").exists() or (parent_dir / "steam_settings").exists():
            score += 60

        # 4. Folder Path Heuristics
        if "binaries/win64" in parent_lower or "binaries\\win64" in parent_lower:
            score += 80
        elif "bin/x64" in parent_lower or "bin\\x64" in parent_lower or "bin64" in parent_lower:
            score += 60
        elif "bin" in parent_lower:
            score += 30
        elif parent_lower == ".":
            # Root directory
            score += 25

        # 5. Name Similarity with Game Title
        clean_exe_stem = re.sub(r"[^a-zA-Z0-9]", "", exe_stem).lower()
        if normalized_game_name and (clean_exe_stem in normalized_game_name or normalized_game_name in clean_exe_stem):
            score += 70
            tags.append("Title Match")

        # 6. File Size Weights & Small Stub Detection
        if size_mb > 15:
            score += min(int(size_mb), 80)
        elif size_mb < 3 and max_size_mb > 15:
            # Launcher stub penalty when large shipping binary exists
            score -= 80
            tags.append("Launcher Stub")

        # 7. Launcher / Utility / AntiCheat Penalties
        if any(pat in exe_lower for pat in ["crash", "bugreport", "feedback", "report", "telemetry", "easyanticheat", "battleye", "unins000"]):
            score -= 250
            tags.append("Diagnostic/Stub")

        if any(pat in exe_lower for pat in ["launcher", "prelauncher", "play"]):
            score -= 100
            if "Launcher Stub" not in tags and "Diagnostic/Stub" not in tags:
                tags.append("Launcher")

        if any(pat in exe_lower for pat in ["config", "settings", "autorun", "autoupdater"]):
            score -= 200

        rel_exe = str(exe.relative_to(game_root)).replace("/", "\\")
        rel_dir = str(parent_dir.relative_to(game_root)).replace("/", "\\")
        if rel_dir == ".":
            rel_dir = ""

        candidate_tag = " | ".join(tags) if tags else "Windows Executable"

        candidates.append({
            "rel_path": rel_exe,
            "name": exe.name,
            "rel_dir": rel_dir,
            "size_mb": size_mb,
            "score": score,
            "tag": candidate_tag,
            "is_recommended": False,
        })

    if not candidates:
        # Fallback to largest executable
        best = max(all_exes, key=lambda f: f.stat().st_size)
        rel_exe = str(best.relative_to(game_root)).replace("/", "\\")
        rel_dir = str(best.parent.relative_to(game_root)).replace("/", "\\")
        candidates.append({
            "rel_path": rel_exe,
            "name": best.name,
            "rel_dir": "" if rel_dir == "." else rel_dir,
            "size_mb": round(best.stat().st_size / (1024 * 1024), 2),
            "score": 0,
            "tag": "Fallback Binary",
            "is_recommended": True,
        })
    else:
        # Sort candidates descending by score
        candidates.sort(key=lambda c: c["score"], reverse=True)
        candidates[0]["is_recommended"] = True

    return candidates


def discover_primary_executable(game_root: Path, game_folder_name: str) -> Optional[Dict[str, Any]]:
    """Returns the single highest-scoring primary executable for the game."""
    all_cands = discover_all_executables(game_root, game_folder_name)
    return all_cands[0] if all_cands else None


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
    manifest_info = extract_steam_manifest_info(game_root)
    game_title = args.game_title or manifest_info.get("title") or normalize_title(folder_name)
    app_id = args.app_id or manifest_info.get("app_id") or ""

    print(f"[Discovery] Analyzing game directory: {game_root}")
    print(f"[Discovery] Detected Game Title: {game_title}")
    print(f"[Discovery] Detected Steam App ID: {app_id or 'None (Unknown)'}")

    # Executable discovery
    candidates = discover_all_executables(game_root, folder_name)
    if args.main_exe:
        custom_exe = (game_root / args.main_exe.replace("\\", "/")).resolve()
        if custom_exe.exists():
            rel_exe = str(custom_exe.relative_to(game_root)).replace("/", "\\")
            rel_dir = str(custom_exe.parent.relative_to(game_root)).replace("/", "\\")
            primary_exe = {
                "rel_path": rel_exe,
                "name": custom_exe.name,
                "rel_dir": "" if rel_dir == "." else rel_dir,
                "size_mb": round(custom_exe.stat().st_size / (1024 * 1024), 2),
                "score": 9999,
                "tag": "User Specified Override",
                "is_recommended": True,
            }
        else:
            print(f"Warning: Specified --main-exe '{args.main_exe}' not found! Falling back to auto-discovery.", file=sys.stderr)
            primary_exe = candidates[0] if candidates else None
    else:
        primary_exe = candidates[0] if candidates else None

    if primary_exe:
        print(f"[Discovery] Primary Executable: {primary_exe['rel_path']} ({primary_exe['size_mb']} MB, score={primary_exe.get('score', 0)})")
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
        "candidates": candidates,
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

