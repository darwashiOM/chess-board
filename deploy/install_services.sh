#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt

sudo cp deploy/systemd/chessboard-hotspot.service /etc/systemd/system/chessboard-hotspot.service
sudo cp deploy/systemd/chessboard.service /etc/systemd/system/chessboard.service
sudo cp deploy/systemd/chessboard-kiosk.service /etc/systemd/system/chessboard-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable chessboard-hotspot.service chessboard.service chessboard-kiosk.service
sudo systemctl restart chessboard-hotspot.service
sudo systemctl restart chessboard.service
sudo systemctl restart chessboard-kiosk.service

echo "Chessboard services installed and restarted."
