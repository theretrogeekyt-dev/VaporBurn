#!/usr/bin/env python3
"""
scripts/iso_packager.py
Calculates disc layouts (single or multi-disc spanning) and packages installer
binaries (setup.exe, setup-*.bin, checksums.sha256, autorun.inf) into ISOs
using xorriso.
Part of the VaporBurn package.
"""

import os
import sys
import subprocess
import shutil
import argparse
import re
from pathlib import Path
from typing import List, Dict

# Media size presets in MegaBytes (MB)
MEDIA_PRESETS = {
    "dvd5": 4480,       # 4.37 GiB
    "dvd9": 8150,       # 7.95 GiB
    "bd25": 23500,      # ~23 GiB
    "bd50": 47000,      # ~46 GiB
    "single": 0,        # No limit (single monolithic ISO)
}


def sanitize_volid(title: str, disc_num: int = 1, total_discs: int = 1) -> str:
    """Generates an ISO-9660 compliant volume identifier (max 32 chars)."""
    clean = re.sub(r"[^A-Za-z0-9]", "_", title).strip("_").upper()
    suffix = f"_D{disc_num}" if total_discs > 1 else ""
    max_len = 32 - len(suffix)
    return (clean[:max_len] + suffix)[:32]


def create_autorun_inf(target_dir: Path, title: str, exe_name: str = "setup.exe") -> None:
    """Generates standard Windows autorun.inf."""
    autorun_file = target_dir / "autorun.inf"
    content = (
        f"[autorun]\r\n"
        f"open={exe_name}\r\n"
        f"icon={exe_name},0\r\n"
        f"label={title}\r\n"
    )
    autorun_file.write_text(content, encoding="utf-8")


def plan_discs(
    installer_files: List[Path],
    disc_size_mb: int,
    temp_disc_root: Path
) -> List[Dict]:
    """
    Distributes installer files across discs.
    Disc 1 gets setup.exe, checksums.sha256, autorun.inf, and as many setup-*.bin files as fit.
    Subsequent discs get subsequent setup-*.bin files.
    """
    if disc_size_mb <= 0:
        # Single disc mode
        return [{
            "disc_number": 1,
            "total_discs": 1,
            "files": installer_files,
            "target_dir": temp_disc_root / "disc_1"
        }]

    disc_size_bytes = disc_size_mb * 1024 * 1024
    discs = []
    
    # Separate core files from bin slices
    core_files = []
    bin_files = []
    for f in installer_files:
        if f.name.lower().endswith(".bin"):
            bin_files.append(f)
        else:
            core_files.append(f)
            
    # Sort bin slices numerically (setup-1.bin, setup-2.bin, ...)
    def bin_sort_key(p: Path):
        match = re.search(r"(\d+)", p.stem)
        return int(match.group(1)) if match else p.stem

    bin_files.sort(key=bin_sort_key)

    # Calculate disc 1
    current_disc_files = list(core_files)
    current_disc_bytes = sum(f.stat().st_size for f in current_disc_files)
    disc_num = 1
    
    for bin_file in bin_files:
        b_size = bin_file.stat().st_size
        if current_disc_bytes + b_size > disc_size_bytes and current_disc_files:
            # Finalize current disc
            discs.append({
                "disc_number": disc_num,
                "files": current_disc_files,
                "target_dir": temp_disc_root / f"disc_{disc_num}"
            })
            disc_num += 1
            current_disc_files = []
            current_disc_bytes = 0

        current_disc_files.append(bin_file)
        current_disc_bytes += b_size

    if current_disc_files:
        discs.append({
            "disc_number": disc_num,
            "files": current_disc_files,
            "target_dir": temp_disc_root / f"disc_{disc_num}"
        })

    total_discs = len(discs)
    for d in discs:
        d["total_discs"] = total_discs

    return discs


def build_iso(disc_dir: Path, output_iso: Path, vol_id: str) -> bool:
    """Invokes xorriso to generate a Joliet/RockRidge/UDF ISO image."""
    cmd = [
        "xorriso",
        "-as", "mkisofs",
        "-iso-level", "3",
        "-joliet",
        "-joliet-long",
        "-rational-rock",
        "-volid", vol_id,
        "-o", str(output_iso),
        str(disc_dir)
    ]
    print(f"[ISO] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        print(f"[ISO] Error creating ISO {output_iso}:\n{result.stdout}", file=sys.stderr)
        return False
    print(f"[ISO] Successfully created: {output_iso} ({round(output_iso.stat().st_size / (1024*1024), 2)} MB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="VaporBurn ISO Packager")
    parser.add_argument("--installer-dir", required=True, help="Directory containing compiled setup.exe, .bin slices, checksums")
    parser.add_argument("--output-dir", required=True, help="Destination directory for output .iso files")
    parser.add_argument("--game-title", default="Game", help="Game Title for Volume ID and autorun")
    parser.add_argument("--iso-name", help="Base filename for output ISO (without .iso extension)")
    parser.add_argument("--disc-type", default="single", choices=["single", "dvd5", "dvd9", "bd25", "bd50", "custom"], help="Target disc media")
    parser.add_argument("--disc-size-mb", type=int, default=0, help="Custom disc capacity limit in MB (used if --disc-type custom)")
    parser.add_argument("--work-dir", default="/tmp/vaporburn_iso", help="Temporary workspace for staging discs")

    args = parser.parse_args()
    installer_dir = Path(args.installer_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    work_dir = Path(args.work_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not installer_dir.exists():
        print(f"Error: Installer directory {installer_dir} does not exist!", file=sys.stderr)
        sys.exit(1)

    # Determine size cap
    if args.disc_type in MEDIA_PRESETS:
        disc_size_mb = MEDIA_PRESETS[args.disc_type]
    else:
        disc_size_mb = args.disc_size_mb

    # Gather installer files (setup.exe, setup-*.bin, checksums.sha256, etc.)
    all_files = [f for f in installer_dir.iterdir() if f.is_file()]
    if not any(f.name.lower().endswith(".exe") for f in all_files):
        print(f"Error: No setup executable found in {installer_dir}!", file=sys.stderr)
        sys.exit(1)

    base_iso_name = args.iso_name or re.sub(r"[^A-Za-z0-9_\-\.]", "_", args.game_title)

    # Plan disc distribution
    discs = plan_discs(all_files, disc_size_mb, work_dir)
    total_discs = len(discs)
    print(f"[ISO] Planned {total_discs} disc(s) for '{args.game_title}' (Mode: {args.disc_type})")

    created_isos = []

    for d in discs:
        num = d["disc_number"]
        t_dir = d["target_dir"]
        t_dir.mkdir(parents=True, exist_ok=True)

        # Stage files (hardlinks or copy)
        for src_file in d["files"]:
            dst_file = t_dir / src_file.name
            if dst_file.exists():
                dst_file.unlink()
            try:
                os.link(src_file, dst_file)
            except OSError:
                shutil.copy2(src_file, dst_file)

        # Create autorun.inf on each disc
        create_autorun_inf(t_dir, args.game_title)

        vol_id = sanitize_volid(args.game_title, num, total_discs)
        
        if total_discs == 1:
            out_iso = output_dir / f"{base_iso_name}.iso"
        else:
            out_iso = output_dir / f"{base_iso_name}_Disc{num}.iso"

        if build_iso(t_dir, out_iso, vol_id):
            created_isos.append(out_iso)

    # Clean up temp staging directory
    shutil.rmtree(work_dir, ignore_errors=True)

    print(f"[ISO] All ISOs successfully built:")
    for iso in created_isos:
        print(f"  -> {iso}")


if __name__ == "__main__":
    main()

