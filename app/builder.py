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


def to_wine_path(posix_path: Path) -> str:
    """
    Converts a POSIX path to a Wine Windows path (Z:\\...).
    Wine maps the root filesystem / to Z:\\.
    """
    p_str = str(posix_path.resolve())
    try:
        res = subprocess.run(
            ["winepath", "-w", p_str],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            env={**os.environ, "WINEPREFIX": os.environ.get("WINEPREFIX", "/tmp/wine"), "WINEDEBUG": "-all"}
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # Reliable canonical fallback: Wine maps / to Z:\
    clean_path = p_str.replace("/", "\\").lstrip("\\")
    return f"Z:\\{clean_path}"


def generate_iss_script(target_iss_path: Path, template_path: Path, config: Dict[str, Any]) -> str:
    """
    Generates a dedicated, fully-defined Inno Setup script with properly typed and quoted
    preprocessor directives. Prepending explicit defines avoids Wine CLI parameter
    quoting/splitting bugs and ISPP type mismatch errors.
    """
    template_content = template_path.read_text(encoding="utf-8", errors="ignore")

    def esc(val: Any) -> str:
        return str(val).replace('"', '""')

    defines_header = f"""; ==============================================================================
; VaporBurn - Auto-generated Inno Setup Compilation Script
; Target: {esc(config.get("GameName", "Game"))}
; ==============================================================================

#define GameName "{esc(config.get('GameName', 'Game'))}"
#define AppVersion "{esc(config.get('AppVersion', '1.0'))}"
#define AppPublisher "{esc(config.get('AppPublisher', 'VaporFetch / VaporBurn'))}"
#define AppExe "{esc(config.get('AppExe', 'Game.exe'))}"
#define AppExeDir "{esc(config.get('AppExeDir', ''))}"
#define AppId "{esc(config.get('AppId', '480'))}"
#define SourceDir "{esc(config.get('SourceDir', 'staging'))}"
#define OutputDir "{esc(config.get('OutputDir', 'output'))}"
#define OutputBaseName "{esc(config.get('OutputBaseName', 'setup'))}"
#define ChunkSize "{esc(config.get('ChunkSize', '4294967295'))}"
#define HasDirectX {1 if config.get('HasDirectX') else 0}
#define DirectXExe "{esc(config.get('DirectXExe', ''))}"
#define HasVCRedist64 {1 if config.get('HasVCRedist64') else 0}
#define VCRedist64Exe "{esc(config.get('VCRedist64Exe', ''))}"
#define HasVCRedist86 {1 if config.get('HasVCRedist86') else 0}
#define VCRedist86Exe "{esc(config.get('VCRedist86Exe', ''))}"
#define HasSaves {1 if config.get('HasSaves') else 0}
#define SavesRelDir "{esc(config.get('SavesRelDir', ''))}"

"""
    full_script = defines_header + template_content
    target_iss_path.parent.mkdir(parents=True, exist_ok=True)
    target_iss_path.write_text(full_script, encoding="utf-8")
    return full_script


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
        if primary_exe_override:
            norm_exe = primary_exe_override.replace("\\", "/").strip("/")
            custom_exe = game_path / norm_exe
            if custom_exe.exists():
                rel_dir = str(custom_exe.parent.relative_to(game_path)).replace("/", "\\")
                primary_exe = {
                    "rel_path": str(custom_exe.relative_to(game_path)).replace("/", "\\"),
                    "name": custom_exe.name,
                    "rel_dir": "" if rel_dir == "." else rel_dir
                }
            else:
                primary_exe = discover_primary_executable(game_path, folder_name)
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
        await log_callback("[InnoSetup] Generating tailored installer configuration script...")

        # Translate POSIX staging and build output to Wine Windows paths
        win_staging = to_wine_path(staging_dir)
        win_build_out = to_wine_path(build_out_dir)

        chunk_size = str(params.get("chunk_size", 4294967295))
        iss_file = job_workspace / "installer.iss"
        generate_iss_script(
            target_iss_path=iss_file,
            template_path=TEMPLATE_ISS,
            config={
                "GameName": game_title,
                "AppVersion": "1.0",
                "AppPublisher": "VaporFetch / VaporBurn",
                "AppExe": primary_exe["rel_path"],
                "AppExeDir": primary_exe["rel_dir"],
                "AppId": app_id,
                "SourceDir": win_staging,
                "OutputDir": win_build_out,
                "OutputBaseName": "setup",
                "ChunkSize": chunk_size,
                "HasDirectX": has_dx == "1",
                "DirectXExe": dx_exe,
                "HasVCRedist64": has_vc64 == "1",
                "VCRedist64Exe": vc64_exe,
                "HasVCRedist86": has_vc86 == "1",
                "VCRedist86Exe": vc86_exe,
                "HasSaves": has_saves == "1",
                "SavesRelDir": saves_rel,
            }
        )

        win_iss = to_wine_path(iss_file)
        iscc_cmd = [
            "wine",
            "/opt/innosetup/app/ISCC.exe",
            win_iss
        ]

        await log_callback(f"[InnoSetup] Invoking ISCC: {' '.join(iscc_cmd)}")

        wine_prefix = os.environ.get("WINEPREFIX", "/tmp/wine")
        proc = await asyncio.create_subprocess_exec(
            *iscc_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "WINEDEBUG": "-all", "WINEPREFIX": wine_prefix}
        )

        iscc_output_lines = []
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
                iscc_output_lines.append(text)
                await log_callback(f"[ISCC] {text}")
                # Parse progress markers from ISCC output
                if "Compressing" in text:
                    await progress_callback(55, text[:60])

        await proc.wait()
        if proc.returncode != 0:
            error_lines = [
                l for l in iscc_output_lines 
                if any(k in l.lower() for k in ["error", "fatal", "failed", "line "])
            ]
            if not error_lines:
                error_lines = iscc_output_lines[-10:]
            error_summary = "\n".join(error_lines[-5:]) if error_lines else f"Exit code {proc.returncode}"
            raise RuntimeError(f"Inno Setup compilation failed with exit code {proc.returncode}:\n{error_summary}")

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

