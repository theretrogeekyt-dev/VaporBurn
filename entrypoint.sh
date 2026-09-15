#!/usr/bin/env bash
# ==============================================================================
# VaporBurn - Automated ISO Installer Packaging Engine
# Web UI Server & CLI Pipeline Orchestrator
# ==============================================================================

set -eo pipefail

# Colorful log output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

log_info()    { echo -e "${CYAN}[VaporBurn]${NC} $1"; }
log_success() { echo -e "${GREEN}[VaporBurn] ✔${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[VaporBurn] ⚠${NC} $1"; }
log_error()   { echo -e "${RED}[VaporBurn] ✖ ERROR:${NC} $1" >&2; }
log_step()    { echo -e "\n${BOLD}${PURPLE}==> $1${NC}"; }

print_banner() {
    cat << "EOF"
 __     __                       ____                 
 \ \   / /_ _ _ __   ___  _ __  | __ ) _   _ _ __ _ __  
  \ \ / / _` | '_ \ / _ \| '__| |  _ \| | | | '__| '_ \ 
   \ V / (_| | |_) | (_) | |    | |_) | |_| | |  | | | |
    \_/ \__,_| .__/ \___/|_|    |____/ \__,_|_|  |_| |_|
             |_|                                        
  Automated VaporFetch -> ISO Windows Installer Engine
EOF
    echo -e "${BLUE}======================================================${NC}\n"
}

PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-002}
PORT=${PORT:-8081}

INPUT_DIR=${INPUT_DIR:-"/input"}
OUTPUT_DIR=${OUTPUT_DIR:-"/output"}
WORKSPACE_DIR=${WORKSPACE_DIR:-"/workspace"}
DATA_DIR=${DATA_DIR:-"/app/data"}

export WINEPREFIX="/tmp/wine"
export WINEDEBUG="-all"

umask "$UMASK"

print_banner

log_info "Initializing environment (PUID=${PUID}, PGID=${PGID}, UMASK=${UMASK})..."

# Ensure directories exist
mkdir -p "$OUTPUT_DIR" "$WORKSPACE_DIR" "$DATA_DIR" "$WINEPREFIX"

# Adjust directory permissions so non-root Wine & Uvicorn can write
if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    chown -R "${PUID}:${PGID}" "$DATA_DIR" "$OUTPUT_DIR" "$WORKSPACE_DIR" "$WINEPREFIX" 2>/dev/null || true
fi

# Pre-initialize Wine prefix if not already created
if [ ! -d "$WINEPREFIX/drive_c" ]; then
    log_info "Initializing headless Wine environment..."
    wineboot --init > /dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# Mode Selection: CLI Batch Mode vs Web UI Server Mode
# ------------------------------------------------------------------------------
if [ "$1" = "cli" ] || [ "$CLI_MODE" = "true" ]; then
    log_step "Running in Headless CLI Mode"

    if [ ! -d "$INPUT_DIR" ]; then
        log_error "Input directory '$INPUT_DIR' does not exist!"
        exit 1
    fi

    # Execute Python CLI discovery and runner
    python3 /app/scripts/discover_exe.py --game-dir "$INPUT_DIR" --output-json "$WORKSPACE_DIR/cli_discovery.json"
    python3 -c "
import asyncio
from pathlib import Path
from app.builder import run_packaging_pipeline

async def cli_runner():
    async def log_cb(x): print(x)
    async def prog_cb(p, s): print(f'[{p}%] {s}')
    await run_packaging_pipeline(
        job_id='cli',
        game_path=Path('${INPUT_DIR}'),
        params={'disc_type': '${DISC_TYPE:-single}', 'game_title': '${GAME_TITLE:-}'},
        log_callback=log_cb,
        progress_callback=prog_cb,
        is_cancelled=lambda: False
    )

asyncio.run(cli_runner())
"
    log_success "CLI Packaging completed!"
    exit 0
fi

# Default: Start FastAPI Web Server
log_step "Starting VaporBurn Web UI Server on port ${PORT}"
log_info "Web UI accessible at: http://0.0.0.0:${PORT}"
log_info "Input game share:     ${INPUT_DIR}"
log_info "Output ISO share:     ${OUTPUT_DIR}"

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
