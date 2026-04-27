from chessboard_app.wifi import WifiManager


def main():
    wifi = WifiManager()
    status = wifi.status()
    if status["connected"]:
        print(f"Wi-Fi already connected: {status['ssid']}")
        return
    if not status["available"]:
        print("NetworkManager/nmcli is not available; cannot start setup hotspot.")
        return
    wifi.start_hotspot()
    print(f"Started setup hotspot: {wifi.setup_ssid}")
    print(f"Password: {wifi.setup_password}")
    print(f"Setup URL: {wifi.setup_url}")


if __name__ == "__main__":
    main()
