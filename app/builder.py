"""
app/builder.py
Asynchronous orchestrator for sanitization, Inno Setup compilation under Wine,
and ISO image packaging with real-time log streaming.
"""

import os
import sys
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, Callable, Awaitable

from app.config import (
    BASE_DIR,
    OUTPUT_DIR,
    WORKSPACE_DIR,
    TEMPLATE_ISS,
    PUID,
    PGID,
    UMASK,
)
from scripts.discover_exe import discover_primary_executable, find_steam_appid, find_redistributables, find_save_data
from scripts.sanitize_and_hash import scan_and_sanitize, write_manifest
from scripts.iso_packager import plan_discs, build_iso, sanitize_volid, create_autorun_inf, MEDIA_PRESETS


async def run_packaging_pipeline(
    job_id: str,
    game_path: Path,
    params: Dict[str, Any],
    log_callback: Callable[[str], Awaitable[None]],
    progress_callback: Callable[[int, str], Awaitable[None]],
    is_cancelled: Callable[[], bool],
) -> Dict[str, Any]:
    """
    Executes the full packaging pipeline asynchronously with real-time log callbacks.
    """
    job_workspace = WORKSPACE_DIR / f"job_{job_id}"
    staging_dir = job_workspace / "staging"
    build_out_dir = job_workspace / "installer_build"
    disc_work_dir = job_workspace / "disc_work"

    job_workspace.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    build_out_dir.mkdir(parents=True, exist_ok=True)
    disc_work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # -------------------------------------------------------------
        # Stage 1: Discovery & Parameter Resolution
        # -------------------------------------------------------------
        await progress_callback(5, "Analyzing game files & dependencies...")
        await log_callback(f"[Pipeline] Starting packaging job {job_id} for: {game_path.name}")
        
        folder_name = game_path.name
        game_title = params.get("game_title") or folder_name
        app_id = params.get("app_id") or find_steam_appid(game_path) or "480"
        
        primary_exe_override = params.get("main_exe")
        if primary_exe_override and (game_path / primary_exe_override).exists():
            custom_exe = game_path / primary_exe_override
            primary_exe = {
                "rel_path": str(custom_exe.relative_to(game_path)).replace("/", "\\"),
                "name": custom_exe.name,
                "rel_dir": str(custom_exe.parent.relative_to(game_path)).replace("/", "\\") if str(custom_exe.parent.relative_to(game_path)) != "." else ""
            }
        else:
            primary_exe = discover_primary_executable(game_path, folder_name)

        if not primary_exe:
            primary_exe = {"rel_path": "Game.exe", "name": "Game.exe", "rel_dir": ""}

        await log_callback(f"[Discovery] Title: {game_title} | AppID: {app_id} | Binary: {primary_exe['rel_path']}")

        # Redistributables
        redists = find_redistributables(game_path)
        has_dx = "1" if any(r["id"] == "directx" for r in redists) else "0"
        dx_exe = next((r["exe_rel"] for r in redists if r["id"] == "directx"), "")
        has_vc64 = "1" if any(r["id"] == "vcredist_x64" for r in redists) else "0"
        vc64_exe = next((r["exe_rel"] for r in redists if r["id"] == "vcredist_x64"), "")
        has_vc86 = "1" if any(r["id"] == "vcredist_x86" for r in redists) else "0"
        vc86_exe = next((r["exe_rel"] for r in redists if r["id"] == "vcredist_x86"), "")

        # Saves
        save_info = find_save_data(game_path)
        has_saves = "1" if save_info.get("has_saves") else "0"
        saves_rel = save_info.get("save_dir_rel", "").replace("/", "\\")

        if is_cancelled():
            raise asyncio.CancelledError()

        # -------------------------------------------------------------
        # Stage 2: Sanitization & Checksum Manifest Generation
        # -------------------------------------------------------------
        await progress_callback(15, "Sanitizing assets (stripping crash dumps, shader caches, logs)...")
        await log_callback("[Sanitize] Staging and computing SHA-256 manifest...")

        manifest_file = staging_dir / "checksums.sha256"
        # Run scan and sanitize in executor thread so async event loop stays snappy
        loop = asyncio.get_running_loop()
        kept_files, kept_bytes, excluded_bytes = await loop.run_in_executor(
            None,
            scan_and_sanitize,
            game_path,
            staging_dir,
            True # use hardlinks for instant staging
        )
        await loop.run_in_executor(None, write_manifest, manifest_file, kept_files)

        mb_kept = round(kept_bytes / (1024 * 1024), 2)
        mb_stripped = round(excluded_bytes / (1024 * 1024), 2)
        await log_callback(f"[Sanitize] Staged {len(kept_files)} files ({mb_kept} MB kept, {mb_stripped} MB bloat stripped)")

        if is_cancelled():
            raise asyncio.CancelledError()

        # -------------------------------------------------------------
        # Stage 3: Inno Setup Compilation via Wine
        # -------------------------------------------------------------
        await progress_callback(35, "Compiling Inno Setup Windows installer (LZMA2 Ultra compression)...")
        await log_callback("[InnoSetup] Invoking ISCC compiler via Wine...")

        # Convert linux staging and build paths to Windows paths for Inno Setup
        win_staging = str(staging_dir)
        win_build_out = str(build_out_dir)

        # Attempt winepath if available
        try:
            wp_src = subprocess.check_output(["winepath", "-w", str(staging_dir)], text=True).strip()
            wp_out = subprocess.check_output(["winepath", "-w", str(build_out_dir)], text=True).strip()
            win_staging = wp_src
            win_build_out = wp_out
        except Exception:
            pass

        chunk_size = str(params.get("chunk_size", 4294967295))
        iscc_cmd = [
            "wine",
            "/opt/innosetup/app/ISCC.exe",
            f"/DGameName={game_title}",
            f"/DAppExe={primary_exe['rel_path']}",
            f"/DAppExeDir={primary_exe['rel_dir']}",
            f"/DAppId={app_id}",
            f"/DSourceDir={win_staging}",
            f"/DOutputDir={win_build_out}",
            "/DOutputBaseName=setup",
            f"/DChunkSize={chunk_size}",
            f"/DHasDirectX={has_dx}",
            f"/DDirectXExe={dx_exe}",
            f"/DHasVCRedist64={has_vc64}",
            f"/DVCRedist64Exe={vc64_exe}",
            f"/DHasVCRedist86={has_vc86}",
            f"/DVCRedist86Exe={vc86_exe}",
            f"/DHasSaves={has_saves}",
            f"/DSavesRelDir={saves_rel}",
            str(TEMPLATE_ISS)
        ]

        await log_callback(f"[InnoSetup] Command: {' '.join(iscc_cmd[:5])} ...")

        # Execute wine process asynchronously and stream terminal output
        proc = await asyncio.create_subprocess_exec(
            *iscc_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "WINEDEBUG": "-all", "WINEPREFIX": "/tmp/wine"}
        )

        while True:
            if is_cancelled():
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                raise asyncio.CancelledError()

            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").rstrip()
            if text:
                await log_callback(f"[ISCC] {text}")
                # Parse progress markers from ISCC output
                if "Compressing" in text:
                    await progress_callback(55, text[:60])

        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Inno Setup compilation failed with exit code {proc.returncode}")

        setup_exe = build_out_dir / "setup.exe"
        if not setup_exe.exists():
            raise RuntimeError("Inno Setup finished but setup.exe was not created!")

        await log_callback("[InnoSetup] Installer compiled successfully!")

        if is_cancelled():
            raise asyncio.CancelledError()

        # -------------------------------------------------------------
        # Stage 4: ISO Packaging with xorriso
        # -------------------------------------------------------------
        await progress_callback(75, "Creating mountable ISO image(s) with xorriso...")
        await log_callback("[ISO] Planning disc layouts...")

        disc_type = params.get("disc_type", "single")
        disc_size_mb = params.get("disc_size_mb", 0)
        if disc_type in MEDIA_PRESETS:
            disc_size_mb = MEDIA_PRESETS[disc_type]

        installer_files = [f for f in build_out_dir.iterdir() if f.is_file()]
        discs = plan_discs(installer_files, disc_size_mb, disc_work_dir)
        total_discs = len(discs)
        await log_callback(f"[ISO] Planned {total_discs} disc(s) for format '{disc_type}'")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        created_isos = []
        base_clean_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in game_title).strip("_")

        for d in discs:
            num = d["disc_number"]
            t_dir = d["target_dir"]
            t_dir.mkdir(parents=True, exist_ok=True)

            for src_file in d["files"]:
                dst = t_dir / src_file.name
                if dst.exists():
                    dst.unlink()
                try:
                    os.link(src_file, dst)
                except OSError:
                    shutil.copy2(src_file, dst)

            create_autorun_inf(t_dir, game_title)
            vol_id = sanitize_volid(game_title, num, total_discs)

            if total_discs == 1:
                iso_path = OUTPUT_DIR / f"{base_clean_name}.iso"
            else:
                iso_path = OUTPUT_DIR / f"{base_clean_name}_Disc{num}.iso"

            await log_callback(f"[ISO] Building image: {iso_path.name} (Volume ID: {vol_id})")

            # Run xorriso
            xorriso_cmd = [
                "xorriso",
                "-as", "mkisofs",
                "-iso-level", "3",
                "-joliet",
                "-joliet-long",
                "-rational-rock",
                "-volid", vol_id,
                "-o", str(iso_path),
                str(t_dir)
            ]

            x_proc = await asyncio.create_subprocess_exec(
                *xorriso_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            while True:
                line = await x_proc.stdout.readline()
                if not line:
                    break
                t = line.decode("utf-8", errors="ignore").rstrip()
                if t:
                    await log_callback(f"[xorriso] {t}")

            await x_proc.wait()
            if x_proc.returncode != 0:
                raise RuntimeError(f"xorriso failed with code {x_proc.returncode}")

            created_isos.append(iso_path)

        # -------------------------------------------------------------
        # Stage 5: ISO Checksums & Ownership
        # -------------------------------------------------------------
        await progress_callback(90, "Computing ISO SHA-256 checksums & finalizing...")
        for iso in created_isos:
            await log_callback(f"[Checksum] Generating SHA-256 for {iso.name}...")
            # Compute hash
            from scripts.sanitize_and_hash import calculate_sha256
            sha = await loop.run_in_executor(None, calculate_sha256, iso)
            sha_file = iso.parent / f"{iso.name}.sha256"
            sha_file.write_text(f"{sha} *{iso.name}\n", encoding="utf-8")
            await log_callback(f"[Checksum] {iso.name}: {sha}")

        # Fix ownership
        try:
            if PUID and PGID:
                for iso in created_isos:
                    os.chown(iso, PUID, PGID)
                    sha_file = iso.parent / f"{iso.name}.sha256"
                    if sha_file.exists():
                        os.chown(sha_file, PUID, PGID)
        except Exception:
            pass

        await progress_callback(100, "Packaging complete!")
        await log_callback(f"[Pipeline] Successfully generated {len(created_isos)} ISO image(s) in {OUTPUT_DIR}")

        return {
            "game_title": game_title,
            "app_id": app_id,
            "output_isos": [str(iso.name) for iso in created_isos],
            "total_discs": total_discs,
        }

    finally:
        # Clean up temporary staging workspace
        shutil.rmtree(job_workspace, ignore_errors=True)
