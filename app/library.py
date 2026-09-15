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
    is_system_or_ignored_dir,
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


def get_base_folder_key(folder_name: str) -> str:
    """
    Normalizes folder name to identify true duplicate copies (e.g. - Copy, _backup, (1)).
    Leaves distinct editions/versions intact.
    """
    clean = folder_name.strip()
    # Strip bracketed AppID: [1091500] or (1091500)
    clean = re.sub(r"\s*[\[\(]\d{3,8}[\]\)]\s*$", "", clean, flags=re.I)
    # Strip copy / backup suffixes: - Copy, - Copy (2), (1), _backup, -backup, .bak, _old
    clean = re.sub(r"(\s*[-_]\s*copy(\s*\(\d+\))?|\s*\(\d+\)|\.bak|[-_]backup|[-_]old)$", "", clean, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", clean.lower())


def inspect_game_folder(game_dir: Path) -> Dict[str, Any]:
    """Extracts rich metadata for a single game directory."""
    folder_name = game_dir.name
    fallback_title = normalize_title(folder_name)

    # 1. Extract metadata from Steam manifests or appid files
    manifest_info = extract_steam_manifest_info(game_dir)
    app_id = manifest_info.get("app_id")
    manifest_title = manifest_info.get("title")

    # Check if folder name contains edition / version keywords
    # (e.g. "Alpha 1", "Beta", "Demo", "Episode One", "Resurrection of Evil", "BFG Edition")
    edition_keywords = {
        "alpha", "beta", "demo", "prologue", "episode", "resurrection",
        "edition", "remastered", "vr", "patch", "build", "standalone"
    }
    folder_lower = folder_name.lower()
    has_edition_in_folder = any(kw in folder_lower for kw in edition_keywords)

    # If folder name contains specific edition info, preserve it so distinct builds don't collide
    if has_edition_in_folder:
        title = fallback_title
    elif manifest_title:
        title = manifest_title
    elif app_id and (re.match(r"^\d+$", folder_name) or folder_lower in {"game", "app", "steam"}):
        # Folder name is completely uninformative (e.g. "208200" or "game"), resolve from cache/API
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
    1. Direct subdirectories: /input/<Game>
    2. Steam library layout: /input/steamapps/common/<Game>
    3. Common container layout: /input/common/<Game>
    4. Standalone root game: /input is itself a game
    """
    if not input_dir.exists() or not input_dir.is_dir():
        return []

    candidates: List[Path] = []

    # 1. Direct subdirectories
    try:
        for p in input_dir.iterdir():
            if not p.is_dir() or is_system_or_ignored_dir(p.name):
                continue
            if is_valid_game_dir(p):
                candidates.append(p)
    except OSError:
        pass

    # 2. Check for steamapps/common structure
    steam_common = input_dir / "steamapps" / "common"
    if steam_common.exists() and steam_common.is_dir():
        try:
            for p in steam_common.iterdir():
                if p.is_dir() and not is_system_or_ignored_dir(p.name) and is_valid_game_dir(p):
                    candidates.append(p)
        except OSError:
            pass

    # 3. Check for common/ container directly in input
    direct_common = input_dir / "common"
    if direct_common.exists() and direct_common.is_dir():
        try:
            for p in direct_common.iterdir():
                if p.is_dir() and not is_system_or_ignored_dir(p.name) and is_valid_game_dir(p):
                    candidates.append(p)
        except OSError:
            pass

    # 4. Check if input_dir itself is a single standalone game
    if not candidates:
        if is_valid_game_dir(input_dir):
            return [input_dir]

    # Deduplicate candidate paths by canonical real path
    seen = set()
    unique_candidates: List[Path] = []
    for c in candidates:
        try:
            resolved = str(c.resolve())
        except Exception:
            resolved = str(c)
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(c)

    return unique_candidates


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
    # duplicate backup folders like "Doom 3 - Copy" or "Doom 3_backup", or symlinks).
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

    unique_by_path: Dict[str, Dict[str, Any]] = {}
    unique_by_base_key: Dict[str, Dict[str, Any]] = {}

    for game in scanned_games:
        real_path = str(Path(game["path"]).resolve())
        base_key = get_base_folder_key(game["folder_name"])
        app_id = game.get("app_id") or ""

        # Check for path duplicate
        existing = unique_by_path.get(real_path)
        if not existing:
            # Check for explicit copy / backup duplicate
            # (only if base_key matches AND either app_id matches or one has no app_id)
            cand = unique_by_base_key.get(base_key)
            if cand:
                cand_id = cand.get("app_id") or ""
                if not app_id or not cand_id or app_id == cand_id:
                    existing = cand

        if existing:
            # Duplicate found! Keep whichever has the higher quality score
            if game_quality_score(game) > game_quality_score(existing):
                old_path = str(Path(existing["path"]).resolve())
                old_base_key = get_base_folder_key(existing["folder_name"])
                unique_by_path.pop(old_path, None)
                unique_by_base_key.pop(old_base_key, None)

                unique_by_path[real_path] = game
                unique_by_base_key[base_key] = game
        else:
            unique_by_path[real_path] = game
            unique_by_base_key[base_key] = game

    deduped = list(unique_by_path.values())
    deduped.sort(key=lambda g: g.get("title", "").lower())
    return deduped
