from typing import Any

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.input_queue import InputQueue
from chessboard_app.leds import DisabledLedController, LedSettings
from chessboard_app.lichess_client import LichessClient
from chessboard_app.lichess_oauth import LichessOAuth
from chessboard_app.orientation import orient_occupancy, orient_square, normalize_orientation
from chessboard_app.sensors import StaticSensorReader, sensor_details
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
    game_session = game_session or GameSession()
    orientation = _active_orientation(state.get("boardOrientation"), game_session)
    raw_snapshot = sensor_reader.read().as_dict()
    snapshot = orient_occupancy(raw_snapshot, orientation)
    wifi_manager = wifi_manager or WifiManager()
    led_controller = led_controller or DisabledLedController()
    led_controller.apply_settings(LedSettings(
        enabled=state["ledsEnabled"],
        brightness=state["ledBrightness"],
        orientation=orientation,
    ))
    sync = game_session.sync_status(snapshot)
    _auto_accept_ready_puzzle_move(game_session, snapshot, allow_unsynced=bool(state.get("testMode")))
    sync = game_session.sync_status(snapshot)
    if sync.get("matches") and getattr(game_session, "auto_mark_synced", lambda: False)():
        game_session.mark_synced(snapshot)
    update_led_display(
        led_controller,
        game_session,
        sync,
        snapshot,
        test_mode=bool(state.get("testMode")),
    )
    led_status = led_controller.status()
    sensor_status = getattr(sensor_reader, "status", lambda: "ok")()
    state["hardware"] = {
        "sensors": sensor_status,
        "leds": led_status["mode"],
    }
    sensor_error = getattr(sensor_reader, "error", None)
    if sensor_error:
        state["hardware"]["sensorError"] = sensor_error
    state["leds"] = led_status
    state["sensors"] = snapshot
    state["sensorDetails"] = _sensor_details_for_snapshot(sensor_reader, raw_snapshot, snapshot, orientation)
    state["game"] = game_session.public_state()
    state["sync"] = sync
    state["wifi"] = wifi_manager.status()
    return state


def build_live_state(
    sensor_reader: Any,
    game_session: GameSession | None = None,
    led_controller: Any | None = None,
    test_mode: bool = False,
    board_orientation: str = "white",
) -> dict[str, Any]:
    game_session = game_session or GameSession()
    orientation = _active_orientation(board_orientation, game_session)
    raw_snapshot = sensor_reader.read().as_dict()
    snapshot = orient_occupancy(raw_snapshot, orientation)
    led_controller = led_controller or DisabledLedController()
    current_led_settings = getattr(led_controller, "settings", LedSettings())
    led_controller.apply_settings(LedSettings(
        enabled=getattr(current_led_settings, "enabled", False),
        brightness=getattr(current_led_settings, "brightness", 0.1),
        orientation=orientation,
    ))
    sync = game_session.sync_status(snapshot)
    _auto_accept_ready_puzzle_move(game_session, snapshot, allow_unsynced=test_mode)
    sync = game_session.sync_status(snapshot)
    if sync.get("matches") and getattr(game_session, "auto_mark_synced", lambda: False)():
        game_session.mark_synced(snapshot)
    update_led_display(led_controller, game_session, sync, snapshot, test_mode=test_mode)
    sensor_status = getattr(sensor_reader, "status", lambda: "ok")()
    state = {
        "hardware": {
            "sensors": sensor_status,
            "leds": led_controller.status()["mode"],
        },
        "leds": led_controller.status(),
        "sensors": snapshot,
        "sensorDetails": _sensor_details_for_snapshot(sensor_reader, raw_snapshot, snapshot, orientation),
        "game": game_session.public_state(),
        "sync": sync,
    }
    sensor_error = getattr(sensor_reader, "error", None)
    if sensor_error:
        state["hardware"]["sensorError"] = sensor_error
    return state


def _active_orientation(board_orientation: str | None, game_session: GameSession) -> str:
    if game_session.player_color in {"white", "black"}:
        return game_session.player_color
    return normalize_orientation(board_orientation)


def _read_oriented_snapshot(sensor_reader: Any, board_orientation: str | None, game_session: GameSession) -> dict[str, bool]:
    return orient_occupancy(sensor_reader.read().as_dict(), _active_orientation(board_orientation, game_session))


def _sensor_details_for_snapshot(
    sensor_reader: Any,
    raw_snapshot: dict[str, bool],
    snapshot: dict[str, bool],
    orientation: str,
) -> dict[str, dict[str, object]]:
    raw_details = sensor_details(raw_snapshot)
    details = {}
    for logical_square, active in snapshot.items():
        physical_square = orient_square(logical_square, orientation)
        value = dict(raw_details[physical_square])
        value["active"] = bool(active)
        value["physicalSquare"] = physical_square
        details[logical_square] = value
    sensor_error = getattr(sensor_reader, "error", None)
    if sensor_error:
        for value in details.values():
            value["error"] = sensor_error
    return details


def update_led_display(
    led_controller: Any,
    game_session: GameSession,
    sync: dict[str, Any],
    actual_occupancy: dict[str, bool] | None = None,
    test_mode: bool = False,
) -> None:
    settings = getattr(led_controller, "settings", LedSettings())
    if not settings.enabled:
        return

    missing = list(sync.get("missing", []))
    extra = list(sync.get("extra", []))
    occupied = [
        square
        for square, is_occupied in (actual_occupancy or {}).items()
        if is_occupied
    ]
    if _should_show_setup_guidance(game_session):
        led_controller.show_setup_guidance(
            missing,
            extra,
            frame=0,
            occupied_squares=occupied,
            expected_board=game_session.board,
            expected_player_color=game_session.player_color,
        )
        return

    if test_mode:
        lifted_square = _test_mode_lifted_square(game_session, actual_occupancy or {})
        if lifted_square:
            led_controller.show_legal_targets(game_session.board, lifted_square)
            return

    if sync.get("matches"):
        getattr(led_controller, "clear", lambda: None)()
        return

    if len(missing) == 1 and not extra:
        led_controller.show_legal_targets(game_session.board, missing[0])
        return

    if game_session.last_move:
        led_controller.show_move(game_session.last_move)


def _should_show_setup_guidance(game_session: GameSession) -> bool:
    if game_session.mode == "puzzle" and game_session.status == "puzzle_setup":
        return True
    return game_session.mode == "game" and game_session.status == "idle"


