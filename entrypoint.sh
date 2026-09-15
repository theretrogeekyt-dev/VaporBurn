#!/usr/bin/env bash
# ==============================================================================
# VaporBurn - Automated ISO Installer Packaging Engine
# Entrypoint Pipeline Script
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

# ------------------------------------------------------------------------------
# 1. Environment & Path Initialization
# ------------------------------------------------------------------------------
PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-002}

INPUT_DIR=${INPUT_DIR:-"/input"}
OUTPUT_DIR=${OUTPUT_DIR:-"/output"}
WORKSPACE_DIR=${WORKSPACE_DIR:-"/workspace"}

DISC_TYPE=${DISC_TYPE:-"single"}
DISC_SIZE_MB=${DISC_SIZE_MB:-0}
CHUNK_SIZE=${CHUNK_SIZE:-"4294967295"} # 4GB FAT32 slice limit
COMPRESSION=${COMPRESSION:-"lzma2/ultra64"}

export WINEPREFIX="/tmp/wine"
export WINEDEBUG="-all"

umask "$UMASK"

# ------------------------------------------------------------------------------
# 2. Pre-flight Validation
# ------------------------------------------------------------------------------
print_banner

log_info "Initializing container environment (PUID=${PUID}, PGID=${PGID}, UMASK=${UMASK})..."

if [ ! -d "$INPUT_DIR" ]; then
    log_error "Input directory '$INPUT_DIR' does not exist! Please mount your game backup directory to /input."
    exit 1
fi

mkdir -p "$OUTPUT_DIR" "$WORKSPACE_DIR"

# Check if input directory is empty
if [ -z "$(ls -A "$INPUT_DIR" 2>/dev/null)" ]; then
    log_error "Input directory '$INPUT_DIR' is empty! Mount a game backup folder created by VaporFetch."
    exit 1
fi

# Detect whether /input is a single game directory or a collection folder
# If /input contains game files directly (e.g. .exe or directories), treat /input as the game.
# If /input contains multiple subdirectories and SUBDIR_MODE is specified, allow batching.
TARGET_GAME_DIR="$INPUT_DIR"

if [ -n "$GAME_SUBDIR" ]; then
    TARGET_GAME_DIR="$INPUT_DIR/$GAME_SUBDIR"
    if [ ! -d "$TARGET_GAME_DIR" ]; then
        log_error "Specified GAME_SUBDIR '$GAME_SUBDIR' not found in $INPUT_DIR!"
        exit 1
    fi
fi

log_info "Source Game Directory: ${TARGET_GAME_DIR}"
log_info "Target Output Directory: ${OUTPUT_DIR}"

# ------------------------------------------------------------------------------
# 3. Step 1: Executable & Metadata Discovery
# ------------------------------------------------------------------------------
log_step "Step 1: Smart Executable & Game Metadata Discovery"

DISCOVERY_JSON="$WORKSPACE_DIR/discovery.json"
DISCOVERY_ARGS=(
    "--game-dir" "$TARGET_GAME_DIR"
    "--output-json" "$DISCOVERY_JSON"
)

if [ -n "$GAME_TITLE" ]; then
    DISCOVERY_ARGS+=("--game-title" "$GAME_TITLE")
fi
if [ -n "$APP_ID" ]; then
    DISCOVERY_ARGS+=("--app-id" "$APP_ID")
fi
if [ -n "$MAIN_EXE" ]; then
    DISCOVERY_ARGS+=("--main-exe" "$MAIN_EXE")
fi

python3 /app/scripts/discover_exe.py "${DISCOVERY_ARGS[@]}"

# Extract discovery outputs using Python
DETECTED_TITLE=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(data.get('game_title', 'Game'))")
DETECTED_APP_ID=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(data.get('app_id', '480'))")
DETECTED_EXE_REL=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); exe=data.get('primary_exe'); print(exe.get('rel_path', 'Game.exe') if exe else 'Game.exe')")
DETECTED_EXE_DIR=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); exe=data.get('primary_exe'); print(exe.get('rel_dir', '') if exe else '')")

HAS_DX=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print('1' if any(r['id']=='directx' for r in data.get('redistributables', [])) else '0')")
DX_EXE=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(next((r['exe_rel'] for r in data.get('redistributables', []) if r['id']=='directx'), ''))")

HAS_VC64=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print('1' if any(r['id']=='vcredist_x64' for r in data.get('redistributables', [])) else '0')")
VC64_EXE=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(next((r['exe_rel'] for r in data.get('redistributables', []) if r['id']=='vcredist_x64'), ''))")

HAS_VC86=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print('1' if any(r['id']=='vcredist_x86' for r in data.get('redistributables', [])) else '0')")
VC86_EXE=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(next((r['exe_rel'] for r in data.get('redistributables', []) if r['id']=='vcredist_x86'), ''))")

HAS_SAVES=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print('1' if data.get('saves', {}).get('has_saves') else '0')")
SAVES_REL_DIR=$(python3 -c "import json; data=json.load(open('$DISCOVERY_JSON')); print(data.get('saves', {}).get('save_dir_rel', '').replace('/', '\\\\'))")

log_success "Discovered: '${DETECTED_TITLE}' (Steam AppID: ${DETECTED_APP_ID})"
log_success "Primary Binary: '${DETECTED_EXE_REL}'"

