"""
app/library.py
Scans input backup folders, extracts metadata, discovers binaries,
and generates Steam library card information.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import INPUT_DIR
from scripts.discover_exe import (
    discover_primary_executable,
    find_steam_appid,
    find_goldberg_locations,
    find_save_data,
    find_redistributables,
    normalize_title,
)


def format_size(size_bytes: int) -> str:
    """Formats raw byte count into human-readable representation."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def get_dir_size(path: Path) -> int:
    """Computes total directory size in bytes without recursing into deep exclusions."""
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    continue
    except OSError:
        pass
    return total


def inspect_game_folder(game_dir: Path) -> Dict[str, Any]:
    """Extracts rich metadata for a single game directory."""
    folder_name = game_dir.name
    raw_title = normalize_title(folder_name)
    app_id = find_steam_appid(game_dir) or "480"

    # Steam CDN Banner Art
    banner_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
    if app_id == "480":
        banner_fallback = "/static/default_banner.jpg"
    else:
        banner_fallback = banner_url

    goldberg_info = find_goldberg_locations(game_dir)
    save_info = find_save_data(game_dir)
    redists = find_redistributables(game_dir)
    primary_exe = discover_primary_executable(game_dir, folder_name)
    size_bytes = get_dir_size(game_dir)

    return {
        "folder_name": folder_name,
        "title": raw_title,
        "app_id": app_id,
        "banner_url": banner_url,
        "banner_fallback": banner_fallback,
        "size_bytes": size_bytes,
        "size_formatted": format_size(size_bytes),
        "has_goldberg": goldberg_info["has_goldberg"],
        "has_saves": save_info["has_saves"],
        "save_count": save_info.get("file_count", 0),
        "redist_count": len(redists),
        "primary_exe": primary_exe.get("rel_path") if primary_exe else None,
        "path": str(game_dir),
    }


def scan_input_library() -> List[Dict[str, Any]]:
    """
    Scans INPUT_DIR. If INPUT_DIR contains game subdirectories, returns a list of them.
    If INPUT_DIR itself appears to be a single game directory, returns it as the only item.
    """
    if not INPUT_DIR.exists() or not INPUT_DIR.is_dir():
        return []

    # Check if INPUT_DIR itself contains executables or steam_api
    top_exes = list(INPUT_DIR.glob("*.exe"))
    top_dlls = list(INPUT_DIR.glob("steam_api*.dll"))
    
    subdirs = [p for p in INPUT_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")]

    # If input directory is itself a single game (contains top-level game files or Binaries)
    if (top_exes or top_dlls or (INPUT_DIR / "Binaries").exists()) and len(subdirs) <= 3:
        return [inspect_game_folder(INPUT_DIR)]

    # Otherwise enumerate each subfolder as an individual game
    games = []
    for sdir in sorted(subdirs, key=lambda p: p.name.lower()):
        # Skip special utility folders
        if sdir.name.lower() in ["lost+found", "system volume information", "$recycle.bin"]:
            continue
        games.append(inspect_game_folder(sdir))

    return games

