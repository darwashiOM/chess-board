from typing import Any

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.input_queue import InputQueue
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
    input_queue: InputQueue | None = None,
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
    input_queue = input_queue or InputQueue()
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

    class InputRequest(BaseModel):
        command: str

    class LedTestRequest(BaseModel):
        pattern: str

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

    def _phone_base_url() -> str:
        try:
            status = wifi_manager.status()
        except Exception:
            status = {}
        ip = status.get("ip") if isinstance(status, dict) else None
        if ip:
            return f"http://{ip}:8000"
        return wifi_manager.setup_url

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
      #kioskRoot { width: 100vw; height: 100vh; padding: 10px; display: grid; grid-template-rows: auto 1fr auto; gap: 8px; }
      header { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; border-bottom: 1px solid #3f3a31; padding-bottom: 6px; }
      h1 { font-size: clamp(20px, 5vw, 32px); margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .pill { color: #f4d35e; font-weight: 800; font-size: 14px; }
      .screen { min-height: 0; overflow: hidden; display: grid; gap: 8px; align-content: start; }
      .split { display: grid; grid-template-columns: minmax(128px, 40vh) 1fr; gap: 10px; min-height: 0; }
      .board { display: grid; grid-template-columns: repeat(8, 1fr); width: min(40vh, 42vw); border: 2px solid #6f6a60; }
      .sq { aspect-ratio: 1; display: grid; place-items: center; font-size: 10px; font-weight: 800; }
      .light { background: #eeeed2; color: #333; }
      .dark { background: #769656; color: #111; }
      .piece { width: 44%; height: 44%; border-radius: 50%; background: #1f1f1f; box-shadow: 0 0 0 3px #f8f8f8; }
      .list { display: grid; gap: 6px; max-height: 72vh; overflow: hidden; }
      .item { min-height: 42px; display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; border: 2px solid #4b453b; background: #26221d; color: #f0ede7; padding: 8px 10px; font-weight: 750; }
      .item.selected { background: #f4d35e; color: #161512; border-color: #fff0a8; }
      .item small { opacity: .82; font-weight: 700; }
      .meta { color: #d8d3c8; line-height: 1.35; display: grid; gap: 5px; }
      .status { min-height: 24px; color: #f4d35e; font-weight: 800; }
      .password { font-size: clamp(18px, 5vw, 28px); min-height: 42px; border: 2px solid #5b5548; padding: 7px 10px; background: #221f1a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .keyboard { display: grid; gap: 5px; }
      .keyRow { display: grid; gap: 5px; }
      .key { min-height: 38px; border: 2px solid #4b453b; background: #26221d; color: #f0ede7; display: grid; place-items: center; font-weight: 850; }
      .key.selected { background: #f4d35e; color: #161512; border-color: #fff0a8; }
      .qrGrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; align-items: start; }
      .qrCard { display: grid; gap: 6px; justify-items: center; text-align: center; font-weight: 800; }
      .qrCard img { width: min(28vw, 150px, 38vh); background: #fff; padding: 6px; }
      footer { display: grid; grid-template-columns: repeat(5, 1fr); gap: 5px; color: #d8d3c8; font-size: 12px; }
      footer span { text-align: center; border-top: 1px solid #3f3a31; padding-top: 5px; }
      code { color: #f4d35e; }
      @media (max-width: 560px), (max-height: 420px) {
        #kioskRoot { padding: 6px; gap: 5px; }
        header { padding-bottom: 4px; }
        h1 { font-size: 18px; }
        .split { grid-template-columns: 35vw 1fr; gap: 7px; }
        .board { width: 35vw; }
        .item { min-height: 34px; padding: 5px 7px; font-size: 13px; }
        .key { min-height: 31px; font-size: 13px; }
        .qrCard img { width: min(28vw, 112px, 34vh); }
        footer { font-size: 10px; }
      }
    </style>
  </head>
  <body data-stage="boot">
    <div id="kioskRoot">
      <header>
        <h1 id="screenTitle">Chess Board</h1>
        <div id="screenPill" class="pill">Starting</div>
      </header>
      <main id="screen" class="screen"></main>
      <footer><span>Up</span><span>Down</span><span>Left Back</span><span>Right Open</span><span>Select</span></footer>
    </div>
    <script>
      var squares = [];
      var files = "abcdefgh";
      for (var rank = 8; rank >= 1; rank--) {
        for (var fileIndex = 0; fileIndex < files.length; fileIndex++) squares.push(files[fileIndex] + rank);
      }
      var appEl = document.getElementById("screen");
      var titleEl = document.getElementById("screenTitle");
      var pillEl = document.getElementById("screenPill");
      var PASSWORD_ROWS = [
        ["a", "b", "c", "d", "e", "f", "g", "h"],
        ["i", "j", "k", "l", "m", "n", "o", "p"],
        ["q", "r", "s", "t", "u", "v", "w", "x"],
        ["y", "z", "0", "1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "!", "@", "#", "$"],
        ["%", "^", "&", "*", "?", "-", "_", "."],
        ["Shift", "Back", "Clear", "Connect"]
      ];
      var kioskState = {
        screen: "boot",
        selected: 0,
        gridRow: 0,
        gridCol: 0,
        networks: [],
        selectedSsid: "",
        password: "",
        shift: false,
        message: "",
        ledTest: "idle",
        lastCommand: "none",
        setupOverride: false
      };
      var latestState = null;
      var scanInFlight = false;
      var mainMenu = [
        ["Play", "playMenu"],
        ["Current Game", "game"],
        ["Tactics", "tactics"],
        ["Settings", "settings"],
        ["Diagnostics", "diagnostics"],
        ["Board Test", "boardTest"],
        ["LED Test", "ledTest"]
      ];
      var playMenu = [
        ["Random 3+2", function () { playAction("/api/play/seek", {timeMinutes: 3, increment: 2}); }],
        ["Random 5+0", function () { playAction("/api/play/seek", {timeMinutes: 5, increment: 0}); }],
        ["AI 3+2", function () { playAction("/api/play/ai", {level: 3, clockLimit: 180, increment: 2}); }],
        ["Friend Link", function () { playAction("/api/play/open", {timeMinutes: 3, increment: 2}); }],
        ["Daily Puzzle", function () { playAction("/api/puzzles/daily", {}); }],
        ["Tactics", function () { playAction("/api/puzzles/next", {}); }]
      ];
      function activeControlRoot() { return appEl; }
      function escapeHtml(value) {
        return String(value).replace(/[&<>"]/g, function (char) {
          return {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"}[char];
        });
      }
      function request(method, path, body, onOk, onError) {
        var xhr = new XMLHttpRequest();
        xhr.open(method, path, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function () {
          if (xhr.readyState !== 4) return;
          if (xhr.status >= 200 && xhr.status < 300) {
            var data = null;
            try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch (error) { data = xhr.responseText; }
            if (onOk) onOk(data, xhr);
          } else if (onError) {
            onError(xhr);
          }
        };
        xhr.onerror = function () { if (onError) onError(xhr); };
        xhr.send(body ? JSON.stringify(body) : null);
      }
      function stageForState(state) {
        if (!state || !state.wifi) return "boot";
        if (!state.wifi.connected || !(state.wifi.mode === "client" || state.wifi.mode === "wired")) return "wifi";
        if (!state.lichess || !state.lichess.connected) return "lichess";
        return "app";
      }
      function setHeader(title, pill) {
        titleEl.textContent = title;
        pillEl.textContent = pill || kioskState.lastCommand;
      }
      function selectedClass(index) { return index === kioskState.selected ? " selected" : ""; }
      function setScreen(screen) {
        kioskState.screen = screen;
        kioskState.selected = 0;
        kioskState.gridRow = 0;
        kioskState.gridCol = 0;
        renderScreen();
      }
      function syncStage() {
        var stage = stageForState(latestState);
        document.body.setAttribute("data-stage", stage);
        if (stage === "wifi" && kioskState.screen !== "wifiList" && kioskState.screen !== "wifiPassword" && kioskState.screen !== "wifiError") {
          kioskState.screen = "wifiList";
          scanWifi();
        } else if (stage === "lichess" && kioskState.screen !== "lichessSetup") {
          kioskState.screen = "lichessSetup";
        } else if (stage === "app" && !kioskState.setupOverride && (kioskState.screen === "boot" || kioskState.screen === "wifiList" || kioskState.screen === "wifiPassword" || kioskState.screen === "wifiError" || kioskState.screen === "lichessSetup")) {
          kioskState.screen = "mainMenu";
        }
      }
      function renderMenu(title, items, subtitle) {
        var html = '<section class="list">';
        setHeader(title, subtitle || "Menu");
        for (var i = 0; i < items.length; i++) {
          html += '<div class="item' + selectedClass(i) + '"><span>' + escapeHtml(items[i][0]) + '</span><small>' + (i === kioskState.selected ? "open" : "") + '</small></div>';
        }
        html += '</section><div class="status">' + escapeHtml(kioskState.message) + '</div>';
        appEl.innerHTML = html;
      }
      function renderWifiList() {
        var html = '<section class="list">';
        setHeader("Choose Wi-Fi", scanInFlight ? "Scanning" : "Required");
        for (var i = 0; i < kioskState.networks.length; i++) {
          var network = kioskState.networks[i];
          html += '<div class="item' + selectedClass(i) + '"><span>' + escapeHtml(network.ssid) + '</span><small>' + escapeHtml(network.signal || 0) + '%</small></div>';
        }
        html += '<div class="item' + selectedClass(kioskState.networks.length) + '"><span>Refresh Wi-Fi List</span><small>scan</small></div>';
        html += '</section><div class="status">' + escapeHtml(kioskState.message || "Select your network") + '</div>';
        appEl.innerHTML = html;
      }
      function displayKey(key) {
        return key.length === 1 && key >= "a" && key <= "z" && kioskState.shift ? key.toUpperCase() : key;
      }
      function renderWifiPassword() {
        var html = '<div class="password">' + (kioskState.password ? escapeHtml(kioskState.password.replace(/./g, "*")) : "Password") + '</div><section class="keyboard">';
        setHeader(kioskState.selectedSsid || "Wi-Fi Password", "Type");
        for (var r = 0; r < PASSWORD_ROWS.length; r++) {
          html += '<div class="keyRow" style="grid-template-columns: repeat(' + PASSWORD_ROWS[r].length + ', 1fr)">';
          for (var c = 0; c < PASSWORD_ROWS[r].length; c++) {
            html += '<div class="key' + (r === kioskState.gridRow && c === kioskState.gridCol ? " selected" : "") + '">' + escapeHtml(displayKey(PASSWORD_ROWS[r][c])) + '</div>';
          }
          html += '</div>';
        }
        html += '</section><div class="status">' + escapeHtml(kioskState.message || "Select Connect when done") + '</div>';
        appEl.innerHTML = html;
      }
      function renderLichessSetup() {
        setHeader("Connect Lichess", "Required");
        appEl.innerHTML = '<div class="qrGrid"><div class="qrCard"><div>Connect Lichess</div><img alt="Lichess OAuth QR code" src="/api/lichess-token-qr.svg"></div><div class="qrCard"><div>Get API Key</div><img alt="Get API Key QR code" src="/api/lichess-manual-token-qr.svg"></div><div class="qrCard"><div>Enter API Key</div><img alt="Enter API Key QR code" src="/api/phone-setup-qr.svg"></div></div><section class="list"><div class="item' + selectedClass(0) + '"><span>Check Connection</span><small>refresh</small></div><div class="item' + selectedClass(1) + '"><span>Open OAuth Here</span><small>/auth</small></div></section><div class="status">Scan on phone. The board continues automatically after token is saved.</div>';
      }
      function renderBoard() {
        var state = latestState || {};
        var sensors = state.sensors || {};
        var orientation = state.boardOrientation === "black" ? squares.slice().reverse() : squares;
        var html = '<div class="board">';
        for (var i = 0; i < orientation.length; i++) {
          var square = orientation[i];
          var file = square.charCodeAt(0) - 97;
          var rank = Number(square.charAt(1));
          html += '<div class="sq ' + ((file + rank) % 2 ? "light" : "dark") + '">' + (sensors[square] ? '<div class="piece"></div>' : '') + '</div>';
        }
        return html + '</div>';
      }
      function renderGame() {
        var game = latestState && latestState.game ? latestState.game : {clock: {whiteMs: null, blackMs: null}};
        var clock = game.clock || {whiteMs: null, blackMs: null};
        var sync = latestState && latestState.sync ? latestState.sync : {matches: false, missing: [], extra: []};
        setHeader("Current Game", sync.matches ? "Synced" : "Fix Board");
        appEl.innerHTML = '<div class="split">' + renderBoard() + '<div class="meta"><div>Game: <code>' + escapeHtml(game.id || "none") + '</code></div><div>Turn: <code>' + escapeHtml(game.turn || "white") + '</code></div><div>White: <code>' + formatClock(clock.whiteMs) + '</code></div><div>Black: <code>' + formatClock(clock.blackMs) + '</code></div><div>Last move: <code>' + escapeHtml(game.lastMove || "none") + '</code></div><div>Missing: <code>' + escapeHtml((sync.missing || []).join(", ") || "none") + '</code></div><div>Extra: <code>' + escapeHtml((sync.extra || []).join(", ") || "none") + '</code></div></div></div>';
      }
      function renderSettings() {
        var state = latestState || {};
        renderMenu("Settings", [["Lights " + (state.ledsEnabled ? "On" : "Off"), "toggle"], ["Brightness " + Math.round((state.ledBrightness || 0.1) * 100) + "%", "brightness"], ["Orientation " + (state.boardOrientation || "white"), "orientation"], ["Reconnect Wi-Fi", "wifi"], ["Disconnect Lichess", "logout"], ["Back", "back"]], "Board");
      }
      function renderDiagnostics() {
        var state = latestState || {};
        var wifi = state.wifi || {};
        var leds = state.leds || {};
        var sync = state.sync || {missing: [], extra: []};
        var occupied = occupiedSquares(state);
        setHeader("Diagnostics", "Hardware");
        appEl.innerHTML = '<div class="split">' + renderBoard() + '<div class="meta"><div>Wi-Fi: <code>' + escapeHtml(wifi.ssid || wifi.mode || "unknown") + '</code></div><div>IP: <code>' + escapeHtml(wifi.ip || "none") + '</code></div><div>Sensors active: <code>' + occupied.length + '/64</code></div><div>Occupied: <code>' + escapeHtml(occupied.join(", ") || "none") + '</code></div><div>LEDs: <code>' + escapeHtml(leds.mode || "unknown") + ' ' + Math.round((leds.brightness || 0) * 100) + '%</code></div><div>Missing: <code>' + escapeHtml((sync.missing || []).join(", ") || "none") + '</code></div><div>Extra: <code>' + escapeHtml((sync.extra || []).join(", ") || "none") + '</code></div></div></div>';
      }
      function occupiedSquares(state) {
        var occupied = [];
        state = state || {};
        for (var i = 0; i < squares.length; i++) if (state.sensors && state.sensors[squares[i]]) occupied.push(squares[i]);
        return occupied;
      }
      function renderBoardTest() {
        var sync = latestState && latestState.sync ? latestState.sync : {missing: [], extra: []};
        var occupied = occupiedSquares(latestState);
        setHeader("Board Test", occupied.length + "/64");
        appEl.innerHTML = '<div class="split">' + renderBoard() + '<div class="meta"><div>Place or remove pieces and watch the board update.</div><div>Active sensors: <code>' + occupied.length + '</code></div><div>Squares: <code>' + escapeHtml(occupied.join(", ") || "none") + '</code></div><div>Missing expected: <code>' + escapeHtml((sync.missing || []).join(", ") || "none") + '</code></div><div>Extra: <code>' + escapeHtml((sync.extra || []).join(", ") || "none") + '</code></div></div></div>';
      }
      function renderLedTest() {
        renderMenu("LED Test", [["All Lights", "all"], ["Border Chase", "border"], ["Square Test", "square"], ["Brightness Up", "up"], ["Brightness Down", "down"], ["Back", "back"]], kioskState.ledTest);
      }
      function renderScreen() {
        if (kioskState.screen === "boot") { setHeader("Chess Board", "Starting"); appEl.innerHTML = '<div class="status">Loading...</div>'; }
        else if (kioskState.screen === "wifiList") renderWifiList();
        else if (kioskState.screen === "wifiPassword") renderWifiPassword();
        else if (kioskState.screen === "wifiError") renderMenu("Wi-Fi Failed", [["Edit Password", "edit"], ["Choose Different Wi-Fi", "wifi"], ["Refresh Wi-Fi List", "scan"]], "Retry");
        else if (kioskState.screen === "lichessSetup") renderLichessSetup();
        else if (kioskState.screen === "mainMenu") renderMenu("Chess Board", mainMenu, latestState && latestState.lichess && latestState.lichess.username ? latestState.lichess.username : "Ready");
        else if (kioskState.screen === "playMenu") renderMenu("Play", playMenu, "Lichess");
        else if (kioskState.screen === "tactics") renderMenu("Tactics", [["Daily Puzzle", "daily"], ["Next Puzzle", "next"], ["Back", "back"]], "Puzzle");
        else if (kioskState.screen === "game") renderGame();
        else if (kioskState.screen === "settings") renderSettings();
        else if (kioskState.screen === "diagnostics") renderDiagnostics();
        else if (kioskState.screen === "boardTest") renderBoardTest();
        else if (kioskState.screen === "ledTest") renderLedTest();
      }
      function listLength() {
        if (kioskState.screen === "wifiList") return kioskState.networks.length + 1;
        if (kioskState.screen === "lichessSetup") return 2;
        if (kioskState.screen === "mainMenu") return mainMenu.length;
        if (kioskState.screen === "playMenu") return playMenu.length;
        if (kioskState.screen === "tactics") return 3;
        if (kioskState.screen === "settings") return 6;
        if (kioskState.screen === "ledTest") return 6;
        if (kioskState.screen === "wifiError") return 3;
        return 0;
      }
      function moveSelection(delta) { var length = listLength(); if (length) kioskState.selected = (kioskState.selected + delta + length) % length; }
      function moveKeyboard(rowDelta, colDelta) {
        kioskState.gridRow = (kioskState.gridRow + rowDelta + PASSWORD_ROWS.length) % PASSWORD_ROWS.length;
        var row = PASSWORD_ROWS[kioskState.gridRow];
        kioskState.gridCol = (kioskState.gridCol + colDelta + row.length) % row.length;
      }
      function goBack() {
        if (kioskState.screen === "wifiList" && kioskState.setupOverride) { kioskState.setupOverride = false; setScreen("mainMenu"); }
        else if (kioskState.screen === "wifiPassword" || kioskState.screen === "wifiError") setScreen("wifiList");
        else if (kioskState.screen === "playMenu" || kioskState.screen === "game" || kioskState.screen === "tactics" || kioskState.screen === "settings" || kioskState.screen === "diagnostics" || kioskState.screen === "boardTest" || kioskState.screen === "ledTest") setScreen("mainMenu");
      }
      function activateSelected() {
        if (kioskState.screen === "wifiList") {
          if (kioskState.selected >= kioskState.networks.length) { scanWifi(); return; }
          kioskState.selectedSsid = kioskState.networks[kioskState.selected].ssid;
          kioskState.password = "";
          setScreen("wifiPassword");
        } else if (kioskState.screen === "wifiPassword") pressPasswordKey(PASSWORD_ROWS[kioskState.gridRow][kioskState.gridCol]);
        else if (kioskState.screen === "wifiError") { if (kioskState.selected === 0) setScreen("wifiPassword"); else if (kioskState.selected === 1) setScreen("wifiList"); else scanWifi(); }
        else if (kioskState.screen === "lichessSetup") { if (kioskState.selected === 0) refresh(); else window.location.href = "/auth/lichess/start"; }
        else if (kioskState.screen === "mainMenu") setScreen(mainMenu[kioskState.selected][1]);
        else if (kioskState.screen === "playMenu") playMenu[kioskState.selected][1]();
        else if (kioskState.screen === "tactics") { if (kioskState.selected === 0) playAction("/api/puzzles/daily", {}); else if (kioskState.selected === 1) playAction("/api/puzzles/next", {}); else goBack(); }
        else if (kioskState.screen === "settings") settingsAction(kioskState.selected);
        else if (kioskState.screen === "ledTest") ledTestAction(kioskState.selected);
        renderScreen();
      }
      function pressPasswordKey(key) {
        if (key === "Shift") kioskState.shift = !kioskState.shift;
        else if (key === "Back") kioskState.password = kioskState.password.slice(0, -1);
        else if (key === "Clear") kioskState.password = "";
        else if (key === "Connect") connectWifi();
        else kioskState.password += displayKey(key);
      }
      function connectWifi() {
        kioskState.message = "Connecting to " + kioskState.selectedSsid + "...";
        renderScreen();
        request("POST", "/api/wifi/connect", {ssid: kioskState.selectedSsid, password: kioskState.password}, function () { kioskState.message = "Connected"; kioskState.setupOverride = false; refresh(); }, function () { kioskState.message = "Could not connect. Check password."; setScreen("wifiError"); });
      }
      function scanWifi() {
        if (scanInFlight) return;
        scanInFlight = true;
        kioskState.message = "Scanning Wi-Fi...";
        renderScreen();
        request("GET", "/api/wifi/scan", null, function (networks) { kioskState.networks = networks || []; kioskState.message = kioskState.networks.length ? "Select your network" : "No networks found"; scanInFlight = false; kioskState.selected = 0; renderScreen(); }, function () { kioskState.networks = []; kioskState.message = "Could not scan Wi-Fi"; scanInFlight = false; renderScreen(); });
      }
      function settingsAction(index) {
        var state = latestState || {};
        if (index === 0) saveSettings({ledsEnabled: !state.ledsEnabled});
        else if (index === 1) saveSettings({ledBrightness: Math.min(1, ((state.ledBrightness || 0.1) + 0.1))});
        else if (index === 2) saveSettings({boardOrientation: state.boardOrientation === "black" ? "white" : "black"});
        else if (index === 3) { kioskState.setupOverride = true; kioskState.networks = []; setScreen("wifiList"); scanWifi(); }
        else if (index === 4) request("POST", "/api/lichess/logout", null, function () { refresh(); });
        else goBack();
      }
      function ledTestAction(index) {
        if (index === 0) runLedTest("all", "All Lights");
        else if (index === 1) runLedTest("border", "Border Chase");
        else if (index === 2) runLedTest("square", "Square Test");
        else if (index === 3) saveSettings({ledsEnabled: true, ledBrightness: Math.min(1, ((latestState && latestState.ledBrightness) || 0.1) + 0.1)});
        else if (index === 4) saveSettings({ledBrightness: Math.max(0.01, ((latestState && latestState.ledBrightness) || 0.1) - 0.1)});
        else goBack();
      }
      function runLedTest(pattern, label) { request("POST", "/api/led/test", {pattern: pattern}, function () { kioskState.ledTest = label; refresh(); }, function () { kioskState.ledTest = "LED test unavailable"; renderScreen(); }); }
      function saveSettings(body) { request("POST", "/api/settings", body, function () { refresh(); }); }
      function playAction(path, body) { request("POST", path, body || {}, function () { kioskState.message = "Sent to Lichess"; refresh(); }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); }); }
      function formatClock(ms) { if (ms === null || ms === undefined) return "--"; var total = Math.max(0, Math.floor(ms / 1000)); return Math.floor(total / 60) + ":" + String(total % 60).replace(/^([0-9])$/, "0$1"); }
      function handleCommand(command) {
        kioskState.lastCommand = command;
        if (kioskState.screen === "wifiPassword") {
          if (command === "up") moveKeyboard(-1, 0);
          else if (command === "down") moveKeyboard(1, 0);
          else if (command === "left") moveKeyboard(0, -1);
          else if (command === "right") moveKeyboard(0, 1);
          else if (command === "select") activateSelected();
        } else {
          if (command === "up") moveSelection(-1);
          else if (command === "down") moveSelection(1);
          else if (command === "left") goBack();
          else if (command === "right" || command === "select") activateSelected();
        }
        renderScreen();
      }
      function pollInput() { request("GET", "/api/input", null, function (commands) { for (var i = 0; commands && i < commands.length; i++) handleCommand(commands[i]); }, function () { kioskState.lastCommand = "input offline"; }); }
      function refresh() { request("GET", "/api/state", null, function (state) { latestState = state; syncStage(); renderScreen(); }, function (xhr) { renderBootError(xhr); }); }
      function renderBootError(error) { setHeader("Chess Board", "Backend Error"); appEl.innerHTML = '<section class="list"><div class="item selected"><span>Waiting for backend</span><small>retrying</small></div></section><div class="status">Could not load /api/state</div>'; }
      document.addEventListener("keydown", function (event) {
        var keys = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "select"};
        if (keys[event.key]) { event.preventDefault(); handleCommand(keys[event.key]); }
      });
      renderScreen();
      refresh();
      setInterval(refresh, 1000);
      setInterval(pollInput, 80);
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

    @app.get("/api/input")
    def get_input():
        return input_queue.drain()

    @app.post("/api/input")
    def post_input(payload: InputRequest):
        try:
            input_queue.push(payload.command)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

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

    @app.get("/api/phone-setup-qr.svg")
    def phone_setup_qr():
        return Response(
            content=setup_url_qr_svg(f"{_phone_base_url()}/phone-setup"),
            media_type="image/svg+xml",
        )

    @app.get("/api/lichess-token-qr.svg")
    def lichess_token_qr():
        auth_url = f"{_phone_base_url()}/auth/lichess/start"
        return Response(
            content=setup_url_qr_svg(auth_url),
            media_type="image/svg+xml",
        )

    @app.get("/api/lichess-manual-token-qr.svg")
    def lichess_manual_token_qr():
        return Response(
            content=setup_url_qr_svg(config_store.public_state()["lichessTokenUrl"]),
            media_type="image/svg+xml",
        )

    @app.get("/phone-setup", response_class=HTMLResponse)
    def phone_setup():
        return HTMLResponse("""
<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chess Board Setup</title>
    <style>
      body { margin: 0; font-family: system-ui, sans-serif; background: #161512; color: #f0ede7; padding: 18px; }
      main { max-width: 520px; margin: 0 auto; display: grid; gap: 14px; }
      input, button { width: 100%; min-height: 48px; font-size: 17px; padding: 10px; box-sizing: border-box; }
      button { background: #769656; color: #111; border: 0; font-weight: 800; }
      .status { color: #f4d35e; font-weight: 800; min-height: 24px; }
    </style>
  </head>
  <body>
    <main>
      <h1>Chess Board Setup</h1>
      <p>Paste a Lichess API token with board play access. The board will save it automatically.</p>
      <input id="token" type="password" autocomplete="off" placeholder="Lichess API token">
      <button id="save">Send Token To Board</button>
      <div id="status" class="status"></div>
      <p><a style="color:#f4d35e" href="/auth/lichess/start">Connect with Lichess OAuth instead</a></p>
    </main>
    <script>
      document.getElementById("save").addEventListener("click", function () {
        var token = document.getElementById("token").value.replace(/^\\s+|\\s+$/g, "");
        var status = document.getElementById("status");
        var xhr = new XMLHttpRequest();
        status.textContent = "Sending...";
        xhr.open("POST", "/api/lichess/token", true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function () {
          if (xhr.readyState !== 4) return;
          if (xhr.status >= 200 && xhr.status < 300) {
            status.textContent = "Saved. You can return to the board.";
            document.getElementById("token").value = "";
          } else {
            status.textContent = "Could not save token: " + (xhr.responseText || xhr.status);
          }
        };
        xhr.send(JSON.stringify({token: token}));
      });
    </script>
  </body>
</html>
""")

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

    @app.post("/api/led/test")
    def led_test(payload: LedTestRequest):
        try:
            run_test = getattr(led_controller, "run_test")
            run_test(payload.pattern)
        except AttributeError as exc:
            raise HTTPException(status_code=501, detail="LED test is not supported by this controller") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return led_controller.status()

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
