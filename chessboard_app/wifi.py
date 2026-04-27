from __future__ import annotations

import subprocess
from typing import Callable


CommandRunner = Callable[[list[str]], str]


def default_runner(args: list[str]) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


class WifiManager:
    setup_ssid = "ChessBoard-Setup"
    setup_password = "chessboard"
    setup_url = "http://10.42.0.1:8000"

    def __init__(self, runner: CommandRunner = default_runner):
        self.runner = runner

    def status(self) -> dict[str, object]:
        try:
            output = self.runner([
                "nmcli",
                "-t",
                "-f",
                "active,ssid,device,state,ip4.address",
                "dev",
                "wifi",
            ])
        except Exception:
            return {
                "available": False,
                "connected": False,
                "ssid": None,
                "interface": None,
                "ip": None,
                "mode": "unavailable",
                "setupSsid": self.setup_ssid,
                "setupPassword": self.setup_password,
                "setupUrl": self.setup_url,
            }

        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) >= 5 and parts[0] == "yes":
                return {
                    "available": True,
                    "connected": parts[3] == "connected",
                    "ssid": parts[1] or None,
                    "interface": parts[2] or None,
                    "ip": parts[4].split("/")[0] if parts[4] else None,
                    "mode": "setup" if parts[1] == self.setup_ssid else "client",
                    "setupSsid": self.setup_ssid,
                    "setupPassword": self.setup_password,
                    "setupUrl": self.setup_url,
                }
            if len(parts) >= 4 and parts[2] == "connected":
                return {
                    "available": True,
                    "connected": True,
                    "ssid": parts[0] or None,
                    "interface": parts[1] or None,
                    "ip": parts[3].split("/")[0] if parts[3] else None,
                    "mode": "setup" if parts[0] == self.setup_ssid else "client",
                    "setupSsid": self.setup_ssid,
                    "setupPassword": self.setup_password,
                    "setupUrl": self.setup_url,
                }
        return {
            "available": True,
            "connected": False,
            "ssid": None,
            "interface": None,
            "ip": None,
            "mode": "disconnected",
            "setupSsid": self.setup_ssid,
            "setupPassword": self.setup_password,
            "setupUrl": self.setup_url,
        }

    def scan(self) -> list[dict[str, object]]:
        output = self.runner(["nmcli", "-t", "-f", "ssid,signal,security", "dev", "wifi", "list"])
        networks = []
        seen = set()
        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) < 3 or not parts[0] or parts[0] in seen:
                continue
            seen.add(parts[0])
            networks.append({
                "ssid": parts[0],
                "signal": int(parts[1] or 0),
                "security": parts[2],
            })
        return networks

    def connect(self, ssid: str, password: str) -> None:
        self.runner(["nmcli", "dev", "wifi", "connect", ssid, "password", password])

    def start_hotspot(self, ifname: str = "wlan0") -> None:
        self.runner([
            "nmcli",
            "dev",
            "wifi",
            "hotspot",
            "ifname",
            ifname,
            "ssid",
            self.setup_ssid,
            "password",
            self.setup_password,
        ])
