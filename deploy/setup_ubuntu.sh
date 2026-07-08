#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/gold-signal"
SERVICE_NAME="gold-signal"
DOMAIN="${1:-}"

if [[ -z "${DOMAIN}" ]]; then
  echo "Usage: bash deploy/setup_ubuntu.sh <your-domain.example.com>"
  exit 1
fi

if [[ ! -f "requirements.txt" || ! -f "run_app.py" ]]; then
  echo "Run this script from the project root directory."
  exit 1
fi

echo "[1/8] Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git certbot python3-certbot-nginx

echo "[2/8] Syncing project to ${APP_DIR}..."
sudo mkdir -p "${APP_DIR}"
sudo rsync -a --delete --exclude ".git" --exclude ".venv" ./ "${APP_DIR}/"

echo "[3/8] Creating virtual environment..."
sudo python3 -m venv "${APP_DIR}/.venv"
sudo "${APP_DIR}/.venv/bin/pip" install --upgrade pip
sudo "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "[4/8] Preparing environment file..."
if [[ ! -f "${APP_DIR}/.env" ]]; then
  sudo cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from template. Edit it with your real API keys before going live."
fi

echo "[5/8] Installing systemd service..."
sudo sed \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${APP_DIR}|" \
  -e "s|^EnvironmentFile=.*|EnvironmentFile=${APP_DIR}/.env|" \
  -e "s|^ExecStart=.*|ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run_app.py|" \
  -e "s|^User=.*|User=root|" \
  "${APP_DIR}/deploy/gold-signal.service" | sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

echo "[6/8] Configuring Nginx..."
sudo cp "${APP_DIR}/deploy/nginx.conf" "/etc/nginx/sites-available/${SERVICE_NAME}"
sudo sed -i "s/server_name .*/server_name ${DOMAIN};/" "/etc/nginx/sites-available/${SERVICE_NAME}"
sudo ln -sf "/etc/nginx/sites-available/${SERVICE_NAME}" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "[7/8] Requesting TLS certificate..."
sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "admin@${DOMAIN}" || true

echo "[8/8] Health check..."
curl -fsS "http://127.0.0.1:8001/signal?metal=gold" >/dev/null && echo "App endpoint OK"
curl -fsS "http://127.0.0.1:8001/manifest.webmanifest" >/dev/null && echo "Manifest OK"

echo "Deployment complete."
echo "If HTTPS cert step failed, run manually: sudo certbot --nginx -d ${DOMAIN}"
