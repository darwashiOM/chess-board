from typing import Any

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.leds import DisabledLedController, LedSettings
from chessboard_app.lichess_client import LichessClient
from chessboard_app.lichess_oauth import LichessOAuth
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
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
    oauth_sessions = {}
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

    class FriendChallengeRequest(BaseModel):
        username: str
        clockLimit: int = 180
        increment: int = 2
        rated: bool = False
        color: str = "random"
        variant: str = "standard"

    class AiChallengeRequest(BaseModel):
        level: int = 3
        clockLimit: int = 180
        increment: int = 2
        color: str = "random"
        variant: str = "standard"

    class SeekRequest(BaseModel):
        timeMinutes: int = 3
        increment: int = 2
        rated: bool = False
        color: str = "random"
        variant: str = "standard"

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
      nav { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
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
      .setupScreen { display: none; width: 100vw; height: 100vh; padding: 12px; place-items: center; text-align: center; }
      .setupBox { max-width: 480px; display: grid; gap: 10px; justify-items: center; }
      .setupBox img { width: min(240px, 72vw, 60vh); background: #fff; padding: 8px; }
      body[data-stage="wifi"] #appShell, body[data-stage="lichess"] #appShell { display: none; }
      body[data-stage="wifi"] #wifiSetupScreen { display: grid; }
      body[data-stage="lichess"] #lichessSetupScreen { display: grid; }
      @media (max-width: 560px), (max-height: 420px) {
        main { padding: 6px; gap: 6px; }
        h1 { display: none; }
        nav { grid-template-columns: repeat(6, 1fr); }
        nav button { min-height: 36px; padding: 4px; font-size: 12px; }
        .layout { grid-template-columns: 39vw 1fr; gap: 8px; }
        .grid { width: 39vw; }
        .row { padding: 5px 0; font-size: 13px; }
        button, input, select { min-height: 36px; font-size: 13px; }
      }
    </style>
  </head>
  <body>
    <section id="wifiSetupScreen" class="setupScreen">
      <div class="setupBox">
        <h1>Set Up Board Wi-Fi</h1>
        <div>1. Scan to join the board setup network.</div>
        <img alt="Board setup network QR code" src="/api/setup-qr.svg">
        <div><code>ChessBoard-Setup</code> / <code>chessboard</code></div>
        <div>2. Scan to open the setup page.</div>
        <img alt="Board setup page QR code" src="/api/setup-page-qr.svg">
        <div><code>http://10.42.0.1:8000</code></div>
        <form id="mainWifiForm">
          <input id="mainWifiSsid" type="text" placeholder="Home Wi-Fi name">
          <input id="mainWifiPassword" type="password" placeholder="Home Wi-Fi password">
          <button class="primary">Send Wi-Fi To Board</button>
        </form>
      </div>
    </section>
    <section id="lichessSetupScreen" class="setupScreen">
      <div class="setupBox">
        <h1>Connect Lichess</h1>
        <img alt="Lichess OAuth QR code" src="/api/lichess-token-qr.svg">
        <div>Scan with your phone, approve Lichess, then return here.</div>
        <a href="/auth/lichess/start">Connect on this screen</a>
      </div>
    </section>
    <div id="appShell">
    <main>
      <header>
        <h1 id="title">ChessBoard</h1>
        <nav>
          <button class="tabButton active" data-tab="home">Home</button>
          <button class="tabButton" data-tab="play">Play</button>
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
            <p><a id="oauthLink" href="/auth/lichess/start">Connect Lichess from phone</a></p>
            <p><a id="tokenLink" href="https://lichess.org/account/oauth/token/create?scopes[]=board:play" target="_blank" rel="noreferrer">Manual token fallback</a></p>
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
          <div id="play" class="tab">
            <div class="row"><span>Preset</span><code>3+2</code></div>
            <div class="field">
              <label for="friendUsername">Friend username</label>
              <input id="friendUsername" type="text" placeholder="lichess username">
            </div>
            <div class="actions">
              <button id="challengeFriend" class="primary" type="button">Play Friend 3+2</button>
              <button id="challengeAi" type="button">Play AI 3+2</button>
              <button id="seekGame" type="button">Random 3+2</button>
              <button id="openChallenge" type="button">Friend Link</button>
              <button id="dailyPuzzle" type="button">Daily Puzzle</button>
              <button id="nextPuzzle" type="button">Tactics</button>
            </div>
            <div id="playStatus"></div>
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
            <div class="row"><span>Board setup network</span><code id="setupSsid">ChessBoard-Setup</code></div>
            <div class="row"><span>Setup password</span><code id="setupPassword">chessboard</code></div>
            <div class="row"><span>Setup page</span><code id="setupUrl">http://10.42.0.1:8000</code></div>
            <img id="setupQr" alt="Board setup network QR code" src="/api/setup-qr.svg" style="width:min(180px,65vw);background:#fff;padding:8px;margin:8px 0;">
            <img id="setupPageQr" alt="Board setup page QR code" src="/api/setup-page-qr.svg" style="width:min(180px,65vw);background:#fff;padding:8px;margin:8px 0;">
            <form id="wifiForm">
              <div class="field">
                <label for="wifiSsidInput">SSID</label>
                <input id="wifiSsidInput" type="text">
              </div>
              <div class="field">
                <label for="wifiPassword">Password</label>
                <input id="wifiPassword" type="password">
              </div>
              <button class="primary">Send Wi-Fi To Board</button>
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
    </div>
    <script>
      const squares = [];
      for (let rank = 8; rank >= 1; rank--) {
        for (const file of "abcdefgh") squares.push(file + rank);
      }
      const boardEl = document.getElementById("board");
      const statusEl = document.getElementById("status");
      const titleEl = document.getElementById("title");
      const tabOrder = ["home", "play", "game", "settings", "wifi", "diagnostics"];
      let latestState = null;
      function render(state) {
        latestState = state;
        document.body.dataset.stage = state.wifi.mode !== "client" ? "wifi" : (state.lichess.connected ? "app" : "lichess");
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
        document.getElementById("setupPageQr").style.display = state.wifi.mode === "client" ? "none" : "block";
        document.getElementById("rawSensorDetails").textContent = JSON.stringify(state.sensorDetails, null, 2);
        maybeShowSetupTab(state);
      }
      function maybeShowSetupTab(state) {
        if (document.body.dataset.stage !== "app") return;
        if (window.userSelectedTab) return;
        if (state.wifi.mode !== "client") {
          activateTab("wifi");
        } else if (!state.lichess.connected) {
          activateTab("home");
        }
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
      document.getElementById("mainWifiForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        await fetch("/api/wifi/connect", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            ssid: document.getElementById("mainWifiSsid").value,
            password: document.getElementById("mainWifiPassword").value
          })
        });
        document.getElementById("mainWifiPassword").value = "";
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
      async function playAction(path, body) {
        const res = await fetch(path, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body || {})
        });
        const text = await res.text();
        document.getElementById("playStatus").textContent = res.ok ? text : `Error: ${text}`;
        await refresh();
      }
      document.getElementById("challengeFriend").addEventListener("click", () => playAction("/api/play/friend", {
        username: document.getElementById("friendUsername").value,
        clockLimit: 180,
        increment: 2
      }));
      document.getElementById("challengeAi").addEventListener("click", () => playAction("/api/play/ai", {
        level: 3,
        clockLimit: 180,
        increment: 2
      }));
      document.getElementById("seekGame").addEventListener("click", () => playAction("/api/play/seek", {
        timeMinutes: 3,
        increment: 2
      }));
      document.getElementById("openChallenge").addEventListener("click", () => playAction("/api/play/open", {
        timeMinutes: 3,
        increment: 2
      }));
      document.getElementById("dailyPuzzle").addEventListener("click", () => playAction("/api/puzzles/daily"));
      document.getElementById("nextPuzzle").addEventListener("click", () => playAction("/api/puzzles/next"));
      for (const button of document.querySelectorAll(".tabButton")) {
        button.addEventListener("click", () => {
          window.userSelectedTab = true;
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
          window.userSelectedTab = true;
          activateRelativeTab(-1);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          window.userSelectedTab = true;
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

    @app.get("/auth/lichess/start")
    def lichess_oauth_start(request: Request):
        redirect_uri = str(request.url_for("lichess_oauth_callback"))
        session, url = LichessOAuth().start(redirect_uri)
        oauth_sessions[session.state] = session
        return RedirectResponse(url)

    @app.get("/auth/lichess/callback")
    def lichess_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
        if error:
            raise HTTPException(status_code=400, detail=error)
        if not code or not state or state not in oauth_sessions:
            raise HTTPException(status_code=400, detail="Invalid Lichess OAuth callback")
        session = oauth_sessions.pop(state)
        token = LichessOAuth().finish(session, code)
        username = LichessClient(token).validate_token()
        config_store.save_lichess_token(token, username=username)
        return HTMLResponse("""
<!doctype html>
<html>
  <head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lichess Connected</title></head>
  <body style="font-family: system-ui, sans-serif; background:#161512; color:#f0ede7;">
    <h1>Lichess connected</h1>
    <p>You can return to the chessboard screen.</p>
  </body>
</html>
""")

    @app.get("/api/setup-qr.svg")
    def setup_qr():
        return Response(
            content=setup_wifi_qr_svg(wifi_manager.setup_ssid, wifi_manager.setup_password),
            media_type="image/svg+xml",
        )

    @app.get("/api/setup-page-qr.svg")
    def setup_page_qr():
        return Response(
            content=setup_url_qr_svg(wifi_manager.setup_url),
            media_type="image/svg+xml",
        )

    @app.get("/api/lichess-token-qr.svg")
    def lichess_token_qr(request: Request):
        auth_url = str(request.url_for("lichess_oauth_start"))
        return Response(
            content=setup_url_qr_svg(auth_url),
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

    def _lichess_client():
        config = config_store.load()
        if not config.lichess_token:
            raise HTTPException(status_code=401, detail="Lichess is not connected")
        return LichessClient(config.lichess_token)

    @app.post("/api/play/friend")
    def play_friend(payload: FriendChallengeRequest):
        if not payload.username.strip():
            raise HTTPException(status_code=400, detail="Friend username is required")
        return _lichess_client().challenge_friend(
            payload.username.strip(),
            clock_limit=payload.clockLimit,
            increment=payload.increment,
            rated=payload.rated,
            color=payload.color,
            variant=payload.variant,
        )

    @app.post("/api/play/ai")
    def play_ai(payload: AiChallengeRequest):
        return _lichess_client().challenge_ai(
            level=payload.level,
            clock_limit=payload.clockLimit,
            increment=payload.increment,
            color=payload.color,
            variant=payload.variant,
        )

    @app.post("/api/play/seek")
    def play_seek(payload: SeekRequest):
        return _lichess_client().create_seek(
            time_minutes=payload.timeMinutes,
            increment=payload.increment,
            rated=payload.rated,
            color=payload.color,
            variant=payload.variant,
        )

    @app.post("/api/play/open")
    def play_open(payload: SeekRequest):
        return _lichess_client().open_challenge(
            clock_limit=payload.timeMinutes * 60,
            increment=payload.increment,
            rated=payload.rated,
            name="ChessBoard",
            variant=payload.variant,
        )

    @app.post("/api/puzzles/daily")
    def daily_puzzle():
        return _lichess_client().daily_puzzle()

    @app.post("/api/puzzles/next")
    def next_puzzle():
        return _lichess_client().next_puzzle()

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