def _test_mode_lifted_square(game_session: GameSession, actual_occupancy: dict[str, bool]) -> str | None:
    if game_session.last_occupancy is None:
        return None
    lifted = [
        square
        for square, was_occupied in game_session.last_occupancy.items()
        if was_occupied and not actual_occupancy.get(square, False)
    ]
    placed = [
        square
        for square, is_occupied in actual_occupancy.items()
        if is_occupied and not game_session.last_occupancy.get(square, False)
    ]
    if len(lifted) == 1 and not placed:
        return lifted[0]
    return None


def _auto_accept_ready_puzzle_move(
    game_session: GameSession,
    snapshot: dict[str, bool],
    allow_unsynced: bool = False,
) -> None:
    if game_session.mode != "puzzle" or game_session.status != "puzzle_play":
        return
    result = game_session.detect_move_from_last_snapshot(snapshot, allow_unsynced=allow_unsynced)
    if result.kind != "move" or not result.uci:
        return
    if result.uci != game_session._next_solution_move():
        return
    game_session.submit_puzzle_move(snapshot, allow_unsynced=allow_unsynced)


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
        testMode: bool | None = None

    class WifiConnectRequest(BaseModel):
        ssid: str
        password: str = ""

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
    <title>Light Mate</title>
    <style>
      * { box-sizing: border-box; }
      :root {
        --porcelain: #faf8f4;
        --paper: #fffefd;
        --charcoal: #2c2b2f;
        --graphite: #5b5a5c;
        --stone: #c9bc9d;
        --line: #e1d6bf;
        --gold: #d7b973;
        --gold-deep: #9a7834;
        --gold-soft: #f4ead2;
        --danger: #b4554e;
      }
      body { margin: 0; font-family: system-ui, sans-serif; background: radial-gradient(circle at top left, #ffffff 0, var(--porcelain) 42%, #f0e9dd 100%); color: var(--charcoal); overflow: hidden; }
      #kioskRoot { width: 100vw; height: 100vh; padding: 10px; display: grid; grid-template-rows: auto 1fr auto; gap: 8px; }
      header { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; border-bottom: 1px solid var(--line); padding-bottom: 7px; }
      .brandBlock { display: grid; gap: 1px; min-width: 0; }
      .brandName { font-size: 13px; font-weight: 760; letter-spacing: .28em; text-transform: uppercase; white-space: nowrap; color: var(--charcoal); }
      .brandName .mate { color: var(--gold-deep); }
      h1 { font-size: clamp(18px, 4vw, 27px); margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 780; }
      .pill { background: var(--charcoal); color: var(--gold); border: 1px solid var(--gold); border-radius: 999px; padding: 5px 9px; font-weight: 850; font-size: 13px; box-shadow: 0 5px 16px rgba(44, 43, 47, .12); }
      .screen { min-height: 0; overflow: hidden; display: grid; gap: 8px; align-content: start; }
      .split { display: grid; grid-template-columns: minmax(128px, 40vh) 1fr; gap: 10px; min-height: 0; }
      .board { display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); width: min(40vh, 42vw); aspect-ratio: 1; border: 2px solid var(--gold-deep); box-shadow: 0 14px 35px rgba(44, 43, 47, .16); }
      .sq { aspect-ratio: 1; display: grid; place-items: center; font-size: 10px; font-weight: 800; position: relative; min-width: 0; min-height: 0; overflow: hidden; }
      .coord { position: absolute; z-index: 2; pointer-events: none; color: var(--gold-deep); font-size: 9px; font-weight: 900; line-height: 1; text-shadow: 0 1px 1px rgba(255, 255, 255, .65); }
      .fileCoord { left: 50%; bottom: 2px; transform: translateX(-50%); text-transform: uppercase; }
      .rankCoord { top: 50%; transform: translateY(-50%); }
      .leftRank { left: 2px; }
      .rightRank { right: 2px; }
      .light { background: #fffdf8; color: var(--charcoal); }
      .dark { background: #d7c99f; color: var(--charcoal); }
      .piece { width: 44%; height: 44%; border-radius: 50%; background: var(--charcoal); box-shadow: 0 0 0 3px #fffaf1, 0 4px 10px rgba(44, 43, 47, .22); }
      .svgPiece { width: 94%; height: 94%; display: block; filter: drop-shadow(0 2px 2px rgba(44, 43, 47, .22)); }
      .piece-blue { fill: #1967d2; stroke: #0b376f; stroke-width: 2.4px; paint-order: stroke fill; }
      .piece-yellow { fill: #f4c84a; stroke: #8d6d13; stroke-width: 2.4px; paint-order: stroke fill; }
      .sq.target::after { content: ""; position: absolute; width: 52%; height: 52%; border-radius: 50%; border: 3px solid #1967d2; background: rgba(25, 103, 210, .22); box-shadow: 0 0 0 2px rgba(244, 200, 74, .72), 0 0 16px rgba(25, 103, 210, .45); z-index: 1; pointer-events: none; }
      .list { display: grid; gap: 6px; max-height: 72vh; overflow: hidden; }
      .item { min-height: 42px; display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; border: 2px solid var(--line); background: rgba(255, 254, 253, .92); color: var(--charcoal); padding: 8px 10px; font-weight: 760; box-shadow: 0 6px 18px rgba(44, 43, 47, .06); }
      .item.selected { background: linear-gradient(90deg, var(--gold-soft), #fffefd); color: var(--charcoal); border-color: var(--gold); box-shadow: inset 4px 0 0 var(--gold-deep), 0 10px 26px rgba(154, 120, 52, .18); }
      .item small { opacity: .82; font-weight: 700; }
      .meta { color: var(--graphite); line-height: 1.35; display: grid; gap: 5px; background: rgba(255, 254, 253, .72); border: 1px solid var(--line); padding: 8px; }
      .status { min-height: 24px; color: var(--gold-deep); font-weight: 850; }
      .password { font-size: clamp(18px, 5vw, 28px); min-height: 42px; border: 2px solid var(--line); padding: 7px 10px; background: var(--paper); color: var(--charcoal); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; box-shadow: inset 0 0 0 1px #fff; }
      .keyboard { display: grid; gap: 5px; }
      .keyRow { display: grid; gap: 5px; }
      .key { min-height: 38px; border: 2px solid var(--line); background: rgba(255, 254, 253, .94); color: var(--charcoal); display: grid; place-items: center; font-weight: 850; box-shadow: 0 5px 14px rgba(44, 43, 47, .05); }
      .key.selected { background: var(--charcoal); color: var(--gold); border-color: var(--gold); }
      .qrGrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; align-items: start; }
      .qrCard { display: grid; gap: 6px; justify-items: center; text-align: center; font-weight: 850; background: var(--paper); border: 1px solid var(--line); padding: 9px; box-shadow: 0 10px 30px rgba(44, 43, 47, .08); }
      .qrCard img { width: min(28vw, 150px, 38vh); background: #fff; padding: 6px; border: 1px solid var(--gold-soft); }
      .wifiStatus { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: center; border: 2px solid var(--line); background: rgba(255, 254, 253, .88); padding: 8px 10px; font-weight: 820; box-shadow: 0 8px 24px rgba(44, 43, 47, .07); }
      .wifiStrength { display: inline-grid; grid-template-columns: repeat(4, 7px); gap: 3px; align-items: end; margin-right: 6px; vertical-align: -2px; }
      .wifiBar { width: 7px; background: #eee7da; border: 1px solid var(--stone); }
      .wifiBar:nth-child(1) { height: 7px; }
      .wifiBar:nth-child(2) { height: 11px; }
      .wifiBar:nth-child(3) { height: 15px; }
      .wifiBar:nth-child(4) { height: 19px; }
      .wifiBar.on { background: var(--gold); border-color: var(--gold-deep); }
      footer { display: grid; grid-template-columns: repeat(5, 1fr); gap: 5px; color: var(--graphite); font-size: 12px; }
      footer span { text-align: center; border-top: 1px solid var(--line); padding-top: 5px; }
      code { color: var(--gold-deep); font-weight: 850; }
      @media (max-width: 560px), (max-height: 420px) {
        #kioskRoot { padding: 6px; gap: 5px; }
        header { padding-bottom: 4px; }
        .brandName { font-size: 10px; letter-spacing: .2em; }
        h1 { font-size: 17px; }
        .split { grid-template-columns: 35vw 1fr; gap: 7px; }
        .board { width: 35vw; }
        .coord { font-size: 8px; }
        .item { min-height: 34px; padding: 5px 7px; font-size: 13px; }
        .key { min-height: 31px; font-size: 13px; }
        .qrCard img { width: min(28vw, 112px, 34vh); }
        .wifiStatus { grid-template-columns: 1fr; gap: 5px; padding: 5px 7px; font-size: 13px; }
        footer { font-size: 10px; }
      }
    </style>
  </head>
  <body data-stage="boot">
    <div id="kioskRoot">
      <header>
        <div class="brandBlock">
          <div class="brandName"><span>LIGHT</span> <span class="mate">MATE</span></div>
          <h1 id="screenTitle">Chess Board</h1>
        </div>
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
        selectedSecurity: "",
        password: "",
        shift: false,
        message: "",
        ledTest: "idle",
        lastCommand: "none",
        setupOverride: false,
        confirmResign: false,
        pendingStart: null,
        pendingStartInFlight: false
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
        ["Play Computer", function () { startComputerGame(); }],
        ["Friend Link", function () { playAction("/api/play/open", {timeMinutes: 3, increment: 2}); }],
        ["Daily Puzzle", function () { fetchPuzzle("/api/puzzles/daily"); }],
        ["Tactics", function () { setScreen("tactics"); }]
      ];
      function activeControlRoot() { return appEl; }
      function escapeHtml(value) {
        return String(value).replace(/[&<>"]/g, function (char) {
          if (char === "&") return "&amp;";
          if (char === "<") return "&lt;";
          if (char === ">") return "&gt;";
          return "&quot;";
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
      function errorDetail(xhr) {
        try {
          var data = JSON.parse(xhr.responseText || "{}");
          return data.detail || data;
        } catch (error) {
          return xhr.responseText || xhr.status;
        }
      }
      function errorMessage(xhr, fallback) {
        var detail = errorDetail(xhr);
        if (detail && detail.message) return detail.message;
        if (typeof detail === "string") return detail;
        return fallback || "Request failed";
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
          var security = network.security ? network.security : "Open";
          html += '<div class="item' + selectedClass(i) + '"><span>' + escapeHtml(network.ssid) + '</span><small>' + escapeHtml(network.signal || 0) + '% ' + escapeHtml(security) + '</small></div>';
        }
        html += '<div class="item' + selectedClass(kioskState.networks.length) + '"><span>Refresh Wi-Fi List</span><small>scan</small></div>';
        html += '</section><div class="status">' + escapeHtml(kioskState.message || "Select your network") + '</div>';
        appEl.innerHTML = html;
      }
      function isOpenNetwork(network) {
        return !network.security || network.security === "--" || network.security === "none";
      }
      function displayKey(key) {
        return key.length === 1 && key >= "a" && key <= "z" && kioskState.shift ? key.toUpperCase() : key;
      }
      function wifiSignalBars(signal) {
        var percent = Number(signal || 0);
        var active = percent >= 75 ? 4 : percent >= 50 ? 3 : percent >= 25 ? 2 : percent > 0 ? 1 : 0;
        var html = '<span class="wifiStrength" aria-hidden="true">';
        for (var i = 1; i <= 4; i++) html += '<span class="wifiBar' + (i <= active ? " on" : "") + '"></span>';
        return html + '</span>';
      }
      function renderWifiStatus() {
        var state = latestState || {};
        var wifi = state.wifi || {};
        var lichess = state.lichess || {};
        var ssid = wifi.connected ? (wifi.ssid || wifi.mode || "connected") : "not connected";
        var signal = wifi.signal || 0;
        var signalText = signal ? " " + signal + "%" : "";
        return '<div class="wifiStatus"><div>' + wifiSignalBars(signal) + 'Wi-Fi: <code>' + escapeHtml(ssid) + '</code>' + escapeHtml(signalText) + '</div><div>Lichess: <code>' + escapeHtml(lichess.connected ? (lichess.username || "connected") : "not connected") + '</code></div></div>';
      }
      function renderWifiPassword() {
        var html = '<div class="password">' + (kioskState.password ? escapeHtml(kioskState.password.replace(/./g, "*")) : "Password") + '</div><section class="keyboard">';
        setHeader(kioskState.selectedSsid || "Wi-Fi Password", kioskState.selectedSecurity || "Type");
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
        appEl.innerHTML = renderWifiStatus() + '<div class="qrGrid"><div class="qrCard"><div>Connect Lichess</div><img alt="Lichess OAuth QR code" src="/api/lichess-token-qr.svg"></div></div><div class="status">Scan on phone. The board continues automatically after Lichess connects.</div>';
      }
      function squareCoordinateLabels(square, row, col) {
        var file = square.charAt(0);
        var rank = square.charAt(1);
        var html = "";
        if (row === 7) html += '<span class="coord fileCoord">' + escapeHtml(file) + '</span>';
        if (col === 0) html += '<span class="coord rankCoord leftRank">' + escapeHtml(rank) + '</span>';
        if (col === 7) html += '<span class="coord rankCoord rightRank">' + escapeHtml(rank) + '</span>';
        return html;
      }
      function pieceSvg(piece, playerColor) {
        var symbols = {
          K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
          k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟"
        };
        var symbol = symbols[piece] || "";
        if (!symbol) return "";
        var scale = pieceScale(piece);
        var colorClass = pieceColorClass(piece, playerColor);
        return '<svg class="svgPiece" viewBox="0 0 100 100" role="img" aria-label="' + escapeHtml(piece) + '">' +
          '<text class="' + colorClass + '" x="50" y="' + scale.y + '" text-anchor="middle" font-size="' + scale.size + '" font-family="Arial Unicode MS, DejaVu Sans, Segoe UI Symbol, Georgia, serif" font-weight="700">' + symbol + '</text>' +
          '</svg>';
      }
      function pieceColorClass(piece, playerColor) {
        var isWhite = piece === piece.toUpperCase();
        if (playerColor === "black") return isWhite ? "piece-blue" : "piece-yellow";
        return isWhite ? "piece-yellow" : "piece-blue";
      }
      function pieceScale(piece) {
        var scales = {
          P: {size: 72, y: 71}, p: {size: 72, y: 71},
          B: {size: 92, y: 79}, b: {size: 92, y: 79}
        };
        return scales[piece] || {size: 82, y: 76};
      }
      function renderBoard() {
        var state = latestState || {};
        var sensors = state.sensors || {};
        var orientation = state.boardOrientation === "black" ? squares.slice().reverse() : squares;
        var html = '<div class="board">';
        for (var i = 0; i < orientation.length; i++) {
          var square = orientation[i];
          var row = Math.floor(i / 8);
          var col = i % 8;
          var file = square.charCodeAt(0) - 97;
          var rank = Number(square.charAt(1));
          html += '<div class="sq ' + ((file + rank) % 2 ? "light" : "dark") + '">' + (sensors[square] ? '<div class="piece"></div>' : '') + squareCoordinateLabels(square, row, col) + '</div>';
        }
        return html + '</div>';
      }
      function gameBoardOrientation(game) {
        if (game && game.playerColor === "black") return "black";
        if (game && game.playerColor === "white") return "white";
        return latestState && latestState.boardOrientation === "black" ? "black" : "white";
      }
      function renderDebugRows(game, sync) {
        var debug = game.debug || {};
        var leds = latestState && latestState.leds ? latestState.leds : {};
        return '<div>Debug: <code>' + escapeHtml(debug.playerColorReason || "no color reason") + '</code></div>' +
          '<div>FEN: <code>' + escapeHtml(debug.fen || game.fen || "none") + '</code></div>' +
          '<div>LED mode: <code>' + escapeHtml(leds.mode || "none") + '</code></div>' +
          '<div>Baseline pieces: <code>' + escapeHtml(debug.lastOccupancyCount === undefined ? "none" : debug.lastOccupancyCount) + '</code></div>' +
          '<div>Sync matches: <code>' + escapeHtml(sync && sync.matches ? "yes" : "no") + '</code></div>';
      }
      function renderPositionBoard(pieces, playerColor, orientationColor) {
        var state = latestState || {};
        var orientation = orientationColor === "black" ? squares.slice().reverse() : squares;
        var targets = {};
        var leds = state.leds || {};
        if (leds.mode === "legal-targets") {
          var highlighted = leds.highlightedSquares || [];
          for (var t = 0; t < highlighted.length; t++) targets[highlighted[t]] = true;
        } else if (leds.mode === "move") {
          var moveSquares = leds.highlightedSquares || [];
          for (var m = 0; m < moveSquares.length; m++) targets[moveSquares[m]] = true;
        }
        var html = '<div class="board">';
        pieces = pieces || {};
        playerColor = playerColor || "white";
        for (var i = 0; i < orientation.length; i++) {
          var square = orientation[i];
          var row = Math.floor(i / 8);
          var col = i % 8;
          var file = square.charCodeAt(0) - 97;
          var rank = Number(square.charAt(1));
          html += '<div class="sq ' + ((file + rank) % 2 ? "light" : "dark") + (targets[square] ? " target" : "") + '">' + (pieces[square] ? pieceSvg(pieces[square], playerColor) : '') + squareCoordinateLabels(square, row, col) + '</div>';
        }
        return html + '</div>';
      }
      function renderGame() {
        var game = latestState && latestState.game ? latestState.game : {clock: {whiteMs: null, blackMs: null}};
        var clock = game.clock || {whiteMs: null, blackMs: null};
        var sync = latestState && latestState.sync ? latestState.sync : {matches: false, missing: [], extra: []};
        var actions = [["Submit Move", "board"], ["Offer/Accept Draw", "draw"], ["Decline Draw", "no"], [kioskState.confirmResign ? "Confirm Resign" : "Resign", "resign"], ["Refresh Lichess", "sync"], ["Back", "menu"]];
        var actionHtml = '<section class="list compact">';
        for (var i = 0; i < actions.length; i++) actionHtml += '<div class="item' + selectedClass(i) + '"><span>' + actions[i][0] + '</span><small>' + actions[i][1] + '</small></div>';
        actionHtml += '</section>';
        setHeader("Current Game", game.drawOffer ? "Draw Offered" : (sync.matches ? "Synced" : "Fix Board"));
        appEl.innerHTML = '<div class="split">' + renderPositionBoard(game.pieces || {}, game.playerColor || "white", gameBoardOrientation(game)) + '<div class="meta"><div>' + escapeHtml(gameHelpText(sync)) + '</div><div>You are: <code>' + escapeHtml(game.playerColor || "unknown") + '</code></div><div>Board view: <code>' + escapeHtml(gameBoardOrientation(game)) + '</code></div><div>White: <code>' + formatClock(clock.whiteMs) + '</code> Black: <code>' + formatClock(clock.blackMs) + '</code></div><div>Game: <code>' + escapeHtml(game.id || "none") + '</code></div><div>Status: <code>' + escapeHtml(game.status || "idle") + '</code></div><div>Turn: <code>' + escapeHtml(game.turn || "white") + '</code></div><div>Last move: <code>' + escapeHtml(game.lastMove || "none") + '</code></div><div>Draw offer: <code>' + escapeHtml(game.drawOffer || "none") + '</code></div><div>Missing: <code>' + escapeHtml((sync.missing || []).join(", ") || "none") + '</code></div><div>Extra: <code>' + escapeHtml((sync.extra || []).join(", ") || "none") + '</code></div>' + renderDebugRows(game, sync) + actionHtml + '</div></div>';
      }
      function renderSettings() {
        var state = latestState || {};
        renderMenu("Settings", [["Lights On", "enable"], ["Lights Off", "disable"], ["Brightness Up", "up"], ["Brightness Down", "down"], ["Brightness " + Math.round((state.ledBrightness || 0.1) * 100) + "%", "level"], ["Orientation " + (state.boardOrientation || "white"), "orientation"], ["Test Mode " + (state.testMode ? "On" : "Off"), "test"], ["Reconnect Wi-Fi", "wifi"], ["Disconnect Lichess", "logout"], ["Back", "back"]], "Board");
      }
      function renderPuzzle() {
        var game = latestState && latestState.game ? latestState.game : {};
        var puzzle = game.puzzle || {};
        var sync = latestState && latestState.sync ? latestState.sync : {matches: false, missing: [], extra: []};
        var actions = [["Start Puzzle", "ready"], ["Submit Puzzle Move", "move"], ["Next Puzzle", "new"], ["Refresh Puzzle", "sync"], ["Back", "menu"]];
        var actionHtml = '<section class="list compact">';
        for (var i = 0; i < actions.length; i++) actionHtml += '<div class="item' + selectedClass(i) + '"><span>' + actions[i][0] + '</span><small>' + actions[i][1] + '</small></div>';
        actionHtml += '</section>';
        setHeader("Puzzle", puzzle.status === "complete" ? "Solved" : (sync.matches ? "Ready" : "Set Pieces"));
        appEl.innerHTML = '<div class="split">' + renderPositionBoard(game.pieces || {}, game.playerColor || "white", gameBoardOrientation(game)) + '<div class="meta"><div>' + escapeHtml(puzzleHelpText(sync, puzzle)) + '</div><div>You are: <code>' + escapeHtml(game.playerColor || "unknown") + '</code></div><div>Board view: <code>' + escapeHtml(gameBoardOrientation(game)) + '</code></div><div>Puzzle: <code>' + escapeHtml(puzzle.id || "none") + '</code></div><div>Rating: <code>' + escapeHtml(puzzle.rating || "--") + '</code></div><div>Status: <code>' + escapeHtml(puzzle.status || game.status || "setup") + '</code></div><div>Turn: <code>' + escapeHtml(game.turn || "white") + '</code></div><div>Move: <code>' + escapeHtml((puzzle.solutionIndex || 0) + "/" + (puzzle.solutionLength || 0)) + '</code></div><div>Themes: <code>' + escapeHtml((puzzle.themes || []).join(", ") || "none") + '</code></div><div>Missing: <code>' + escapeHtml((sync.missing || []).join(", ") || "none") + '</code></div><div>Extra: <code>' + escapeHtml((sync.extra || []).join(", ") || "none") + '</code></div>' + renderDebugRows(game, sync) + actionHtml + '</div></div>';
      }
      function gameHelpText(sync) {
        if (!latestState || !latestState.game || !latestState.game.id) return "Set the physical board first.";
        if (sync && !sync.matches) return "Fix the lit squares before submitting a move.";
        return "Lift one piece, place it on the lit destination, then submit.";
      }
      function puzzleHelpText(sync, puzzle) {
        if (puzzle && puzzle.status === "complete") return "Puzzle solved.";
        if (sync && !sync.matches) return "Set up every lit square before starting.";
        return "Play the lit move, then submit it.";
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
        renderMenu("LED Test", [["All Lights", "all"], ["Border Chase", "border"], ["Square Test", "square"], ["Lights Off", "off"], ["Brightness Up", "up"], ["Brightness Down", "down"], ["Back", "back"]], kioskState.ledTest);
      }
      function renderScreen() {
        if (kioskState.screen === "boot") { setHeader("Chess Board", "Starting"); appEl.innerHTML = '<div class="status">Loading...</div>'; }
        else if (kioskState.screen === "wifiList") renderWifiList();
        else if (kioskState.screen === "wifiPassword") renderWifiPassword();
        else if (kioskState.screen === "wifiError") renderMenu("Wi-Fi Failed", [["Edit Password", "edit"], ["Choose Different Wi-Fi", "wifi"], ["Refresh Wi-Fi List", "scan"]], "Retry");
        else if (kioskState.screen === "lichessSetup") renderLichessSetup();
        else if (kioskState.screen === "mainMenu") renderMenu("Chess Board", mainMenu, latestState && latestState.lichess && latestState.lichess.username ? latestState.lichess.username : "Ready");
        else if (kioskState.screen === "playMenu") renderMenu("Play", playMenu, "Lichess");
        else if (kioskState.screen === "tactics") renderMenu("Tactics", [["New Puzzle", "new"], ["Daily Puzzle", "daily"], ["Back", "back"]], "Puzzle");
        else if (kioskState.screen === "game") { if (latestState && latestState.game && String(latestState.game.mode).indexOf("puzzle") === 0) renderPuzzle(); else renderGame(); }
        else if (kioskState.screen === "puzzle") renderPuzzle();
        else if (kioskState.screen === "settings") renderSettings();
        else if (kioskState.screen === "diagnostics") renderDiagnostics();
        else if (kioskState.screen === "boardTest") renderBoardTest();
        else if (kioskState.screen === "ledTest") renderLedTest();
      }
      function listLength() {
        if (kioskState.screen === "wifiList") return kioskState.networks.length + 1;
        if (kioskState.screen === "lichessSetup") return 0;
        if (kioskState.screen === "mainMenu") return mainMenu.length;
        if (kioskState.screen === "playMenu") return playMenu.length;
        if (kioskState.screen === "tactics") return 3;
        if (kioskState.screen === "game") return 6;
        if (kioskState.screen === "puzzle") return 4;
        if (kioskState.screen === "settings") return 10;
        if (kioskState.screen === "ledTest") return 7;
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
        else if (kioskState.screen === "playMenu" || kioskState.screen === "game" || kioskState.screen === "puzzle" || kioskState.screen === "tactics" || kioskState.screen === "settings" || kioskState.screen === "diagnostics" || kioskState.screen === "boardTest" || kioskState.screen === "ledTest") setScreen("mainMenu");
      }
      function activateSelected() {
        if (kioskState.screen === "wifiList") {
          if (kioskState.selected >= kioskState.networks.length) { scanWifi(); return; }
          var network = kioskState.networks[kioskState.selected];
          kioskState.selectedSsid = network.ssid;
          kioskState.selectedSecurity = network.security || "Open";
          kioskState.password = "";
          if (isOpenNetwork(network)) { kioskState.message = "No password needed"; connectWifi(); return; }
          setScreen("wifiPassword");
        } else if (kioskState.screen === "wifiPassword") pressPasswordKey(PASSWORD_ROWS[kioskState.gridRow][kioskState.gridCol]);
        else if (kioskState.screen === "wifiError") { if (kioskState.selected === 0) setScreen("wifiPassword"); else if (kioskState.selected === 1) setScreen("wifiList"); else scanWifi(); }
        else if (kioskState.screen === "lichessSetup") refresh();
        else if (kioskState.screen === "mainMenu") setScreen(mainMenu[kioskState.selected][1]);
        else if (kioskState.screen === "playMenu") playMenu[kioskState.selected][1]();
        else if (kioskState.screen === "game") gameAction(kioskState.selected);
        else if (kioskState.screen === "puzzle") puzzleAction(kioskState.selected);
        else if (kioskState.screen === "tactics") { if (kioskState.selected === 0) fetchPuzzle("/api/puzzles/next"); else if (kioskState.selected === 1) fetchPuzzle("/api/puzzles/daily"); else goBack(); }
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
        if (index === 0) saveSettings({ledsEnabled: true});
        else if (index === 1) saveSettings({ledsEnabled: false});
        else if (index === 2) saveSettings({ledsEnabled: true, ledBrightness: Math.min(1, ((state.ledBrightness || 0.1) + 0.05))});
        else if (index === 3) saveSettings({ledBrightness: Math.max(0.01, ((state.ledBrightness || 0.1) - 0.05))});
        else if (index === 4) saveSettings({ledBrightness: state.ledBrightness || 0.1});
        else if (index === 5) saveSettings({boardOrientation: state.boardOrientation === "black" ? "white" : "black"});
        else if (index === 6) saveSettings({testMode: !state.testMode});
        else if (index === 7) { kioskState.setupOverride = true; kioskState.networks = []; setScreen("wifiList"); scanWifi(); }
        else if (index === 8) request("POST", "/api/lichess/logout", null, function () { refresh(); });
        else goBack();
      }
      function ledTestAction(index) {
        if (index === 0) runLedTest("all", "All Lights");
        else if (index === 1) runLedTest("border", "Border Chase");
        else if (index === 2) runLedTest("square", "Square Test");
        else if (index === 3) { kioskState.ledTest = "Off"; saveSettings({ledsEnabled: false}); }
        else if (index === 4) saveSettings({ledsEnabled: true, ledBrightness: Math.min(1, ((latestState && latestState.ledBrightness) || 0.1) + 0.05)});
        else if (index === 5) saveSettings({ledBrightness: Math.max(0.01, ((latestState && latestState.ledBrightness) || 0.1) - 0.05)});
        else goBack();
      }
      function runLedTest(pattern, label) { request("POST", "/api/led/test", {pattern: pattern}, function () { kioskState.ledTest = label; refresh(); }, function () { kioskState.ledTest = "LED test unavailable"; renderScreen(); }); }
      function saveSettings(body) { request("POST", "/api/settings", body, function () { refresh(); }); }
      function startComputerGame() {
        kioskState.pendingStart = null;
        kioskState.message = "Starting computer game...";
        renderScreen();
        request("POST", "/api/play/ai", {level: 3, clockLimit: 180, increment: 2}, function () {
          kioskState.message = "Computer game started";
          kioskState.pendingStart = null;
          kioskState.screen = "game";
          kioskState.selected = 0;
          refresh();
        }, function (xhr) {
          if (xhr.status === 409) {
            kioskState.pendingStart = "computer";
            kioskState.screen = "game";
            kioskState.selected = 0;
            kioskState.message = errorMessage(xhr, "Set the physical board first. The game will start when ready.");
            refresh();
            return;
          }
          kioskState.message = "Error: " + errorMessage(xhr);
          renderScreen();
        });
      }
      function gameAction(index) {
        if (index === 0) submitPhysicalMove();
        else if (index === 1) drawGame("yes");
        else if (index === 2) drawGame("no");
        else if (index === 3) resignGame();
        else if (index === 4) refreshLichessGame();
        else goBack();
      }
      function submitPhysicalMove() {
        kioskState.message = "Submitting move...";
        renderScreen();
        request("POST", "/api/game/submit-physical", {}, function (result) {
          kioskState.message = result && result.submitted ? "Move sent: " + result.move : (result && result.message ? result.message : "That button asked the board to check the physical move. Lift one piece, move it, then press Submit Move.");
          refresh();
        }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function refreshLichessGame() {
        kioskState.message = "Refreshing Lichess...";
        renderScreen();
        request("POST", "/api/game/refresh", {}, function () { kioskState.message = "Game refreshed"; refresh(); }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function drawGame(answer) {
        var path = answer === "yes" ? "/api/game/draw/yes" : "/api/game/draw/no";
        kioskState.confirmResign = false;
        kioskState.message = answer === "yes" ? "Sending draw response..." : "Declining draw...";
        renderScreen();
        request("POST", path, {}, function () { kioskState.message = answer === "yes" ? "Draw sent" : "Draw declined"; refreshLichessGame(); }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function resignGame() {
        if (!kioskState.confirmResign) {
          kioskState.confirmResign = true;
          kioskState.message = "Select Confirm Resign";
          renderScreen();
          return;
        }
        kioskState.confirmResign = false;
        kioskState.message = "Resigning...";
        renderScreen();
        request("POST", "/api/game/resign", {}, function () { kioskState.message = "Game resigned"; refreshLichessGame(); }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function fetchPuzzle(path) {
        kioskState.message = "Loading puzzle...";
        renderScreen();
        request("POST", path, {}, function () {
          kioskState.message = "Place pieces, then start";
          kioskState.screen = "puzzle";
          kioskState.selected = 0;
          refresh();
        }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function puzzleAction(index) {
        if (index === 0) startPuzzle();
        else if (index === 1) submitPuzzleMove();
        else if (index === 2) fetchPuzzle("/api/puzzles/next");
        else if (index === 3) refreshPuzzle();
        else goBack();
      }
      function startPuzzle() {
        kioskState.pendingStart = null;
        kioskState.message = "Starting puzzle...";
        renderScreen();
        request("POST", "/api/puzzle/start", {}, function () {
          kioskState.pendingStart = null;
          kioskState.message = "Puzzle started";
          refresh();
        }, function (xhr) {
          if (xhr.status === 409) {
            kioskState.pendingStart = "puzzle";
            kioskState.screen = "puzzle";
            kioskState.selected = 0;
            kioskState.message = errorMessage(xhr, "Set up every lit square. The puzzle will start when ready.");
            refresh();
            return;
          }
          kioskState.message = "Error: " + errorMessage(xhr);
          renderScreen();
        });
      }
      function submitPuzzleMove() {
        kioskState.message = "Checking puzzle move...";
        renderScreen();
        request("POST", "/api/puzzle/submit-physical", {}, function (result) {
          kioskState.message = result && result.accepted ? (result.complete ? "Puzzle solved" : "Correct: " + result.move) : (result && result.message ? result.message : "Move not accepted");
          refresh();
        }, function (xhr) { kioskState.message = "Error: " + (xhr.responseText || xhr.status); renderScreen(); });
      }
      function refreshPuzzle() { kioskState.message = "Puzzle refreshed"; refresh(); }
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
      var liveRefreshInFlight = false;
      var lichessGameRefreshInFlight = false;
      function isLiveScreen() {
        return kioskState.screen === "game" || kioskState.screen === "puzzle" || kioskState.screen === "diagnostics" || kioskState.screen === "boardTest";
      }
      function mergeLiveState(state) {
        if (!latestState) latestState = {};
        latestState.hardware = state.hardware;
        latestState.sensors = state.sensors;
        latestState.sensorDetails = state.sensorDetails;
        latestState.leds = state.leds;
        latestState.game = state.game;
        latestState.sync = state.sync;
      }
      function refreshLive() {
        if (liveRefreshInFlight || !isLiveScreen()) return;
        liveRefreshInFlight = true;
        request("GET", "/api/live-state", null, function (state) {
          mergeLiveState(state);
          maybeRunPendingStart();
          liveRefreshInFlight = false;
          renderScreen();
        }, function () {
          liveRefreshInFlight = false;
        });
      }
      function maybeRunPendingStart() {
        if (!kioskState.pendingStart || kioskState.pendingStartInFlight) return;
        if (!latestState || !latestState.sync || !latestState.sync.matches) return;
        kioskState.pendingStartInFlight = true;
        if (kioskState.pendingStart === "puzzle") {
          request("POST", "/api/puzzle/start", {}, function () {
            kioskState.pendingStart = null;
            kioskState.pendingStartInFlight = false;
            kioskState.message = "Puzzle started";
            refresh();
          }, function (xhr) {
            kioskState.pendingStartInFlight = false;
            kioskState.message = errorMessage(xhr, "Still waiting for the board to match.");
          });
        } else if (kioskState.pendingStart === "computer") {
          request("POST", "/api/play/ai", {level: 3, clockLimit: 180, increment: 2}, function () {
            kioskState.pendingStart = null;
            kioskState.pendingStartInFlight = false;
            kioskState.message = "Computer game started";
            kioskState.screen = "game";
            refresh();
          }, function (xhr) {
            kioskState.pendingStartInFlight = false;
            kioskState.message = errorMessage(xhr, "Still waiting for the board to match.");
          });
        }
      }
      function pollLichessGame() {
        if (lichessGameRefreshInFlight || !latestState || !latestState.game || !latestState.game.id || latestState.game.mode !== "game") return;
        lichessGameRefreshInFlight = true;
        request("POST", "/api/game/refresh", {}, function (state) {
          if (!latestState) latestState = {};
          latestState.game = state.game;
          latestState.sync = state.sync;
          lichessGameRefreshInFlight = false;
          renderScreen();
        }, function () {
          lichessGameRefreshInFlight = false;
        });
      }
      function renderBootError(error) { setHeader("Chess Board", "Backend Error"); appEl.innerHTML = '<section class="list"><div class="item selected"><span>Waiting for backend</span><small>retrying</small></div></section><div class="status">Could not load /api/state</div>'; }
      document.addEventListener("keydown", function (event) {
        var keys = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "select"};
        if (keys[event.key]) { event.preventDefault(); handleCommand(keys[event.key]); }
      });
      renderScreen();
      refresh();
      setInterval(refresh, 2000);
      setInterval(refreshLive, 60);
      setInterval(pollLichessGame, 2000);
      setInterval(pollInput, 80);
    </script>
  </body>
</html>
"""

    @app.get("/api/state")
    def api_state():
        return build_state(config_store, sensor_reader, game_session, wifi_manager, led_controller)

    @app.get("/api/live-state")
    def api_live_state():
        config = config_store.load()
        return build_live_state(
            sensor_reader,
            game_session,
            led_controller,
            test_mode=config.test_mode,
            board_orientation=config.board_orientation,
        )

    @app.get("/api/sensors")
    def api_sensors():
        config = config_store.load()
        return _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)

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
    <p><a style="color:#f4d35e" href="/phone-setup">Open setup page</a></p>
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
        redirect_uri = f"{_phone_base_url()}/auth/lichess/callback"
        session, url = LichessOAuth().start(redirect_uri)
        oauth_sessions[session.state] = session
        return Response(
            content=setup_url_qr_svg(url),
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
    <title>Light Mate Setup</title>
    <style>
      :root {
        --porcelain: #faf8f4;
        --paper: #fffefd;
        --charcoal: #2c2b2f;
        --graphite: #5b5a5c;
        --line: #e1d6bf;
        --gold: #d7b973;
        --gold-deep: #9a7834;
        --danger: #b4554e;
      }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: system-ui, sans-serif; background: radial-gradient(circle at top left, #ffffff 0, var(--porcelain) 44%, #f0e9dd 100%); color: var(--charcoal); padding: 18px; }
      main { max-width: 520px; margin: 0 auto; display: grid; gap: 14px; background: rgba(255, 254, 253, .88); border: 1px solid var(--line); padding: 18px; box-shadow: 0 16px 44px rgba(44, 43, 47, .1); }
      .brandName { font-size: 15px; font-weight: 760; letter-spacing: .28em; text-transform: uppercase; color: var(--charcoal); }
      .brandName .mate { color: var(--gold-deep); }
      h1 { margin: 0; font-size: 28px; }
      p { color: var(--graphite); line-height: 1.45; }
      input, button { width: 100%; min-height: 48px; font-size: 17px; padding: 10px; box-sizing: border-box; }
      input { background: var(--paper); border: 2px solid var(--line); color: var(--charcoal); }
      button { background: var(--charcoal); color: var(--gold); border: 2px solid var(--gold); font-weight: 850; }
      button.danger { background: var(--danger); color: #fff; border-color: var(--danger); }
      .status { color: var(--gold-deep); font-weight: 850; min-height: 24px; }
      a { color: var(--gold-deep); font-weight: 800; }
    </style>
  </head>
  <body>
    <main>
      <div class="brandName"><span>LIGHT</span> <span class="mate">MATE</span></div>
      <h1>Chess Board Setup</h1>
      <p>Paste a Lichess API token with board play access. The board will save it automatically.</p>
      <input id="token" type="password" autocomplete="off" placeholder="Lichess API token">
      <button id="save">Send Token To Board</button>
      <button id="remove" class="danger">Remove Saved Token</button>
      <div id="status" class="status"></div>
      <p><a href="/auth/lichess/start">Connect with Lichess OAuth instead</a></p>
      <p><a href="/">Open board screen</a></p>
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
      document.getElementById("remove").addEventListener("click", function () {
        var status = document.getElementById("status");
        var xhr = new XMLHttpRequest();
        status.textContent = "Removing...";
        xhr.open("POST", "/api/lichess/logout", true);
        xhr.onreadystatechange = function () {
          if (xhr.readyState !== 4) return;
          if (xhr.status >= 200 && xhr.status < 300) {
            status.textContent = "Token removed. You can connect a different account.";
          } else {
            status.textContent = "Could not remove token: " + (xhr.responseText || xhr.status);
          }
        };
        xhr.send();
      });
    </script>
  </body>
</html>
""")

    @app.post("/api/settings")
    def update_settings(payload: SettingsRequest):
        try:
            config = config_store.update_settings(
                leds_enabled=payload.ledsEnabled,
                led_brightness=payload.ledBrightness,
                board_orientation=payload.boardOrientation,
                device_name=payload.deviceName,
                test_mode=payload.testMode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        led_controller.apply_settings(LedSettings(
            enabled=config.leds_enabled,
            brightness=config.led_brightness,
            orientation=_active_orientation(config.board_orientation, game_session),
        ))
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
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        setup_sync = GameSession().sync_status(snapshot)
        test_mode = config.test_mode
        if not setup_sync["matches"] and not test_mode:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Set the physical board first.",
                    "missing": setup_sync["missing"],
                    "extra": setup_sync["extra"],
                },
            )
        client = _lichess_client()
        created = client.challenge_ai(
            level=payload.level,
            clock_limit=payload.clockLimit,
            increment=payload.increment,
            color=payload.color,
            variant=payload.variant,
        )
        game_id = created.get("id")
        if not game_id:
            raise HTTPException(status_code=502, detail="Lichess AI response did not include game id")
        event = client.stream_game_state(game_id)
        game_session.update_from_lichess_state(event)
        username_color = _player_color_from_username(config.lichess_username, game_session)
        if username_color:
            game_session.set_player_color(username_color, f"lichess username matched {username_color}")
        elif created.get("player"):
            game_session.set_player_color(created.get("player"), "lichess challenge response")
        else:
            game_session.set_player_color(None, "unknown")
        game_session.mark_synced(snapshot)
        return {
            "created": created,
            "game": game_session.public_state(),
            "sync": game_session.sync_status(snapshot),
        }

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
        return _load_puzzle(_lichess_client().daily_puzzle())

    @app.post("/api/puzzles/next")
    def next_puzzle():
        return _load_puzzle(_next_batch_puzzle(_lichess_client()))

    def _load_puzzle(payload: dict[str, Any]):
        try:
            game_session.load_puzzle(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        return {
            "puzzle": payload.get("puzzle", {}),
            "game": game_session.public_state(),
            "sync": game_session.sync_status(snapshot),
        }

    def _next_batch_puzzle(client: Any) -> dict[str, Any]:
        current_id = (game_session.puzzle or {}).get("id")
        payload = client.puzzle_batch(angle="mix", nb=1)
        puzzles = payload.get("puzzles") or []
        if not puzzles:
            raise HTTPException(status_code=502, detail="Lichess did not return a next puzzle")
        if current_id and (puzzles[0].get("puzzle") or {}).get("id") == current_id:
            anonymous_client = LichessClient("", base_url=getattr(client, "base_url", "https://lichess.org"))
            payload = anonymous_client.puzzle_batch(angle="mix", nb=1)
            puzzles = payload.get("puzzles") or []
            if not puzzles:
                raise HTTPException(status_code=502, detail="Lichess did not return a next puzzle")
        return puzzles[0]

    @app.post("/api/puzzle/start")
    def start_puzzle():
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        setup_sync = game_session.sync_status(snapshot)
        test_mode = config.test_mode
        if not setup_sync["matches"] and not test_mode:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Set up every lit square before starting.",
                    "missing": setup_sync["missing"],
                    "extra": setup_sync["extra"],
                },
            )
        try:
            game_session.start_puzzle(snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "game": game_session.public_state(),
            "sync": game_session.sync_status(snapshot),
        }

    @app.post("/api/puzzle/submit-physical")
    def submit_puzzle_physical_move():
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        result = game_session.submit_puzzle_move(snapshot, allow_unsynced=config.test_mode)
        result["sync"] = game_session.sync_status(snapshot)
        return result

    @app.post("/api/game/mock-state")
    def update_mock_game(payload: GameStateRequest):
        game_session.update_from_lichess_state(payload.model_dump(exclude_none=True))
        return game_session.public_state()

    @app.post("/api/game/refresh")
    def refresh_game():
        client, game_id = _lichess_for_current_game()
        event = client.stream_game_state(game_id)
        game_session.update_from_lichess_state(event)
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        if game_session.sync_status(snapshot)["matches"]:
            game_session.mark_synced(snapshot)
        return {
            "game": game_session.public_state(),
            "sync": game_session.sync_status(snapshot),
        }

    @app.post("/api/game/submit-physical")
    def submit_physical_move():
        client, game_id = _lichess_for_current_game()
        config = config_store.load()
        snapshot = _read_oriented_snapshot(sensor_reader, config.board_orientation, game_session)
        result = game_session.detect_move_from_last_snapshot(snapshot, allow_unsynced=config.test_mode)
        if result.kind == "none":
            return {"submitted": False, "kind": result.kind, "message": "No physical move detected"}
        if result.kind != "move" or not result.uci:
            return {"submitted": False, "kind": result.kind, "message": result.reason or "Move is not ready"}
        try:
            client.make_move(game_id, result.uci)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        game_session.apply_submitted_move(result.uci, snapshot)
        try:
            game_session.update_from_lichess_state(client.stream_game_state(game_id))
        except Exception:
            pass
        return {
            "submitted": True,
            "move": result.uci,
            "game": game_session.public_state(),
            "sync": game_session.sync_status(snapshot),
        }

    def _lichess_for_current_game():
        config = config_store.load()
        if not config.lichess_token:
            raise HTTPException(status_code=401, detail="Lichess is not connected")
        if not game_session.game_id:
            raise HTTPException(status_code=400, detail="No active game selected")
        return LichessClient(config.lichess_token), game_session.game_id

    def _player_color_from_username(username: str | None, session: GameSession) -> str | None:
        if not username:
            return None
        normalized = username.lower()
        for color in ("white", "black"):
            player = session.players.get(color, {})
            if str(player.get("name") or "").lower() == normalized:
                return color
        return None

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
