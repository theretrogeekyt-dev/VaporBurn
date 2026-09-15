#!/usr/bin/env python3
"""
scripts/sanitize_and_hash.py
Sanitizes game directories by filtering out unnecessary junk (crash dumps,
shader caches, logs, temp download chunks) and generates a SHA-256 checksum
manifest for post-install verification.
Part of the VaporBurn package.
"""

import os
import sys
import hashlib
import fnmatch
import argparse
import json
from pathlib import Path
from typing import List, Tuple, Set

# Glob patterns to exclude (case-insensitive)
EXCLUSION_PATTERNS = [
    # Crash dumps & reports
    "*.dmp",
    "*.mdmp",
    "*.core",
    "CrashReport*",
    "crash_dumps*",
    "*/crash_dumps/*",
    "*/CrashReports/*",
    
    # Shader caches (machine & GPU specific)
    "*.dxvk-cache",
    "*.nv-cache",
    "*.vk-cache",
    "*shadercache*",
    "*ShaderCache*",
    "*/GLCache/*",
    "*/D3DSCache/*",
    "PipelineLibrary.cache",
    "*.ushaderprecache",
    "PSO.cache",
    
    # Logs
    "*.log",
    "*.log.*",
    "*.log.bak",
    "*/Logs/*",
    "*/logs/*",
    "OutputLog.txt",
    
    # Temp download chunks & Steam internal caches
    "*.downloading",
    "*.patch",
    "*.tmp",
    "*.temp",
    "*.part",
    "*.stmp",
    "*.manifest",
    "*/depotcache/*",
    "*/.steam/*",
    "*/downloading/*",
    
    # OS clutter
    "thumbs.db",
    "desktop.ini",
    ".DS_Store",
    "._.DS_Store",
    ".git*",
]


def should_exclude(rel_path: str) -> bool:
    """Checks whether a relative path matches any exclusion pattern."""
    normalized_path = rel_path.replace("\\", "/")
    filename = os.path.basename(normalized_path)
    
    for pat in EXCLUSION_PATTERNS:
        # Check against filename
        if fnmatch.fnmatch(filename.lower(), pat.lower()):
            return True
        # Check against full relative path
        if fnmatch.fnmatch(normalized_path.lower(), pat.lower()):
            return True
        # Check against wildcard path matching
        if pat.startswith("*/") and fnmatch.fnmatch(f"/{normalized_path}".lower(), f"*{pat.lower()}"):
            return True
            
    return False


def calculate_sha256(filepath: Path, buffer_size: int = 1024 * 1024) -> str:
    """Calculates SHA-256 checksum of a file efficiently using 1MB chunks."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(buffer_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def scan_and_sanitize(
    source_dir: Path,
    stage_dir: Path,
    use_hardlinks: bool = True
) -> Tuple[List[Tuple[str, int, str]], int, int]:
    """
    Scans source_dir, skips excluded files, copies or hardlinks sanitized files
    into stage_dir (if stage_dir is provided and different from source_dir),
    and computes SHA-256 for all kept files.
    
    Returns:
      (file_entries, total_kept_bytes, total_excluded_bytes)
    """
    kept_files: List[Tuple[str, int, str]] = []
    total_kept_bytes = 0
    total_excluded_bytes = 0
    excluded_count = 0

    do_staging = stage_dir.resolve() != source_dir.resolve()
    if do_staging:
        stage_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Sanitize] Scanning directory tree: {source_dir}")
    
    all_paths = sorted([p for p in source_dir.rglob("*") if p.is_file()])
    total_items = len(all_paths)
    print(f"[Sanitize] Discovered {total_items} total file(s) before filtering.")

    for idx, file_path in enumerate(all_paths, 1):
        rel_path = str(file_path.relative_to(source_dir))
        
        if should_exclude(rel_path):
            file_size = file_path.stat().st_size
            total_excluded_bytes += file_size
            excluded_count += 1
            continue

        file_size = file_path.stat().st_size
        total_kept_bytes += file_size

        target_path = file_path
        if do_staging:
            dest_file = stage_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Try hardlink first (instantaneous & zero extra disk usage)
            staged = False
            if use_hardlinks:
                try:
                    if dest_file.exists():
                        dest_file.unlink()
                    os.link(file_path, dest_file)
                    staged = True
                except (OSError, NotImplementedError):
                    staged = False
            
            if not staged:
                # Fallback to copy
                import shutil
                shutil.copy2(file_path, dest_file)
            target_path = dest_file

        # Calculate checksum on kept file
        checksum = calculate_sha256(target_path)
        # Windows path format for checksums.sha256
        win_rel_path = rel_path.replace("/", "\\")
        kept_files.append((win_rel_path, file_size, checksum))

        if idx % 500 == 0 or idx == total_items:
            print(f"[Sanitize] Processed {idx}/{total_items} files...")

    print(f"[Sanitize] Sanitization Complete:")
    print(f"  - Kept: {len(kept_files)} files ({round(total_kept_bytes / (1024*1024), 2)} MB)")
    print(f"  - Excluded: {excluded_count} bloat files ({round(total_excluded_bytes / (1024*1024), 2)} MB stripped)")

    return kept_files, total_kept_bytes, total_excluded_bytes


def write_manifest(manifest_path: Path, kept_files: List[Tuple[str, int, str]]) -> None:
    """Writes standard sha256sum manifest (*relative/path)."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        for win_rel_path, _, checksum in kept_files:
            f.write(f"{checksum} *{win_rel_path}\n")
    print(f"[Sanitize] Saved SHA-256 verification manifest to: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="VaporBurn Sanitizer & SHA-256 Generator")
    parser.add_argument("--source-dir", required=True, help="Input raw game directory")
    parser.add_argument("--stage-dir", required=True, help="Staging output directory")
    parser.add_argument("--manifest-out", required=True, help="Output checksums.sha256 path")
    parser.add_argument("--stats-json", help="Optional path to output stats JSON")
    parser.add_argument("--no-hardlinks", action="store_true", help="Force file copying instead of hardlinks")

    args = parser.parse_args()
    source_dir = Path(args.source_dir).resolve()
    stage_dir = Path(args.stage_dir).resolve()
    manifest_out = Path(args.manifest_out).resolve()

    if not source_dir.exists():
        print(f"Error: Source directory {source_dir} not found!", file=sys.stderr)
        sys.exit(1)

    kept_files, kept_bytes, excluded_bytes = scan_and_sanitize(
        source_dir=source_dir,
        stage_dir=stage_dir,
        use_hardlinks=not args.no_hardlinks
    )

    write_manifest(manifest_out, kept_files)

    if args.stats_json:
        stats_path = Path(args.stats_json).resolve()
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats = {
            "total_files_kept": len(kept_files),
            "total_bytes_kept": kept_bytes,
            "total_mb_kept": round(kept_bytes / (1024 * 1024), 2),
            "total_gb_kept": round(kept_bytes / (1024 * 1024 * 1024), 2),
            "total_bytes_excluded": excluded_bytes,
            "total_mb_excluded": round(excluded_bytes / (1024 * 1024), 2),
        }
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)


if __name__ == "__main__":
    main()

