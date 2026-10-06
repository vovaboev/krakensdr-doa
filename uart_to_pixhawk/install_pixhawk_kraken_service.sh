#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-pixhawk-kraken-bridge.service}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"

# === ВАШИ ПУТИ/ПОЛЬЗОВАТЕЛЬ ===
APP_USER="${APP_USER:-admin}"
APP_GROUP="${APP_GROUP:-admin}"
WORKDIR="${WORKDIR:-/home/admin/krakensdr/uart_to_pixhawk}"
SCRIPT_PATH="${SCRIPT_PATH:-$WORKDIR/pixhawk_kraken_bridge.py}"

# base conda (miniforge/miniconda). Можно переопределить: CONDA_BASE=/opt/conda sudo ./install.sh
CONDA_BASE="${CONDA_BASE:-$(conda info --base 2>/dev/null || echo /home/admin/miniforge3)}"

# Параметры приложения
KRAKEN_HOST="${KRAKEN_HOST:-127.0.0.1}"
KRAKEN_PORT="${KRAKEN_PORT:-5005}"
PIXHAWK_UART="${PIXHAWK_UART:-/dev/serial0}"
PIXHAWK_BAUD="${PIXHAWK_BAUD:-115200}"
DF_OUT_RATE_HZ="${DF_OUT_RATE_HZ:-10}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

install -d -m 0755 /etc/systemd/system

cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Pixhawk <-> Kraken DOA Bridge (binary V2)
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${WORKDIR}
Environment=PYTHONUNBUFFERED=1
Environment=KRAKEN_HOST=${KRAKEN_HOST}
Environment=KRAKEN_PORT=${KRAKEN_PORT}
Environment=PIXHAWK_UART=${PIXHAWK_UART}
Environment=PIXHAWK_BAUD=${PIXHAWK_BAUD}
Environment=DF_OUT_RATE_HZ=${DF_OUT_RATE_HZ}
Environment=LOG_LEVEL=${LOG_LEVEL}
ExecStart=/bin/bash -lc 'source "${CONDA_BASE}/etc/profile.d/conda.sh"; conda activate kraken; exec python "${SCRIPT_PATH}"'
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chown root:root "$UNIT_PATH"
chmod 0644 "$UNIT_PATH"

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo "Создано: $UNIT_PATH"
systemctl --no-pager --full status "${SERVICE_NAME}" || true