# ------------------------------------------------------------------------------
# 4. Step 2: Sanitization & Pre-Hashing
# ------------------------------------------------------------------------------
log_step "Step 2: Asset Sanitization & SHA-256 Checksum Generation"

STAGING_DIR="$WORKSPACE_DIR/staging"
STATS_JSON="$WORKSPACE_DIR/stats.json"
MANIFEST_FILE="$STAGING_DIR/checksums.sha256"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

python3 /app/scripts/sanitize_and_hash.py \
    --source-dir "$TARGET_GAME_DIR" \
    --stage-dir "$STAGING_DIR" \
    --manifest-out "$MANIFEST_FILE" \
    --stats-json "$STATS_JSON"

TOTAL_MB=$(python3 -c "import json; data=json.load(open('$STATS_JSON')); print(data.get('total_mb_kept', 0))")
STRIPPED_MB=$(python3 -c "import json; data=json.load(open('$STATS_JSON')); print(data.get('total_mb_excluded', 0))")
log_success "Sanitized game payload: ${TOTAL_MB} MB (Stripped ${STRIPPED_MB} MB bloat/temp files)"

# ------------------------------------------------------------------------------
# 5. Step 3: Inno Setup Compilation via Wine
# ------------------------------------------------------------------------------
log_step "Step 3: Compiling Inno Setup Windows Installer via Wine"

BUILD_OUT_DIR="$WORKSPACE_DIR/installer_build"
rm -rf "$BUILD_OUT_DIR"
mkdir -p "$BUILD_OUT_DIR"

# Initialize wine if needed
if [ ! -d "$WINEPREFIX" ]; then
    log_info "Initializing Wine environment..."
    wineboot --init > /dev/null 2>&1 || true
fi

# Convert paths to Windows paths for Inno Setup compiler
WIN_SOURCE_DIR=$(winepath -w "$STAGING_DIR")
WIN_OUTPUT_DIR=$(winepath -w "$BUILD_OUT_DIR")

ISCC_DEFINES=(
    "/DGameName=${DETECTED_TITLE}"
    "/DAppExe=${DETECTED_EXE_REL}"
    "/DAppExeDir=${DETECTED_EXE_DIR}"
    "/DAppId=${DETECTED_APP_ID}"
    "/DSourceDir=${WIN_SOURCE_DIR}"
    "/DOutputDir=${WIN_OUTPUT_DIR}"
    "/DOutputBaseName=setup"
    "/DChunkSize=${CHUNK_SIZE}"
    "/DHasDirectX=${HAS_DX}"
    "/DDirectXExe=${DX_EXE}"
    "/DHasVCRedist64=${HAS_VC64}"
    "/DVCRedist64Exe=${VC64_EXE}"
    "/DHasVCRedist86=${HAS_VC86}"
    "/DVCRedist86Exe=${VC86_EXE}"
    "/DHasSaves=${HAS_SAVES}"
    "/DSavesRelDir=${SAVES_REL_DIR}"
)

log_info "Invoking Inno Setup Compiler (ISCC)..."
wine /opt/innosetup/app/ISCC.exe "${ISCC_DEFINES[@]}" /app/installer_template.iss

if [ ! -f "$BUILD_OUT_DIR/setup.exe" ]; then
    log_error "Inno Setup compilation failed! setup.exe was not created."
    exit 1
fi

log_success "Compiled installer successfully:"
ls -lh "$BUILD_OUT_DIR"

# ------------------------------------------------------------------------------
# 6. Step 4: ISO Image Creation
# ------------------------------------------------------------------------------
log_step "Step 4: ISO Image Creation (Mode: ${DISC_TYPE})"

python3 /app/scripts/iso_packager.py \
    --installer-dir "$BUILD_OUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --game-title "$DETECTED_TITLE" \
    --disc-type "$DISC_TYPE" \
    --disc-size-mb "$DISC_SIZE_MB" \
    --work-dir "$WORKSPACE_DIR/iso_work"

# Generate SHA-256 for all produced ISO images
cd "$OUTPUT_DIR"
for iso in *.iso; do
    if [ -f "$iso" ]; then
        log_info "Computing integrity hash for ${iso}..."
        sha256sum "$iso" > "${iso}.sha256"
    fi
done

# ------------------------------------------------------------------------------
# 7. Step 5: Fix Permissions & Final Summary
# ------------------------------------------------------------------------------
log_step "Step 5: Finalizing & Adjusting Output Permissions"

if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    log_info "Setting ownership of output files to ${PUID}:${PGID}..."
    chown -R "${PUID}:${PGID}" "$OUTPUT_DIR" || true
    chmod -R 775 "$OUTPUT_DIR" || true
fi

# Clean up temporary build workspace
rm -rf "$WORKSPACE_DIR"

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}${BOLD}✔ VaporBurn ISO Packaging Completed Successfully!${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "Game:         ${BOLD}${DETECTED_TITLE}${NC} (AppID: ${DETECTED_APP_ID})"
echo -e "Executable:   ${DETECTED_EXE_REL}"
echo -e "Output Path:  ${OUTPUT_DIR}"
echo -e "Generated Artifacts:"
ls -lh "$OUTPUT_DIR"
echo -e "\nYou can now mount or burn the generated .iso file(s) and run setup.exe on Windows!\n"
