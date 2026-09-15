"""
app/config.py
Configuration and persistence management for VaporBurn Web UI.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any

# Root Paths
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
SCRIPTS_DIR = BASE_DIR / "scripts"
TEMPLATE_ISS = BASE_DIR / "installer_template.iss"

# Storage Mount Paths
INPUT_DIR = Path(os.getenv("INPUT_DIR", "/input")).resolve()
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output")).resolve()
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()

# Server Settings
PORT = int(os.getenv("PORT", "8081"))
PUID = int(os.getenv("PUID", "1000"))
PGID = int(os.getenv("PGID", "1000"))
UMASK = os.getenv("UMASK", "002")

# Ensure critical directories exist
for d in [DATA_DIR, OUTPUT_DIR, WORKSPACE_DIR]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "default_disc_type": "single",
    "default_disc_size_mb": 0,
    "default_player_name": "VaporPlayer",
    "default_language": "english",
    "default_steamid": "76561197960287930",
    "default_limit_ram": True,
    "default_firewall_rule": True,
    "chunk_size_bytes": 4294967295,
    "wine_debug": "-all",
}


def load_settings() -> Dict[str, Any]:
    """Loads configuration settings from disk with defaults fallback."""
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Persists settings updates to disk."""
    current = load_settings()
    current.update(new_settings)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return current
