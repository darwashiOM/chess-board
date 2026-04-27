# Pi Kiosk Setup

This makes the Pi boot straight into the chessboard screen.

## Install Dependencies

From the Pi:

```bash
cd ~/Desktop/chess-board
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install Chromium if it is not already installed:

```bash
sudo apt update
sudo apt install -y chromium-browser
```

On newer Raspberry Pi OS images the package may be named:

```bash
sudo apt install -y chromium
```

If the executable is `/usr/bin/chromium` instead of `/usr/bin/chromium-browser`, edit `deploy/systemd/chessboard-kiosk.service`.

## Enable Boot To Screen

```bash
cd ~/Desktop/chess-board
sudo cp deploy/systemd/chessboard.service /etc/systemd/system/chessboard.service
sudo cp deploy/systemd/chessboard-hotspot.service /etc/systemd/system/chessboard-hotspot.service
sudo cp deploy/systemd/chessboard-kiosk.service /etc/systemd/system/chessboard-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable chessboard-hotspot.service
sudo systemctl enable chessboard.service
sudo systemctl enable chessboard-kiosk.service
sudo systemctl start chessboard-hotspot.service
sudo systemctl start chessboard.service
sudo systemctl start chessboard-kiosk.service
```

Reboot test:

```bash
sudo reboot
```

The Pi should open Chromium directly to:

```text
http://127.0.0.1:8000
```

## First-Time Wi-Fi Setup

If the Pi has no saved Wi-Fi connection, it starts a setup hotspot.

Connect a phone or laptop to:

```text
SSID: ChessBoard-Setup
Password: chessboard
```

The Wi-Fi tab also shows a QR code for this setup network. Scan it to join the hotspot faster.

Then open:

```text
http://10.42.0.1:8000
```

Use the Wi-Fi tab to enter the real home Wi-Fi SSID and password. NetworkManager saves the connection, so the Pi should reconnect after reboot.

## Lichess Token Setup

From the Home tab, open the token link:

```text
Create Lichess token with board:play
```

The Home tab also shows a QR code for the Lichess token creation page. Scan it on a phone, create the token, then paste/type the token into the board UI.

Log into Lichess, create the token, paste it into the chessboard screen, and select Connect.

The token is saved only on the Pi in the local config file. The browser UI never receives the stored token back.

## Five Button Navigation

Map the physical buttons to keyboard events:

- Up button: `ArrowUp`
- Down button: `ArrowDown`
- Left button: `ArrowLeft`
- Right button: `ArrowRight`
- Select button: `Enter`

The web UI is built so these five inputs can move between tabs, move between controls, and activate the selected item.

## Useful Commands

Check backend logs:

```bash
journalctl -u chessboard.service -f
```

Check kiosk logs:

```bash
journalctl -u chessboard-kiosk.service -f
```

Stop kiosk temporarily:

```bash
sudo systemctl stop chessboard-kiosk.service
```

Disable kiosk boot:

```bash
sudo systemctl disable chessboard-kiosk.service
```
