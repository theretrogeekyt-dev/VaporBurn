FROM debian:bookworm-slim

# Prevent interactive debconf prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    WINEDEBUG=-all \
    WINEPREFIX=/tmp/wine \
    PUID=1000 \
    PGID=1000 \
    UMASK=002 \
    PORT=8081 \
    INPUT_DIR=/input \
    OUTPUT_DIR=/output \
    DATA_DIR=/app/data \
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
        python3-pip \
        python3-venv \
        gosu \
        dos2unix \
        rsync \
    && rm -rf /var/lib/apt/lists/*

# Install Inno Setup 6.2.2 via innoextract (fully supported by innoextract 1.9)
ARG INNOSETUP_URL="https://github.com/jrsoftware/issrc/releases/download/is-6_2_2/innosetup-6.2.2.exe"
RUN mkdir -p /opt/innosetup \
    && curl -fsSL "${INNOSETUP_URL}" -o /tmp/innosetup.exe \
    && innoextract -d /opt/innosetup /tmp/innosetup.exe \
    && rm -f /tmp/innosetup.exe

# Pre-initialize Wine prefix to avoid runtime initialization overhead
RUN WINEDEBUG=-all wineboot --init || true

# Setup working directories
WORKDIR /app
RUN mkdir -p /input /output /workspace /app/data /app/scripts /app/static

# Install Python requirements
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Copy application backend, frontend static assets, pipeline scripts, template, and entrypoint
COPY app/ /app/app/
COPY scripts/ /app/scripts/
COPY installer_template.iss /app/installer_template.iss
COPY entrypoint.sh /app/entrypoint.sh

# Convert line endings & configure execution permissions
RUN dos2unix /app/entrypoint.sh /app/installer_template.iss /app/scripts/*.py \
    && chmod +x /app/entrypoint.sh /app/scripts/*.py

# Web UI Port
EXPOSE 8081

# Volume Mountpoints
VOLUME ["/input", "/output", "/app/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
