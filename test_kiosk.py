from pathlib import Path
import unittest


class KioskTest(unittest.TestCase):
    def test_server_html_contains_five_button_navigation_hooks(self):
        html = Path("chessboard_app/server.py").read_text(encoding="utf-8")

        self.assertIn("ArrowUp", html)
        self.assertIn("ArrowDown", html)
        self.assertIn("ArrowLeft", html)
        self.assertIn("ArrowRight", html)
        self.assertIn("activateRelativeTab", html)
        self.assertIn("maybeShowSetupTab", html)
        self.assertIn("/auth/lichess/start", html)
        self.assertIn("Connect Lichess from phone", html)
        self.assertIn("wifiSetupScreen", html)
        self.assertIn("lichessSetupScreen", html)
        self.assertIn('data-tab="play"', html)
        self.assertIn("/api/play/friend", html)

    def test_systemd_services_boot_backend_and_kiosk(self):
        backend = Path("deploy/systemd/chessboard.service").read_text(encoding="utf-8")
        hotspot = Path("deploy/systemd/chessboard-hotspot.service").read_text(encoding="utf-8")
        kiosk = Path("deploy/systemd/chessboard-kiosk.service").read_text(encoding="utf-8")

        self.assertIn("run_server.py --hardware", backend)
        self.assertIn("--host 0.0.0.0", backend)
        self.assertIn("WantedBy=multi-user.target", backend)
        self.assertIn("ensure_wifi_or_hotspot.py", hotspot)
        self.assertIn("Before=chessboard.service", hotspot)
        self.assertIn("--kiosk", kiosk)
        self.assertIn("http://127.0.0.1:8000", kiosk)


if __name__ == "__main__":
    unittest.main()
