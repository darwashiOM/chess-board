import unittest

from chessboard_app.wifi import WifiManager


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return self.outputs.pop(0)


class WifiTest(unittest.TestCase):
    def test_status_parses_connected_network(self):
        runner = FakeRunner(["HomeWifi:wlan0:connected:192.168.1.50\n"])
        wifi = WifiManager(runner=runner)

        status = wifi.status()

        self.assertEqual(status["available"], True)
        self.assertEqual(status["connected"], True)
        self.assertEqual(status["ssid"], "HomeWifi")
        self.assertEqual(status["interface"], "wlan0")
        self.assertEqual(status["ip"], "192.168.1.50")
        self.assertEqual(status["mode"], "client")

    def test_scan_parses_networks(self):
        runner = FakeRunner(["Home:80:WPA2\nCafe:40:WPA1 WPA2\n"])
        wifi = WifiManager(runner=runner)

        self.assertEqual(wifi.scan(), [
            {"ssid": "Home", "signal": 80, "security": "WPA2"},
            {"ssid": "Cafe", "signal": 40, "security": "WPA1 WPA2"},
        ])

    def test_connect_uses_nmcli(self):
        runner = FakeRunner([""])
        wifi = WifiManager(runner=runner)

        wifi.connect("Home", "password")

        self.assertEqual(runner.calls[0], ["nmcli", "dev", "wifi", "connect", "Home", "password", "password"])

    def test_start_hotspot_uses_nmcli_hotspot(self):
        runner = FakeRunner([""])
        wifi = WifiManager(runner=runner)

        wifi.start_hotspot()

        self.assertEqual(runner.calls[0], [
            "nmcli",
            "dev",
            "wifi",
            "hotspot",
            "ifname",
            "wlan0",
            "ssid",
            "ChessBoard-Setup",
            "password",
            "chessboard",
        ])

    def test_setup_status_marks_setup_network(self):
        runner = FakeRunner(["ChessBoard-Setup:wlan0:connected:10.42.0.1\n"])
        wifi = WifiManager(runner=runner)

        status = wifi.status()

        self.assertEqual(status["mode"], "setup")
        self.assertEqual(status["setupUrl"], "http://10.42.0.1:8000")


if __name__ == "__main__":
    unittest.main()
