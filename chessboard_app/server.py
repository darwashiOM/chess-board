from typing import Any

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.leds import DisabledLedController, LedSettings
from chessboard_app.lichess_client import LichessClient
from chessboard_app.sensors import StaticSensorReader
from chessboard_app.setup_qr import setup_url_qr_svg, setup_wifi_qr_svg
from chessboard_app.wifi import WifiManager


def build_state(
    config_store: AppConfigStore,
    sensor_reader: Any,
    game_session: GameSession | None = None,
    wifi_manager: WifiManager | None = None,
    led_controller: Any | None = None,
) -> dict[str, Any]:
    state = config_store.public_state()
    snapshot = sensor_reader.read().as_dict()
    game_session = game_session or GameSession()
    wifi_manager = wifi_manager or WifiManager()
    led_controller = led_controller or DisabledLedController()
    led_controller.apply_settings(LedSettings(
        enabled=state["ledsEnabled"],
        brightness=state["ledBrightness"],
    ))
    led_status = led_controller.status()
    state["hardware"] = {
        "sensors": "ok",
        "leds": led_status["mode"],
    }
    state["leds"] = led_status
    state["sensors"] = snapshot
    state["sensorDetails"] = getattr(sensor_reader, "details", lambda: {})()
    state["game"] = game_session.public_state()
    state["sync"] = game_session.sync_status(snapshot)
    state["wifi"] = wifi_manager.status()
    return state


