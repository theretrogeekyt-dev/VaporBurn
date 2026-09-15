"""
app/library.py
Scans input backup folders, filters out non-game system directories (e.g. @eaDir, recycle bins),
extracts rich metadata from Steam manifests and store APIs, and generates library card information.
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import INPUT_DIR, DATA_DIR
from scripts.discover_exe import (
    discover_primary_executable,
    extract_steam_manifest_info,
    is_valid_game_dir,
    find_goldberg_locations,
    find_save_data,
    find_redistributables,
    normalize_title,
)

TITLES_CACHE_FILE = DATA_DIR / "steam_titles_cache.json"


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


def load_cached_titles() -> Dict[str, str]:
    """Loads locally cached Steam AppID -> Title mappings."""
    if not TITLES_CACHE_FILE.exists():
        return {}
    try:
        with open(TITLES_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cached_title(app_id: str, title: str):
    """Saves a discovered Steam title to local cache."""
    cache = load_cached_titles()
    cache[app_id] = title
    try:
        TITLES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TITLES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def resolve_steam_title(app_id: str, fallback_title: str) -> str:
    """
    Attempts to resolve official game title for an AppID from local cache
    or Steam public store API (with short timeout).
    """
    if not app_id or not app_id.isdigit():
        return fallback_title

    # 1. Check local cache first
    cached = load_cached_titles().get(app_id)
    if cached:
        return cached

    # 2. Query Steam Store public API (timeout 2s to prevent blocking UI)
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get(app_id, {}).get("success"):
                official_title = data[app_id]["data"].get("name")
                if official_title:
                    save_cached_title(app_id, official_title)
                    return official_title
    except Exception:
        pass

    return fallback_title


def inspect_game_folder(game_dir: Path) -> Dict[str, Any]:
    """Extracts rich metadata for a single game directory."""
    folder_name = game_dir.name
    fallback_title = normalize_title(folder_name)

    # 1. Extract metadata from Steam manifests or appid files
    manifest_info = extract_steam_manifest_info(game_dir)
    app_id = manifest_info.get("app_id")
    
    # Resolve best title
    if manifest_info.get("title"):
        title = manifest_info["title"]
    elif app_id:
        title = resolve_steam_title(app_id, fallback_title)
    else:
        title = fallback_title

    # 2. Steam CDN Banner Art
    if app_id:
        banner_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
        banner_fallback = f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
    else:
        banner_url = "/static/default_banner.svg"
        banner_fallback = "/static/default_banner.svg"

    goldberg_info = find_goldberg_locations(game_dir)
    save_info = find_save_data(game_dir)
    redists = find_redistributables(game_dir)
    primary_exe = discover_primary_executable(game_dir, folder_name)
    size_bytes = get_dir_size(game_dir)

    return {
        "folder_name": folder_name,
        "title": title,
        "app_id": app_id or "",
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
    Scans INPUT_DIR. Filters out NAS metadata directories like @eaDir, #recycle,
    and empty folders. Validates that candidate folders contain genuine game binaries
    or Steam manifests.
    """
    if not INPUT_DIR.exists() or not INPUT_DIR.is_dir():
        return []

    # Check if INPUT_DIR itself is a single game directory
    subdirs = [p for p in INPUT_DIR.iterdir() if p.is_dir()]
    valid_subdirs = [s for s in subdirs if is_valid_game_dir(s)]

    top_exes = [f for f in INPUT_DIR.glob("*.exe") if not f.name.startswith(".")]
    
    # If input directory contains a game directly at root and no valid subdirectories
    if (top_exes or (INPUT_DIR / "Binaries").exists() or list(INPUT_DIR.glob("appmanifest_*.acf"))) and len(valid_subdirs) == 0:
        if is_valid_game_dir(INPUT_DIR):
            return [inspect_game_folder(INPUT_DIR)]

    # Otherwise enumerate only valid game subdirectories
    games = []
    for sdir in sorted(valid_subdirs, key=lambda p: p.name.lower()):
        try:
            games.append(inspect_game_folder(sdir))
        except Exception as e:
            print(f"[Library] Warning: Error inspecting {sdir.name}: {e}")

    return games
