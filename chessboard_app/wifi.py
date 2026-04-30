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
    wifi_interface = "wlan0"

    def __init__(self, runner: CommandRunner = default_runner):
        self.runner = runner

    def _status_payload(
        self,
        *,
        available: bool,
        connected: bool,
        ssid: str | None,
        interface: str | None,
        ip: str | None,
        mode: str,
    ) -> dict[str, object]:
        return {
            "available": available,
            "connected": connected,
            "ssid": ssid,
            "interface": interface,
            "ip": ip,
            "mode": mode,
            "setupSsid": self.setup_ssid,
            "setupPassword": self.setup_password,
            "setupUrl": self.setup_url,
        }

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
            wired_status = self._wired_status()
            if wired_status is not None:
                return wired_status
            return self._status_payload(
                available=False,
                connected=False,
                ssid=None,
                interface=None,
                ip=None,
                mode="unavailable",
            )

        wifi_status = None
        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) >= 5 and parts[0] == "yes":
                wifi_status = self._status_payload(
                    available=True,
                    connected=parts[3] == "connected",
                    ssid=parts[1] or None,
                    interface=parts[2] or None,
                    ip=parts[4].split("/")[0] if parts[4] else None,
                    mode="setup" if parts[1] == self.setup_ssid else "client",
                )
                break
            if len(parts) >= 4 and parts[2] == "connected":
                wifi_status = self._status_payload(
                    available=True,
                    connected=True,
                    ssid=parts[0] or None,
                    interface=parts[1] or None,
                    ip=parts[3].split("/")[0] if parts[3] else None,
                    mode="setup" if parts[0] == self.setup_ssid else "client",
                )
                break

        if wifi_status and wifi_status["mode"] == "client":
            return wifi_status

        wired_status = self._wired_status()
        if wired_status is not None:
            return wired_status

        if wifi_status is not None:
            return wifi_status

        return self._status_payload(
            available=True,
            connected=False,
            ssid=None,
            interface=None,
            ip=None,
            mode="disconnected",
        )

    def _wired_status(self) -> dict[str, object] | None:
        try:
            output = self.runner([
                "nmcli",
                "-t",
                "-f",
                "device,type,state,connection",
                "dev",
                "status",
            ])
        except Exception:
            return None

        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[1] == "ethernet" and parts[2] == "connected":
                device = parts[0] or None
                return self._status_payload(
                    available=True,
                    connected=True,
                    ssid=parts[3] or None,
                    interface=device,
                    ip=self._device_ip(device),
                    mode="wired",
                )
        return None

    def _device_ip(self, device: str | None) -> str | None:
        if not device:
            return None
        try:
            output = self.runner(["nmcli", "-t", "-f", "ip4.address", "dev", "show", device])
        except Exception:
            return None
        for line in output.splitlines():
            value = line.split(":", 1)[-1]
            if value:
                return value.split("/")[0]
        return None

    def scan(self) -> list[dict[str, object]]:
        self.enable_wifi()
        self.stop_hotspot()
        self.rescan()
        try:
            output = self.runner([
                "nmcli",
                "-t",
                "-f",
                "ssid,signal,security",
                "dev",
                "wifi",
                "list",
                "ifname",
                self.wifi_interface,
                "--rescan",
                "yes",
            ])
        except Exception:
            output = ""
        networks = self._parse_nmcli_networks(output)
        if networks:
            return networks
        return self._scan_with_iw()

    def _parse_nmcli_networks(self, output: str) -> list[dict[str, object]]:
        networks: list[dict[str, object]] = []
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

    def _scan_with_iw(self) -> list[dict[str, object]]:
        try:
            output = self.runner(["iw", "dev", self.wifi_interface, "scan"])
        except Exception:
            return []

        networks = []
        seen = set()
        current: dict[str, object] | None = None
        privacy = False
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("BSS "):
                if current and current.get("ssid") and current["ssid"] not in seen:
                    current["security"] = "WPA/WPA2" if privacy else ""
                    networks.append(current)
                    seen.add(current["ssid"])
                current = {"ssid": None, "signal": 0, "security": ""}
                privacy = False
            elif current is not None and stripped.startswith("SSID:"):
                current["ssid"] = stripped.split("SSID:", 1)[1].strip()
            elif current is not None and stripped.startswith("signal:"):
                value = stripped.split("signal:", 1)[1].strip().split()[0]
                current["signal"] = _dbm_to_percent(float(value))
            elif current is not None and "Privacy" in stripped:
                privacy = True

        if current and current.get("ssid") and current["ssid"] not in seen:
            current["security"] = "WPA/WPA2" if privacy else ""
            networks.append(current)
        return networks

    def stop_hotspot(self) -> None:
        try:
            self.runner(["nmcli", "connection", "down", self.setup_ssid])
        except Exception:
            pass

    def enable_wifi(self) -> None:
        try:
            self.runner(["nmcli", "radio", "wifi", "on"])
        except Exception:
            pass
        try:
            self.runner(["rfkill", "unblock", "wifi"])
        except Exception:
            pass

    def rescan(self) -> None:
        try:
            self.runner(["nmcli", "dev", "wifi", "rescan", "ifname", self.wifi_interface])
        except Exception:
            pass

    def connect(self, ssid: str, password: str) -> None:
        self.enable_wifi()
        self.stop_hotspot()
        command = [
            "nmcli",
            "dev",
            "wifi",
            "connect",
            ssid,
        ]
        if password:
            command.extend(["password", password])
        command.extend([
            "ifname",
            self.wifi_interface,
        ])
        self.runner(command)

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


def _dbm_to_percent(dbm: float) -> int:
    if dbm <= -90:
        return 0
    if dbm >= -50:
        return 100
    return int(round(100 * (dbm + 90) / 40))
