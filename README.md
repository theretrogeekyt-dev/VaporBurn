# VaporBurn 💿🔥

[![Build & Publish Docker Image](https://github.com/theretrogeekyt-dev/VaporBurn/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/theretrogeekyt-dev/VaporBurn/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker)](https://github.com/theretrogeekyt-dev/VaporBurn/pkgs/container/vaporburn)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**VaporBurn** is the official packaging companion tool for [**VaporFetch**](https://github.com/theretrogeekyt-dev/VaporFetch). 

While VaporFetch automates downloading and backing up your Steam library with Goldberg emulation directly onto your NAS, **VaporBurn** transforms those raw game backups into **clean, ultra-compressed, professional-grade Windows `.iso` installers**.

Everything runs entirely inside a headless Docker container using Wine, Inno Setup 6, LZMA2 compression, and `xorriso`—delivering the ease of repacker-grade installers without requiring a Windows machine.

---

## 🌟 Key Features

- 🐳 **100% Containerized Pipeline**: Zero host dependencies. Runs headlessly on any Linux server, NAS (Unraid, Synology, TrueNAS), or local Docker host.
- 🛡️ **Non-Destructive Sanitization**: Input game folders are treated strictly read-only. Strips unnecessary bloat (crash dumps `.dmp`, GPU-specific shader caches, logs, temporary download chunks) during staging without modifying your source backup.
- 🎯 **Smart Executable Discovery**: Intelligently pinpoints the real game binary (e.g. `Binaries/Win64/Game-Win64-Shipping.exe`) versus generic launcher stubs (`launcher.exe`), ensuring start menu and desktop shortcuts launch the actual game.
- 🗜️ **Ultra LZMA2 Compression & Slicing**: Compresses game data into chunked slices (e.g. 4GB `setup-1.bin`, `setup-2.bin`) for compatibility with FAT32 drives and large game sizes.
- 🧠 **Decompression Safety (RAM Limiter)**: Includes a "Limit installer RAM usage to 2GB" option in the installer GUI. Automatically pre-checked on PCs with $\le$ 8GB RAM to prevent Out-Of-Memory crashes during heavy LZMA2 extraction.
- 🕹️ **Goldberg Emulation GUI**: The installer presents custom wizard pages where users can configure their **Player Name**, **Language**, and **Steam ID64**. Automatically writes `force_account_name.txt`, `force_language.txt`, and `force_steamid.txt` to the appropriate `steam_settings` directories.
- 💾 **Save Game Handling**: Automatically detects Goldberg saves in the backup (`saves/` or `%APPDATA%\Goldberg SteamEmu Saves\<SteamID>\`) and provides a 1-click option in the installer to restore them to the user's profile.
- 📦 **Redistributables Detection**: Detects `_CommonRedist` or `Redistributables` folders and creates optional tasks in the installer to run DirectX and Visual C++ runtimes silently at the end of setup.
- 🌐 **Windows Firewall Exception**: Offers an optional checkbox to add a Windows Firewall exception for the game binary, essential for Goldberg LAN and Steam P2P multiplayer.
- 🔍 **SHA-256 Integrity Verification**: Generates a cryptographic manifest (`checksums.sha256`) of uncompressed files and bundles a 1-click post-install verifier (`verify_integrity.bat`) to ensure zero file corruption occurred.
- 💿 **Mountable ISO Generation**: Generates clean, mountable ISOs (Rock Ridge + Joliet + UDF) with `autorun.inf`. Supports **Single ISO** (default) or **Multi-Disc Spanning** (`DVD5`, `DVD9`, `BD25`, or custom sizes).

---

## 🏗️ Architecture Overview

```
                          ┌─────────────────────────────┐
                          │   VaporFetch Game Backup    │
                          │        (/input:ro)          │
                          └──────────────┬──────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
      ┌─────────────────────────┐                 ┌─────────────────────────┐
      │  Sanitization & Filter  │                 │   Smart Discovery       │
      │  - Exclude *.dmp        │                 │   - Find Main .exe      │
      │  - Exclude shader cache │                 │   - Detect Goldberg DLLs│
      │  - Exclude logs & temp  │                 │   - Detect Redists      │
      │  - Compute SHA-256      │                 │   - Detect Saves        │
      └────────────┬────────────┘                 └────────────┬────────────┘
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │ Inno Setup Compiler (ISCC)  │
                          │       via Headless Wine     │
                          │   - LZMA2 Ultra Compression │
                          │   - 4GB Chunked .bin Slices │
                          │   - Custom Pascal Script GUI│
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │ Output Staging              │
                          │   - setup.exe               │
                          │   - setup-1.bin, etc.       │
                          │   - checksums.sha256        │
                          │   - autorun.inf             │
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │ ISO Packaging (xorriso)     │
                          │   - Single ISO or Multi-Disc│
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │     Output Directory        │
                          │        (/output)            │
                          │   - GameName.iso            │
                          │   - GameName.iso.sha256     │
                          └─────────────────────────────┘
```

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

1. Clone or download `docker-compose.yml`:
   ```bash
   git clone https://github.com/theretrogeekyt-dev/VaporBurn.git
   cd VaporBurn
   ```

2. Edit `docker-compose.yml` to point to your input game folder and output destination:
   ```yaml
   services:
     vaporburn:
       image: ghcr.io/theretrogeekyt-dev/vaporburn:latest
       container_name: vaporburn
       environment:
         - PUID=1000
         - PGID=1000
         - UMASK=002
         - DISC_TYPE=single    # single, dvd5, dvd9, bd25, or custom
       volumes:
         - /mnt/storage/games/Cyberpunk2077:/input:ro
         - /mnt/storage/installers:/output
   ```

3. Run the container:
   ```bash
   docker compose run --rm vaporburn
   ```

---

### Option 2: Single `docker run` Command

You can package any game folder on-demand with a single command:

```bash
docker run --rm -it \
  -e PUID=$(id -u) \
  -e PGID=$(id -g) \
  -v "/path/to/VaporFetch/Game:/input:ro" \
  -v "/path/to/output/iso:/output" \
  ghcr.io/theretrogeekyt-dev/vaporburn:latest
```

---

## ⚙️ Configuration Reference

All settings can be customized via environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PUID` | `1000` | Host user ID for file ownership |
| `PGID` | `1000` | Host group ID for file ownership |
| `UMASK` | `002` | File creation mask |
| `DISC_TYPE` | `single` | Disc sizing mode: `single`, `dvd5` (4.37GB), `dvd9` (7.95GB), `bd25` (23GB), `bd50` (46GB), or `custom` |
| `DISC_SIZE_MB` | `0` | Capacity per disc in MB (used when `DISC_TYPE=custom`) |
| `CHUNK_SIZE` | `4294967295` | Maximum size of each `.bin` slice in bytes (~4GB for FAT32 compatibility) |
| `GAME_TITLE` | *(Auto-detected)* | Custom game title override for shortcuts and ISO label |
| `APP_ID` | *(Auto-detected)* | Steam App ID override (defaults to `steam_appid.txt` or `480`) |
| `MAIN_EXE` | *(Auto-detected)* | Relative path to primary game executable (e.g. `Binaries/Win64/Game-Win64-Shipping.exe`) |
| `GAME_SUBDIR` | *(Empty)* | Process a specific subdirectory if `/input` is a multi-game parent directory |

---

## 💿 Multi-Disc Spanning

For massive games, you can split the installer across multiple DVD or Blu-ray discs:

```bash
docker run --rm -it \
  -e DISC_TYPE=dvd9 \
  -v "/storage/games/HugeGame:/input:ro" \
  -v "/storage/iso:/output" \
  ghcr.io/theretrogeekyt-dev/vaporburn:latest
```

This will automatically create:
- `HugeGame_Disc1.iso` (contains `setup.exe`, `checksums.sha256`, `autorun.inf`, `setup-1.bin`)
- `HugeGame_Disc2.iso` (contains `setup-2.bin`, `setup-3.bin`)
- `HugeGame_Disc3.iso` ...

When installing on Windows, Inno Setup will cleanly pause when Disc 1 finishes and prompt:
*"Please insert Disc 2..."*. Simply mount `HugeGame_Disc2.iso` in Windows and click OK.

---

## 🖥️ Installing on Windows

1. Double-click the generated `.iso` file in Windows 10/11 (Windows mounts ISOs natively as a virtual DVD drive).
2. Run `setup.exe`.
3. Customize your installation:
   - **RAM Limiter**: Keep checked if installing on a PC with $\le$ 8GB RAM to ensure smooth, crash-free LZMA2 decompression.
   - **Player Name & Language**: Input your custom gamer tag and language (written directly to Goldberg `steam_settings`).
   - **Redistributables**: Check DirectX or VC++ runtimes if needed.
   - **Firewall Rule**: Automatically configures Windows Defender Firewall for LAN/P2P co-op play.
4. Finish installation and click **Verify installed file integrity** to confirm bit-perfect installation.

---

## 🛠️ Building the Docker Image Locally

```bash
git clone https://github.com/theretrogeekyt-dev/VaporBurn.git
cd VaporBurn
docker build -t vaporburn:local .
```

---

## 🤝 Relationship to VaporFetch

- [**VaporFetch**](https://github.com/theretrogeekyt-dev/VaporFetch): Batch downloads Steam games directly on your NAS using SteamCMD and sets up offline Goldberg emulation.
- [**VaporBurn**](https://github.com/theretrogeekyt-dev/VaporBurn): Ingests those downloads and packages them into self-contained, offline `.iso` installers.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
