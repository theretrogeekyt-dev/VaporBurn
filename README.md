# VaporBurn 💿🔥

[![Build & Publish Docker Image](https://github.com/theretrogeekyt-dev/VaporBurn/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/theretrogeekyt-dev/VaporBurn/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker)](https://github.com/theretrogeekyt-dev/VaporBurn/pkgs/container/vaporburn)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**VaporBurn** is the official Web UI packaging companion tool for [**VaporFetch**](https://github.com/theretrogeekyt-dev/VaporFetch). 

While VaporFetch automates downloading and backing up your Steam library with Goldberg emulation directly onto your NAS, **VaporBurn** provides a modern, dedicated Web UI to transform those raw game backups into **clean, ultra-compressed, professional-grade Windows `.iso` installers**.

Everything runs entirely inside a Docker container using Wine, Inno Setup 6, LZMA2 compression, and `xorriso`—designed from the ground up to match the visual identity, telemetry, and ease of use of VaporFetch.

---

## 🌟 Key Features

- 🌐 **Modern Web UI**: A sleek, dark-themed Single Page Application matching VaporFetch's exact styling (`#0b0f19` dark palette, Steam-blue accents, responsive cards, and real-time storage monitors).
- 🎮 **Automated Game Library Scanner**: Automatically scans your mounted `/input` folder for game backups, retrieves high-resolution banner artwork from the Steam CDN, and detects Goldberg status, existing save files, and redistributables.
- ⚡ **1-Click Packaging Wizard**: Configure disc format (`Single ISO`, `DVD-5`, `DVD-9`, `BD-25`), RAM limiter safety, player name, language, and Steam ID in an intuitive modal.
- 📊 **Real-Time Telemetry & SSE Terminal**: Live stage progression bars, percentage indicators, and a collapsible, color-coded live Wine & compiler terminal log stream powered by Server-Sent Events (SSE).
- 💿 **Completed ISOs Manager**: Direct in-browser ISO downloads, file size tracking, and 1-click SHA-256 checksum copy buttons.
- 🛡️ **Non-Destructive Sanitization**: Input game folders are mounted read-only (`:ro`). VaporBurn stages and strips bloat (`*.dmp`, GPU-specific shader caches, logs, `.downloading` chunks) without modifying your original backup share.
- 🎯 **Smart Executable Discovery**: Distinguishes actual game binaries (e.g. `Binaries/Win64/*-Win64-Shipping.exe`) from generic launchers (`launcher.exe`) and blacklists crash reporters (`CrashReportClient.exe`).
- 🗜️ **Ultra LZMA2 Compression & Slicing**: Compresses game data into chunked slices (e.g. 4GB `setup-1.bin`, `setup-2.bin`) for compatibility with FAT32 drives and large game sizes.
- 🧠 **Decompression Safety (RAM Limiter)**: Includes a "Limit installer RAM usage to 2GB" option in the installer GUI. Automatically pre-checked on PCs with $\le$ 8GB RAM to prevent Out-Of-Memory crashes during heavy LZMA2 extraction.
- 🕹️ **Goldberg Emulation GUI**: The installer presents custom wizard pages where users can configure their **Player Name**, **Language**, and **Steam ID64**. Automatically writes `force_account_name.txt`, `force_language.txt`, and `force_steamid.txt` to the appropriate `steam_settings` directories.
- 💾 **Save Game Handling**: Automatically detects Goldberg saves in the backup (`saves/` or `%APPDATA%\Goldberg SteamEmu Saves\<SteamID>\`) and provides a 1-click option in the installer to restore them to the user's profile.
- 📦 **Redistributables Detection**: Detects `_CommonRedist` or `Redistributables` folders and creates optional tasks in the installer to run DirectX and Visual C++ runtimes silently at the end of setup.
- 🔒 **Windows Firewall Exception**: Offers an optional checkbox to add a Windows Firewall exception for the game binary, essential for Goldberg LAN and Steam P2P multiplayer.
- 🔍 **SHA-256 Integrity Verification**: Generates a cryptographic manifest (`checksums.sha256`) of uncompressed files and bundles a 1-click post-install verifier (`verify_integrity.bat`) to ensure zero file corruption occurred.

---

## 🚀 Quick Setup with Docker Compose

1. Create a `vaporburn` directory and download `docker-compose.yml`:
   ```bash
   mkdir -p vaporburn && cd vaporburn
   curl -fsSL https://raw.githubusercontent.com/theretrogeekyt-dev/VaporBurn/main/docker-compose.yml -o docker-compose.yml
   ```

2. Edit `docker-compose.yml` to set your NAS storage paths:
   ```yaml
   services:
     vaporburn:
       image: ghcr.io/theretrogeekyt-dev/vaporburn:latest
       container_name: vaporburn
       restart: unless-stopped
       ports:
         - "8081:8081"                # Web UI accessible at http://<nas-ip>:8081
       environment:
         - PUID=1000                  # Your NAS user ID (id -u)
         - PGID=1000                  # Your NAS group ID (id -g)
         - UMASK=002                  # Ensures group-writable permissions
         - PORT=8081
       volumes:
         - /mnt/storage/games:/input:ro        # Path to your VaporFetch backups
         - /mnt/storage/installers:/output    # Target path for output ISO files
         - ./data:/app/data                   # App settings & job history
   ```

3. Launch the container:
   ```bash
   docker compose up -d
   ```

4. Open **`http://<nas-ip>:8081`** in your browser.

---

## 🐳 Single `docker run` Command

You can spin up VaporBurn with a single command without creating any configuration files:

```bash
docker run -d \
  --name vaporburn \
  --restart unless-stopped \
  -p 8081:8081 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e UMASK=002 \
  -v /mnt/storage/games:/input:ro \
  -v /mnt/storage/installers:/output \
  -v /mnt/storage/vaporburn-data:/app/data \
  ghcr.io/theretrogeekyt-dev/vaporburn:latest
```

---

## 🖥️ Web UI Walkthrough

### 1. Game Library Tab
Browse all downloaded Steam games located in `/input`. Each card displays:
- Official Steam header artwork
- Steam App ID
- Backup size on disk
- Goldberg emulator status & save file counts
- **"🔥 Package to ISO"** trigger button

### 2. Packaging Configuration Modal
Clicking "Package to ISO" opens the packaging wizard:
- **Disc Format**:
  - `Single ISO`: Packages all bins and `setup.exe` into a single mountable `.iso` (recommended for modern virtual drive mounting).
  - `DVD-5` (4.37 GB), `DVD-9` (7.95 GB), `BD-25` (23 GB): Automatically splits multi-part chunks across discs (`Game_Disc1.iso`, `Game_Disc2.iso`, etc.).
- **RAM Limiter Checkbox**: Sets up Inno Setup to cap decompression memory at 2GB (preventing out-of-memory errors on $\le$ 8GB RAM PCs).
- **Goldberg Profile Defaults**: Configure the default player username, language, and Steam ID.
- **Firewall Integration**: Enable automatic inbound/outbound Windows Firewall rules for LAN co-op.

### 3. Packaging Queue & Live Terminal
Monitor active packaging jobs in real time:
- **Live Progress Bar**: Displays stage progress (Sanitizing $\rightarrow$ Discovering $\rightarrow$ Compiling $\rightarrow$ Packaging $\rightarrow$ Checksumming).
- **Live Terminal Stream**: Watch Wine and Inno Setup compiler output streamed line-by-line via Server-Sent Events (SSE).
- **Job Abort**: Safely cancel a running packaging job at any time.

### 4. Completed ISOs Tab
Review and download all generated installers:
- Direct download link for each `.iso` file.
- Direct download link for `.iso.sha256` manifests.
- 1-click clipboard copy for SHA-256 hashes.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8081` | Web server listening port |
| `PUID` | `1000` | Host user ID for file ownership |
| `PGID` | `1000` | Host group ID for file ownership |
| `UMASK` | `002` | File creation mask |
| `INPUT_DIR` | `/input` | Mounted directory containing game backups |
| `OUTPUT_DIR` | `/output` | Mounted directory for generated ISO files |
| `DATA_DIR` | `/app/data` | Directory for persistent settings and job history |
| `CLI_MODE` | `false` | Set to `true` to run headless CLI pipeline instead of Web UI |

---

## 🖥️ Installing on Windows

1. Double-click the generated `.iso` file in Windows 10/11 (Windows mounts ISOs natively as a virtual DVD drive).
2. Run `setup.exe`.
3. Customize your installation:
   - **RAM Limiter**: Keep checked if installing on a PC with $\le$ 8GB RAM.
   - **Player Name & Language**: Input your custom gamer tag and language (written directly to Goldberg `steam_settings`).
   - **Redistributables**: Check DirectX or VC++ runtimes if needed.
   - **Firewall Rule**: Automatically configures Windows Defender Firewall for LAN/P2P co-op play.
4. Finish installation and click **Verify installed file integrity** to confirm bit-perfect installation against `checksums.sha256`.

---

## 🛠️ Building Locally

```bash
git clone https://github.com/theretrogeekyt-dev/VaporBurn.git
cd VaporBurn
docker build -t vaporburn:local .
```

---

## 🤝 Relationship to VaporFetch

- [**VaporFetch**](https://github.com/theretrogeekyt-dev/VaporFetch) (`http://<nas-ip>:8080`): Batch downloads Steam games directly on your NAS using SteamCMD and sets up offline Goldberg emulation.
- [**VaporBurn**](https://github.com/theretrogeekyt-dev/VaporBurn) (`http://<nas-ip>:8081`): Web UI that ingests those backups and packages them into self-contained, offline `.iso` installers.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
