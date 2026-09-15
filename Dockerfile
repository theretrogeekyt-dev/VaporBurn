FROM debian:bookworm-slim

# Prevent interactive debconf prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    WINEDEBUG=-all \
    WINEPREFIX=/tmp/wine \
    PUID=1000 \
    PGID=1000 \
    UMASK=002 \
    INPUT_DIR=/input \
    OUTPUT_DIR=/output \
    WORKSPACE_DIR=/workspace

# Install system dependencies, Wine (32 & 64-bit), xorriso, 7-zip, Python, and utilities
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        gnupg2 \
        xorriso \
        p7zip-full \
        wine \
        wine32 \
        wine64 \
        libwine \
        innoextract \
        python3 \
        gosu \
        dos2unix \
        rsync \
    && rm -rf /var/lib/apt/lists/*

# Install Inno Setup 6.3.3 via innoextract (using official GitHub release with mirror fallback)
ARG INNOSETUP_URL="https://github.com/jrsoftware/issrc/releases/download/is-6_3_3/innosetup-6.3.3.exe"
RUN mkdir -p /opt/innosetup \
    && (curl -fsSL "${INNOSETUP_URL}" -o /tmp/innosetup.exe \
        || curl -fsSL "https://github.com/jrsoftware/issrc/releases/download/is-6_2_2/innosetup-6.2.2.exe" -o /tmp/innosetup.exe) \
    && innoextract -d /opt/innosetup /tmp/innosetup.exe \
    && rm -f /tmp/innosetup.exe

# Pre-initialize Wine prefix to avoid runtime initialization overhead
RUN WINEDEBUG=-all wineboot --init || true

# Setup working directories
WORKDIR /app
RUN mkdir -p /input /output /workspace /app/scripts

# Copy pipeline scripts, Inno Setup template, and entrypoint
COPY scripts/ /app/scripts/
COPY installer_template.iss /app/installer_template.iss
COPY entrypoint.sh /app/entrypoint.sh

# Convert line endings & configure execution permissions
RUN dos2unix /app/entrypoint.sh /app/installer_template.iss /app/scripts/*.py \
    && chmod +x /app/entrypoint.sh /app/scripts/*.py

# Volume Mountpoints
VOLUME ["/input", "/output"]

ENTRYPOINT ["/app/entrypoint.sh"]

