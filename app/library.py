"""
app/library.py
Scans input backup folders, filters out non-game system directories (e.g. @eaDir, recycle bins),
extracts rich metadata from Steam manifests and store APIs, and generates library card information.
"""

import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import INPUT_DIR, DATA_DIR
from scripts.discover_exe import (
    discover_primary_executable,
    discover_all_executables,
    extract_steam_manifest_info,
    is_valid_game_dir,
    is_dependency_dir,
    REDIST_TOOL_APP_IDS,
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
    candidates = discover_all_executables(game_dir, folder_name)
    primary_exe = candidates[0] if candidates else None
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
        "candidates": candidates,
        "path": str(game_dir),
    }


def find_candidate_game_dirs(input_dir: Path) -> List[Path]:
    """
    Discovers candidate game directories inside input_dir.
    Supports:
    1. Steam library layout: /input/steamapps/common/<Game>
    2. Common container layout: /input/common/<Game>
    3. Direct subdirectories: /input/<Game>
    4. Standalone root game: /input is itself a game
    """
    if not input_dir.exists() or not input_dir.is_dir():
        return []

    # 1. Check for steamapps/common structure
    steam_common = input_dir / "steamapps" / "common"
    if steam_common.exists() and steam_common.is_dir():
        common_candidates = [d for d in steam_common.iterdir() if d.is_dir() and is_valid_game_dir(d)]
        if common_candidates:
            return common_candidates

    # 2. Check for common/ container directly in input
    direct_common = input_dir / "common"
    if direct_common.exists() and direct_common.is_dir():
        common_candidates = [d for d in direct_common.iterdir() if d.is_dir() and is_valid_game_dir(d)]
        if common_candidates:
            return common_candidates

    # 3. Enumerate direct subdirectories
    subdirs = [p for p in input_dir.iterdir() if p.is_dir()]
    valid_subdirs = [s for s in subdirs if is_valid_game_dir(s)]

    # 4. Check if input_dir itself is a single standalone game
    top_exes = [f for f in input_dir.glob("*.exe") if not f.name.startswith(".")]
    if len(valid_subdirs) == 0 and (top_exes or (input_dir / "Binaries").exists() or list(input_dir.glob("appmanifest_*.acf"))):
        if is_valid_game_dir(input_dir):
            return [input_dir]

    return valid_subdirs


def scan_input_library() -> List[Dict[str, Any]]:
    """
    Scans INPUT_DIR for genuine game backups.
    Filters out dependencies (e.g. Steamworks Shared, DirectX, vcredist),
    container folders, and deduplicates multiple copies/backups of the same game.
    """
    candidate_dirs = find_candidate_game_dirs(INPUT_DIR)
    if not candidate_dirs:
        return []

    scanned_games: List[Dict[str, Any]] = []
    for gdir in candidate_dirs:
        try:
            game_info = inspect_game_folder(gdir)
            # Filter out dependencies by AppID or folder name
            if game_info.get("app_id") in REDIST_TOOL_APP_IDS or is_dependency_dir(game_info.get("folder_name", "")):
                continue
            # Ensure at least one candidate or primary_exe exists
            if not game_info.get("candidates") and not game_info.get("primary_exe"):
                continue
            scanned_games.append(game_info)
        except Exception as e:
            print(f"[Library] Warning: Error inspecting {gdir.name}: {e}")

    # Deduplication pass:
    # Multiple directories may exist for the same game (e.g. "Doom 3", "Doom 3 [208200]",
    # duplicate backup folders, or symlinks).
    # We maintain index by:
    # 1. canonical real path
    # 2. app_id (if valid)
    # 3. clean title slug (alphanumeric lowercase)
    def game_quality_score(g: Dict[str, Any]) -> int:
        score = 0
        if g.get("has_goldberg"):
            score += 100
        if g.get("has_saves"):
            score += 50
        if g.get("app_id"):
            score += 40
        if g.get("primary_exe"):
            score += 30
        score += min(int(g.get("size_bytes", 0) / (1024 * 1024 * 100)), 50)
        fn_lower = g.get("folder_name", "").lower()
        if any(bad in fn_lower for bad in ["copy", "backup", ".bak", "old"]):
            score -= 60
        return score

    unique_by_id: Dict[str, Dict[str, Any]] = {}
    unique_by_title: Dict[str, Dict[str, Any]] = {}
    unique_by_path: Dict[str, Dict[str, Any]] = {}

    for game in scanned_games:
        real_path = str(Path(game["path"]).resolve())
        app_id = game.get("app_id")
        title_slug = re.sub(r"[^a-z0-9]", "", game.get("title", "").lower())

        # Check if an existing game matches any key
        existing = unique_by_path.get(real_path)
        if not existing and app_id:
            existing = unique_by_id.get(app_id)
        if not existing and title_slug:
            existing = unique_by_title.get(title_slug)

        if existing:
            # Duplicate found! Keep whichever has the higher quality score
            if game_quality_score(game) > game_quality_score(existing):
                old_path = str(Path(existing["path"]).resolve())
                old_id = existing.get("app_id")
                old_slug = re.sub(r"[^a-z0-9]", "", existing.get("title", "").lower())
                unique_by_path.pop(old_path, None)
                if old_id:
                    unique_by_id.pop(old_id, None)
                if old_slug:
                    unique_by_title.pop(old_slug, None)

                unique_by_path[real_path] = game
                if app_id:
                    unique_by_id[app_id] = game
                if title_slug:
                    unique_by_title[title_slug] = game
        else:
            unique_by_path[real_path] = game
            if app_id:
                unique_by_id[app_id] = game
            if title_slug:
                unique_by_title[title_slug] = game

    # Collect unique list preserving object identity
    seen_ptrs = set()
    deduped: List[Dict[str, Any]] = []
    for g in unique_by_path.values():
        ptr = id(g)
        if ptr not in seen_ptrs:
            seen_ptrs.add(ptr)
            deduped.append(g)

    deduped.sort(key=lambda g: g.get("title", "").lower())
    return deduped