def create_app(
    config_store: AppConfigStore | None = None,
    sensor_reader: Any | None = None,
    game_session: GameSession | None = None,
    wifi_manager: WifiManager | None = None,
    led_controller: Any | None = None,
):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, Response
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is required to run the web server. Install with: "
            "pip install fastapi uvicorn"
        ) from exc

    config_store = config_store or AppConfigStore()
    sensor_reader = sensor_reader or StaticSensorReader()
    game_session = game_session or GameSession()
    wifi_manager = wifi_manager or WifiManager()
    led_controller = led_controller or DisabledLedController()
    app = FastAPI(title="Lichess Physical Chessboard")

    class TokenRequest(BaseModel):
        token: str

    class SettingsRequest(BaseModel):
        ledsEnabled: bool | None = None
        ledBrightness: float | None = None
        boardOrientation: str | None = None
        deviceName: str | None = None

    class WifiConnectRequest(BaseModel):
        ssid: str
        password: str

    class GameStateRequest(BaseModel):
        id: str | None = None
        white: dict[str, Any] | None = None
        black: dict[str, Any] | None = None
        state: dict[str, Any] | None = None

    @app.get("/", response_class=HTMLResponse)
    def index():
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ChessBoard</title>
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; font-family: system-ui, sans-serif; background: #161512; color: #f0ede7; overflow: hidden; }
      main { width: 100vw; height: 100vh; padding: 10px; display: grid; grid-template-rows: auto 1fr; gap: 8px; }
      header { display: grid; grid-template-columns: 1fr; gap: 8px; }
      h1 { font-size: clamp(18px, 5vw, 30px); margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      nav { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; }
      nav button { min-height: 42px; background: #2f2b24; color: #f0ede7; border: 2px solid #5b5548; font-weight: 700; }
      nav button.active { background: #769656; color: #111; border-color: #a5c982; }
      .layout { display: grid; grid-template-columns: minmax(150px, 45vh) 1fr; gap: 10px; align-items: start; min-height: 0; }
      .grid { display: grid; grid-template-columns: repeat(8, minmax(16px, 1fr)); width: min(45vh, 48vw); border: 2px solid #6f6a60; }
      .sq { aspect-ratio: 1; display: grid; place-items: center; font-weight: 700; }
      .light { background: #eeeed2; color: #333; }
      .dark { background: #769656; color: #111; }
      .piece { width: 42%; height: 42%; border-radius: 50%; background: #1f1f1f; box-shadow: 0 0 0 3px #f8f8f8; }
      .panel { line-height: 1.35; color: #d8d3c8; min-height: 0; overflow: auto; padding-right: 4px; }
      .tab { display: none; }
      .tab.active { display: block; }
      .field { display: grid; gap: 4px; margin-bottom: 10px; }
      .row { display: flex; align-items: center; justify-content: space-between; gap: 8px; border-bottom: 1px solid #403b33; padding: 8px 0; }
      input, select { width: 100%; min-width: 0; min-height: 42px; padding: 8px; background: #f0ede7; border: 0; font-size: 16px; }
      button { min-height: 42px; padding: 8px 12px; font-size: 15px; }
      button, input, select, a { outline: none; }
      button:focus, input:focus, select:focus, a:focus { box-shadow: 0 0 0 4px #f4d35e; }
      .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
      .primary { background: #769656; color: #111; border: 2px solid #a5c982; font-weight: 800; }
      code { color: #f4d35e; }
      pre { max-height: 160px; overflow: auto; white-space: pre-wrap; font-size: 11px; }
      @media (max-width: 560px), (max-height: 420px) {
        main { padding: 6px; gap: 6px; }
        h1 { display: none; }
        nav { grid-template-columns: repeat(5, 1fr); }
        nav button { min-height: 36px; padding: 4px; font-size: 12px; }
        .layout { grid-template-columns: 39vw 1fr; gap: 8px; }
        .grid { width: 39vw; }
        .row { padding: 5px 0; font-size: 13px; }
        button, input, select { min-height: 36px; font-size: 13px; }
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1 id="title">ChessBoard</h1>
        <nav>
          <button class="tabButton active" data-tab="home">Home</button>
          <button class="tabButton" data-tab="game">Game</button>
          <button class="tabButton" data-tab="settings">Settings</button>
          <button class="tabButton" data-tab="wifi">Wi-Fi</button>
          <button class="tabButton" data-tab="diagnostics">Diagnostics</button>
        </nav>
      </header>
      <div class="layout">
        <div id="board" class="grid"></div>
        <section class="panel">
          <div id="home" class="tab active">
            <div id="status">Loading...</div>
            <p><a id="tokenLink" href="https://lichess.org/account/oauth/token/create?scopes[]=board:play" target="_blank" rel="noreferrer">Create Lichess token with board:play</a></p>
            <img id="lichessQr" alt="Lichess token QR code" src="/api/lichess-token-qr.svg" style="width:min(210px,70vw);background:#fff;padding:8px;margin:8px 0;">
            <form id="tokenForm">
              <div class="field">
                <label for="token">Lichess token</label>
                <input id="token" type="password" placeholder="Token with board:play">
              </div>
              <div class="actions">
                <button class="primary">Connect</button>
                <button id="logoutButton" type="button">Disconnect</button>
              </div>
            </form>
          </div>
          <div id="game" class="tab">
            <div class="row"><span>Game</span><code id="gameId">none</code></div>
            <div class="row"><span>Turn</span><code id="turn">white</code></div>
            <div class="row"><span>White clock</span><code id="whiteClock">--</code></div>
            <div class="row"><span>Black clock</span><code id="blackClock">--</code></div>
            <div class="row"><span>Last move</span><code id="lastMove">none</code></div>
            <div class="row"><span>Board sync</span><code id="syncStatus">unknown</code></div>
            <div class="actions">
              <button id="resignButton" type="button">Resign</button>
              <button id="abortButton" type="button">Abort</button>
              <button id="drawButton" type="button">Draw</button>
            </div>
          </div>
          <div id="settings" class="tab">
            <div class="row">
              <label for="ledToggle">Lights</label>
              <input id="ledToggle" type="checkbox">
            </div>
            <div class="row">
              <label for="ledBrightness">Brightness</label>
              <input id="ledBrightness" type="range" min="0" max="1" step="0.01">
            </div>
            <div class="row">
              <label for="orientation">Board orientation</label>
              <select id="orientation">
                <option value="white">White at bottom</option>
                <option value="black">Black at bottom</option>
              </select>
            </div>
            <div class="row">
              <label for="deviceName">Device name</label>
              <input id="deviceName" type="text">
            </div>
            <button id="saveSettings" class="primary">Save</button>
            <div id="settingsStatus"></div>
          </div>
          <div id="wifi" class="tab">
            <div class="row"><span>Status</span><code id="wifiStatus">unknown</code></div>
            <div class="row"><span>SSID</span><code id="wifiSsid">none</code></div>
            <div class="row"><span>IP</span><code id="wifiIp">none</code></div>
            <div class="row"><span>Setup network</span><code id="setupSsid">ChessBoard-Setup</code></div>
            <div class="row"><span>Setup password</span><code id="setupPassword">chessboard</code></div>
            <div class="row"><span>Setup page</span><code id="setupUrl">http://10.42.0.1:8000</code></div>
            <img id="setupQr" alt="Setup Wi-Fi QR code" src="/api/setup-qr.svg" style="width:min(210px,70vw);background:#fff;padding:8px;margin:8px 0;">
            <form id="wifiForm">
              <div class="field">
                <label for="wifiSsidInput">SSID</label>
                <input id="wifiSsidInput" type="text">
              </div>
              <div class="field">
                <label for="wifiPassword">Password</label>
                <input id="wifiPassword" type="password">
              </div>
              <button class="primary">Connect Wi-Fi</button>
            </form>
            <button id="scanWifi" type="button">Scan Networks</button>
            <button id="startHotspot" type="button">Start Setup Hotspot</button>
            <div id="wifiNetworks"></div>
          </div>
          <div id="diagnostics" class="tab">
            <div class="row"><span>Sensors</span><code id="sensorStatus">unknown</code></div>
            <div class="row"><span>LEDs</span><code id="ledStatus">unknown</code></div>
            <div class="row"><span>Occupied squares</span><code id="occupiedCount">0</code></div>
            <div id="occupiedSquares"></div>
            <div class="row"><span>Missing expected pieces</span><code id="missingSquares">none</code></div>
            <div class="row"><span>Extra pieces</span><code id="extraSquares">none</code></div>
            <pre id="rawSensorDetails"></pre>
          </div>
        </section>
      </div>
    </main>
    <script>
      const squares = [];
      for (let rank = 8; rank >= 1; rank--) {
        for (const file of "abcdefgh") squares.push(file + rank);
      }
      const boardEl = document.getElementById("board");
      const statusEl = document.getElementById("status");
      const titleEl = document.getElementById("title");
      const tabOrder = ["home", "game", "settings", "wifi", "diagnostics"];
      let latestState = null;
      function render(state) {
        latestState = state;
        titleEl.textContent = state.deviceName || "ChessBoard";
        boardEl.innerHTML = "";
        const displaySquares = state.boardOrientation === "black" ? [...squares].reverse() : squares;
        for (const square of displaySquares) {
          const file = square.charCodeAt(0) - 97;
          const rank = Number(square[1]);
          const el = document.createElement("div");
          el.className = "sq " + ((file + rank) % 2 ? "light" : "dark");
          el.title = square;
          if (state.sensors[square]) {
            const piece = document.createElement("div");
            piece.className = "piece";
            el.appendChild(piece);
          }
          boardEl.appendChild(el);
        }
        statusEl.textContent = state.lichess.connected
          ? `Connected to Lichess as ${state.lichess.username || "unknown"}`
          : "Lichess not connected";
        document.getElementById("tokenLink").href = state.lichessTokenUrl;
        document.getElementById("lichessQr").style.display = state.lichess.connected ? "none" : "block";
        document.getElementById("ledToggle").checked = Boolean(state.ledsEnabled);
        document.getElementById("ledBrightness").value = state.ledBrightness || 0.1;
        document.getElementById("orientation").value = state.boardOrientation || "white";
        document.getElementById("deviceName").value = state.deviceName || "ChessBoard";
        document.getElementById("sensorStatus").textContent = state.hardware.sensors;
        document.getElementById("ledStatus").textContent = `${state.leds.mode} ${Math.round(state.leds.brightness * 100)}%`;
        const occupied = squares.filter(square => state.sensors[square]);
        document.getElementById("occupiedCount").textContent = String(occupied.length);
        document.getElementById("occupiedSquares").textContent = occupied.join(", ") || "none";
        document.getElementById("gameId").textContent = state.game.id || "none";
        document.getElementById("turn").textContent = state.game.turn;
        document.getElementById("whiteClock").textContent = formatClock(state.game.clock.whiteMs);
        document.getElementById("blackClock").textContent = formatClock(state.game.clock.blackMs);
        document.getElementById("lastMove").textContent = state.game.lastMove || "none";
        document.getElementById("syncStatus").textContent = state.sync.matches ? "synced" : "fix board";
        document.getElementById("missingSquares").textContent = state.sync.missing.join(", ") || "none";
        document.getElementById("extraSquares").textContent = state.sync.extra.join(", ") || "none";
        document.getElementById("wifiStatus").textContent = state.wifi.connected ? "connected" : (state.wifi.available ? "not connected" : "unavailable");
        document.getElementById("wifiSsid").textContent = state.wifi.ssid || "none";
        document.getElementById("wifiIp").textContent = state.wifi.ip || "none";
        document.getElementById("setupSsid").textContent = state.wifi.setupSsid || "ChessBoard-Setup";
        document.getElementById("setupPassword").textContent = state.wifi.setupPassword || "chessboard";
        document.getElementById("setupUrl").textContent = state.wifi.setupUrl || "http://10.42.0.1:8000";
        document.getElementById("setupQr").style.display = state.wifi.mode === "client" ? "none" : "block";
        document.getElementById("rawSensorDetails").textContent = JSON.stringify(state.sensorDetails, null, 2);
      }
      function formatClock(ms) {
        if (ms === null || ms === undefined) return "--";
        const total = Math.max(0, Math.floor(ms / 1000));
        const minutes = Math.floor(total / 60);
        const seconds = total % 60;
        return `${minutes}:${String(seconds).padStart(2, "0")}`;
      }
      function activeTabId() {
        return document.querySelector(".tab.active").id;
      }
      function visibleControls() {
        const activeTab = document.querySelector(".tab.active");
        return [
          ...document.querySelectorAll(".tabButton"),
          ...activeTab.querySelectorAll("button, input, select, a")
        ].filter(el => !el.disabled && el.offsetParent !== null);
      }
      function focusRelative(offset) {
        const controls = visibleControls();
        if (!controls.length) return;
        const index = Math.max(0, controls.indexOf(document.activeElement));
        controls[(index + offset + controls.length) % controls.length].focus();
      }
      function activateTab(tabId) {
        const button = document.querySelector(`[data-tab="${tabId}"]`);
        if (!button) return;
        for (const item of document.querySelectorAll(".tabButton, .tab")) item.classList.remove("active");
        button.classList.add("active");
        document.getElementById(tabId).classList.add("active");
        if (latestState) render(latestState);
        button.focus();
      }
      function activateRelativeTab(offset) {
        const current = tabOrder.indexOf(activeTabId());
        activateTab(tabOrder[(current + offset + tabOrder.length) % tabOrder.length]);
      }
      async function refresh() {
        const res = await fetch("/api/state");
        render(await res.json());
      }
      document.getElementById("tokenForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        const token = document.getElementById("token").value;
        await fetch("/api/lichess/token", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({token})
        });
        document.getElementById("token").value = "";
        await refresh();
      });
      document.getElementById("logoutButton").addEventListener("click", async () => {
        await fetch("/api/lichess/logout", {method: "POST"});
        await refresh();
      });
      document.getElementById("saveSettings").addEventListener("click", async () => {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            ledsEnabled: document.getElementById("ledToggle").checked,
            ledBrightness: Number(document.getElementById("ledBrightness").value),
            boardOrientation: document.getElementById("orientation").value,
            deviceName: document.getElementById("deviceName").value
          })
        });
        document.getElementById("settingsStatus").textContent = res.ok ? "Saved" : "Could not save settings";
        await refresh();
      });
      document.getElementById("wifiForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        await fetch("/api/wifi/connect", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            ssid: document.getElementById("wifiSsidInput").value,
            password: document.getElementById("wifiPassword").value
          })
        });
        document.getElementById("wifiPassword").value = "";
        await refresh();
      });
      document.getElementById("scanWifi").addEventListener("click", async () => {
        const res = await fetch("/api/wifi/scan");
        const networks = await res.json();
        document.getElementById("wifiNetworks").textContent = networks.map(n => `${n.ssid} (${n.signal}%)`).join(", ") || "none";
      });
      document.getElementById("startHotspot").addEventListener("click", async () => {
        await fetch("/api/wifi/hotspot", {method: "POST"});
        await refresh();
      });
      async function gameAction(path) {
        await fetch(path, {method: "POST"});
        await refresh();
      }
      document.getElementById("resignButton").addEventListener("click", () => gameAction("/api/game/resign"));
      document.getElementById("abortButton").addEventListener("click", () => gameAction("/api/game/abort"));
      document.getElementById("drawButton").addEventListener("click", () => gameAction("/api/game/draw/yes"));
      for (const button of document.querySelectorAll(".tabButton")) {
        button.addEventListener("click", () => {
          activateTab(button.dataset.tab);
        });
      }
      document.addEventListener("keydown", (event) => {
        if (event.key === "ArrowUp") {
          event.preventDefault();
          focusRelative(-1);
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          focusRelative(1);
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          activateRelativeTab(-1);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          activateRelativeTab(1);
        }
      });
      refresh();
      document.querySelector(".tabButton.active").focus();
      setInterval(refresh, 1000);
    </script>
  </body>
</html>
"""

    @app.get("/api/state")
    def api_state():
        return build_state(config_store, sensor_reader, game_session, wifi_manager, led_controller)

    @app.get("/api/sensors")
    def api_sensors():
        return sensor_reader.read().as_dict()

    @app.get("/api/setup-qr.svg")
    def setup_qr():
        return Response(
            content=setup_wifi_qr_svg(wifi_manager.setup_ssid, wifi_manager.setup_password),
            media_type="image/svg+xml",
        )

    @app.get("/api/lichess-token-qr.svg")
    def lichess_token_qr():
        return Response(
            content=setup_url_qr_svg(config_store.public_state()["lichessTokenUrl"]),
            media_type="image/svg+xml",
        )

    @app.post("/api/settings")
    def update_settings(payload: SettingsRequest):
        try:
            config_store.update_settings(
                leds_enabled=payload.ledsEnabled,
                led_brightness=payload.ledBrightness,
                board_orientation=payload.boardOrientation,
                device_name=payload.deviceName,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return config_store.public_state()

    @app.get("/api/wifi/status")
    def wifi_status():
        return wifi_manager.status()

    @app.get("/api/wifi/scan")
    def wifi_scan():
        try:
            return wifi_manager.scan()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/wifi/connect")
    def wifi_connect(payload: WifiConnectRequest):
        try:
            wifi_manager.connect(payload.ssid, payload.password)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return wifi_manager.status()

    @app.post("/api/wifi/hotspot")
    def wifi_hotspot():
        try:
            wifi_manager.start_hotspot()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return wifi_manager.status()

    @app.get("/api/games")
    def active_games():
        config = config_store.load()
        if not config.lichess_token:
            raise HTTPException(status_code=401, detail="Lichess is not connected")
        return LichessClient(config.lichess_token).active_games()

    @app.post("/api/game/mock-state")
    def update_mock_game(payload: GameStateRequest):
        game_session.update_from_lichess_state(payload.model_dump(exclude_none=True))
        return game_session.public_state()

    def _lichess_for_current_game():
        config = config_store.load()
        if not config.lichess_token:
            raise HTTPException(status_code=401, detail="Lichess is not connected")
        if not game_session.game_id:
            raise HTTPException(status_code=400, detail="No active game selected")
        return LichessClient(config.lichess_token), game_session.game_id

    @app.post("/api/game/resign")
    def resign_game():
        client, game_id = _lichess_for_current_game()
        client.resign(game_id)
        return {"ok": True}

    @app.post("/api/game/abort")
    def abort_game():
        client, game_id = _lichess_for_current_game()
        client.abort(game_id)
        return {"ok": True}

    @app.post("/api/game/draw/{answer}")
    def draw_game(answer: str):
        client, game_id = _lichess_for_current_game()
        client.handle_draw(game_id, accept=answer == "yes")
        return {"ok": True}

    @app.post("/api/lichess/token")
    def save_token(payload: TokenRequest):
        try:
            username = LichessClient(payload.token).validate_token()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        config_store.save_lichess_token(payload.token, username=username)
        return {"connected": True, "username": username}

    @app.post("/api/lichess/logout")
    def logout():
        config_store.delete_lichess_token()
        return {"connected": False}

    return app
