from pathlib import Path
import unittest


class KioskTest(unittest.TestCase):
    def test_server_html_contains_five_button_navigation_hooks(self):
        html = Path("chessboard_app/server.py").read_text(encoding="utf-8")

        self.assertIn("kioskState", html)
        self.assertIn("renderScreen", html)
        self.assertIn("renderWifiList", html)
        self.assertIn("renderWifiPassword", html)
        self.assertIn("PASSWORD_ROWS", html)
        for symbol in ["!", "@", "#", "$", "%", "^", "&", "*", "?"]:
            self.assertIn(f'"{symbol}"', html)
        self.assertIn("activateSelected", html)
        self.assertIn("goBack", html)
        self.assertIn("/auth/lichess/start", html)
        self.assertIn("Connect Lichess", html)
        self.assertIn("Get API Key", html)
        self.assertIn("Enter API Key", html)
        self.assertIn("/phone-setup", html)
        self.assertIn("Send Token To Board", html)
        self.assertIn("/api/lichess-manual-token-qr.svg", html)
        self.assertIn("Choose Wi-Fi", html)
        self.assertIn("state.wifi.connected", html)
        self.assertIn('state.wifi.mode === "wired"', html)
        self.assertIn("Board Test", html)
        self.assertIn("LED Test", html)
        self.assertIn("/api/led/test", html)
        self.assertIn("activeControlRoot", html)
        self.assertIn('stage === "wifi"', html)
        self.assertIn("/api/phone-setup-qr.svg", html)
        self.assertNotIn('<img alt="Board setup network QR code"', html)
        self.assertNotIn('<img alt="Board setup page QR code"', html)
        self.assertNotIn('id="mainWifiSsidDisplay" type="text"', html)
        self.assertNotIn("activateRelativeTab", html)
        self.assertNotIn('class="tabButton"', html)
        self.assertIn("/api/play/friend", html)

    def test_systemd_services_boot_backend_and_kiosk(self):
        backend = Path("deploy/systemd/chessboard.service").read_text(encoding="utf-8")
        hotspot = Path("deploy/systemd/chessboard-hotspot.service").read_text(encoding="utf-8")
        portal = Path("deploy/systemd/chessboard-portal.service").read_text(encoding="utf-8")
        dpad = Path("deploy/systemd/chessboard-dpad.service").read_text(encoding="utf-8")
        kiosk = Path("deploy/systemd/chessboard-kiosk.service").read_text(encoding="utf-8")

        self.assertIn("run_server.py --hardware", backend)
        self.assertIn("--host 0.0.0.0", backend)
        self.assertNotIn("network-online.target", backend)
        self.assertIn("WantedBy=multi-user.target", backend)
        self.assertIn("ensure_wifi_or_hotspot.py", hotspot)
        self.assertIn("Before=chessboard.service", hotspot)
        self.assertIn("setup_portal.py", portal)
        self.assertIn("dpad_keyboard.py", dpad)
        self.assertIn("User=root", dpad)
        self.assertIn("--mode http", dpad)
        self.assertIn("--kiosk", kiosk)
        self.assertIn("/bin/sleep 1", kiosk)
        self.assertIn("http://127.0.0.1:8000", kiosk)

    def test_install_script_updates_services(self):
        script = Path("deploy/install_services.sh").read_text(encoding="utf-8")

        self.assertIn("pip install -r requirements.txt", script)
        self.assertIn("dnsmasq-shared.d", script)
        self.assertIn("chessboard-portal.service", script)
        self.assertIn("chessboard-dpad.service", script)
        self.assertIn("modprobe uinput", script)
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("systemctl restart chessboard.service", script)


if __name__ == "__main__":
    unittest.main()
