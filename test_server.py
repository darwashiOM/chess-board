import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chess

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.leds import MemoryLedController
from chessboard_app.sensors import StaticSensorReader, UnavailableSensorReader
from chessboard_app.sensors import expected_occupancy_from_board
from chessboard_app.server import build_live_state, build_state, create_app
from chessboard_app.wifi import WifiManager


class ServerStateTest(unittest.TestCase):
    def enabled_led_store(self, tmp):
        store = AppConfigStore(os.path.join(tmp, "config.json"))
        store.update_settings(leds_enabled=True)
        return store

    def puzzle_payload(self):
        return {
            "game": {"id": "setupGame", "pgn": "e4 e5", "players": []},
            "puzzle": {
                "id": "puzzle1",
                "rating": 1200,
                "themes": ["opening"],
                "initialPly": 2,
                "solution": ["g1f3", "b8c6"],
            },
        }

    def test_build_state_includes_public_config_and_sensors(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            state = build_state(store, StaticSensorReader(), GameSession(), WifiManager(runner=lambda args: ""))

            self.assertEqual(state["lichess"]["username"], "player1")
            self.assertEqual(state["hardware"]["sensors"], "ok")
            self.assertEqual(len(state["sensors"]), 64)
            self.assertIn("game", state)
            self.assertIn("wifi", state)
            self.assertIn("leds", state)
            self.assertNotIn("secret", repr(state))

    def test_build_state_reads_sensors_once(self):
        class CountingSensorReader(StaticSensorReader):
            def __init__(self):
                super().__init__()
                self.read_count = 0
                self.details_count = 0

            def read(self):
                self.read_count += 1
                return super().read()

            def details(self):
                self.details_count += 1
                return super().details()

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            reader = CountingSensorReader()

            state = build_state(store, reader, GameSession(), WifiManager(runner=lambda args: ""))

            self.assertEqual(reader.read_count, 1)
            self.assertEqual(reader.details_count, 0)
            self.assertEqual(len(state["sensorDetails"]), 64)

    def test_live_state_skips_wifi_and_returns_fresh_sensors(self):
        class FailingWifi(WifiManager):
            def status(self):
                raise AssertionError("live state should not call Wi-Fi status")

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader({"e4": True, **{
                    square: False
                    for square in expected_occupancy_from_board(chess.Board()).keys()
                    if square != "e4"
                }}),
                game_session=GameSession(),
                wifi_manager=FailingWifi(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/live-state")

            state = route.endpoint()

        self.assertEqual(state["sensors"]["e4"], True)
        self.assertIn("sync", state)
        self.assertIn("sensorDetails", state)
        self.assertNotIn("wifi", state)

    def test_black_player_color_rotates_physical_sensor_snapshot(self):
        raw = {square: False for square in chess.SQUARE_NAMES}
        raw["h1"] = True
        session = GameSession()
        session.board = chess.Board("r7/8/8/8/8/8/8/8 b - - 0 1")
        session.set_player_color("black", "test black orientation")

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            state = build_state(
                store,
                StaticSensorReader(raw),
                session,
                WifiManager(runner=lambda args: ""),
                MemoryLedController(),
            )

        self.assertTrue(state["sensors"]["a8"])
        self.assertFalse(state["sensors"]["h1"])
        self.assertEqual(state["sync"]["missing"], [])
        self.assertEqual(state["sync"]["extra"], [])

    def test_index_serves_valid_escape_html_quote_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/")
            html = route.endpoint()

        self.assertIn('return "&quot;"', html)
        self.assertNotIn('return {"&":', html)
        self.assertNotIn('""": "&quot;"', html)

    def test_index_lithess_setup_shows_network_status_without_local_oauth_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/")
            html = route.endpoint()

        self.assertIn("renderWifiStatus", html)
        self.assertIn("wifiSignalBars", html)
        self.assertIn("Wi-Fi:", html)
        self.assertIn("Lichess:", html)
        self.assertNotIn("Open OAuth Here", html)
        rendered_status = html.split("function renderWifiStatus()", 1)[1].split("function renderWifiPassword()", 1)[0]
        self.assertNotIn("IP:", rendered_status)
        lichess_screen = html.split("function renderLichessSetup()", 1)[1].split("function renderBoard()", 1)[0]
        self.assertIn("/api/lichess-token-qr.svg", lichess_screen)
        self.assertNotIn("Check Connection", lichess_screen)
        self.assertNotIn("Get API Key", lichess_screen)
        self.assertNotIn("Enter API Key", lichess_screen)

    def test_lichess_qr_encodes_direct_lichess_oauth_url(self):
        server_source = Path("chessboard_app/server.py").read_text(encoding="utf-8")
        qr_route = server_source.split('def lichess_token_qr():', 1)[1].split('@app.get("/api/lichess-manual-token-qr.svg")', 1)[0]

        self.assertIn("LichessOAuth().start", qr_route)
        self.assertIn("/auth/lichess/callback", qr_route)
        self.assertIn("oauth_sessions[session.state]", qr_route)
        self.assertIn("setup_url_qr_svg(url)", qr_route)
        self.assertNotIn('"/auth/lichess/start"', qr_route)

    def test_index_uses_light_mate_gallery_theme(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/")
            html = route.endpoint()

        self.assertIn("Light Mate", html)
        self.assertIn("--porcelain: #faf8f4", html)
        self.assertIn("--charcoal: #2c2b2f", html)
        self.assertIn("--gold: #d7b973", html)
        self.assertIn("brandName", html)
        self.assertIn("LIGHT", html)
        self.assertIn("MATE", html)
        self.assertNotIn("background: #769656", html)
        self.assertNotIn("background: #161512", html)

    def test_phone_setup_can_return_after_oauth_and_remove_saved_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            phone_route = next(route for route in app.routes if getattr(route, "path", None) == "/phone-setup")
            phone_html = phone_route.endpoint().body.decode("utf-8")
            server_source = Path("chessboard_app/server.py").read_text(encoding="utf-8")

        self.assertIn("Remove Saved Token", phone_html)
        self.assertIn("/api/lichess/logout", phone_html)
        self.assertIn("Connect with Lichess OAuth", phone_html)
        self.assertIn("Light Mate", phone_html)
        self.assertIn("--porcelain: #faf8f4", phone_html)
        self.assertIn("--gold: #d7b973", phone_html)
        self.assertIn("/phone-setup", server_source)

    def test_build_state_reports_unavailable_sensor_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            state = build_state(
                store,
                UnavailableSensorReader("No I2C device at address: 0x20"),
                GameSession(),
                WifiManager(runner=lambda args: ""),
            )

            self.assertEqual(state["hardware"]["sensors"], "unavailable")
            self.assertIn("0x20", state["hardware"]["sensorError"])
            self.assertEqual(len(state["sensors"]), 64)

    def test_update_settings_changes_public_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            config = store.update_settings(leds_enabled=True, board_orientation="black")

            self.assertEqual(config.leds_enabled, True)
            self.assertEqual(config.board_orientation, "black")
            state = build_state(store, StaticSensorReader(), GameSession(), WifiManager(runner=lambda args: ""))
            self.assertEqual(state["ledsEnabled"], True)
            self.assertEqual(state["boardOrientation"], "black")

    def test_settings_endpoint_applies_led_changes_immediately(self):
        class RecordingLedController(MemoryLedController):
            def __init__(self):
                super().__init__()
                self.applied = []

            def apply_settings(self, settings):
                super().apply_settings(settings)
                self.applied.append(settings)

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.update_settings(leds_enabled=True, led_brightness=0.2)
            leds = RecordingLedController()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=leds,
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/settings")

            route.endpoint(type("Payload", (), {
                "ledsEnabled": False,
                "ledBrightness": 0.05,
                "boardOrientation": None,
                "deviceName": None,
                "testMode": None,
            })())

        self.assertEqual(leds.applied[-1].enabled, False)
        self.assertEqual(leds.applied[-1].brightness, 0.05)

    def test_settings_endpoint_updates_test_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/settings")

            state = route.endpoint(type("Payload", (), {
                "ledsEnabled": None,
                "ledBrightness": None,
                "boardOrientation": None,
                "deviceName": None,
                "testMode": True,
            })())

        self.assertEqual(state["testMode"], True)

    def test_state_highlights_legal_targets_when_one_piece_is_lifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
            session.status = "started"
            occupancy = expected_occupancy_from_board(session.board)
            occupancy["e2"] = False
            leds = MemoryLedController()

            state = build_state(
                store,
                StaticSensorReader(occupancy),
                session,
                WifiManager(runner=lambda args: ""),
                leds,
            )

        self.assertEqual(state["leds"]["mode"], "legal-targets")
        self.assertEqual(state["leds"]["highlightedSquares"], ["e3", "e4"])

    def test_puzzle_setup_uses_led_setup_guidance_for_missing_and_extra_squares(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            occupancy = expected_occupancy_from_board(session.board)
            occupancy["g1"] = False
            occupancy["d4"] = True
            leds = MemoryLedController()

            state = build_state(
                store,
                StaticSensorReader(occupancy),
                session,
                WifiManager(runner=lambda args: ""),
                leds,
            )

        self.assertEqual(state["game"]["mode"], "puzzle_setup")
        self.assertEqual(state["leds"]["mode"], "setup")
        self.assertIn("g1", state["leds"]["highlightedSquares"])
        self.assertIn("d4", state["leds"]["extraSquares"])

    def test_state_highlights_last_move_when_board_needs_opponent_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
            session.update_from_lichess_state({"state": {"moves": "e2e4 e7e5"}})
            physical_board = chess.Board()
            physical_board.push(chess.Move.from_uci("e2e4"))
            occupancy = expected_occupancy_from_board(physical_board)
            leds = MemoryLedController()

            state = build_state(
                store,
                StaticSensorReader(occupancy),
                session,
                WifiManager(runner=lambda args: ""),
                leds,
            )

        self.assertEqual(state["leds"]["mode"], "move")
        self.assertEqual(state["leds"]["highlightedSquares"], ["e7", "e5"])

    def test_play_ai_starts_lichess_game_and_marks_sensor_baseline(self):
        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def challenge_ai(self, **kwargs):
                return {"id": "game123", "player": "white"}

            def stream_game_state(self, game_id):
                return {
                    "id": game_id,
                    "white": {"name": "player1"},
                    "black": {"name": "Lichess AI", "rating": 1500},
                    "state": {"moves": "", "status": "started", "wtime": 180000, "btime": 180000},
                }

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(chess.Board())),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/play/ai")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint(type("Payload", (), {
                    "level": 3,
                    "clockLimit": 180,
                    "increment": 2,
                    "color": "random",
                    "variant": "standard",
                })())

        self.assertEqual(result["game"]["id"], "game123")
        self.assertEqual(result["game"]["playerColor"], "white")
        self.assertEqual(result["game"]["debug"]["playerColorReason"], "lichess username matched white")
        self.assertIsNotNone(session.last_occupancy)

    def test_play_ai_infers_player_color_from_lichess_username_when_response_omits_player(self):
        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def challenge_ai(self, **kwargs):
                return {"id": "game123"}

            def stream_game_state(self, game_id):
                return {
                    "id": game_id,
                    "white": {"name": "Lichess AI", "rating": 1500},
                    "black": {"name": "player1"},
                    "state": {"moves": "e2e4", "status": "started"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(chess.Board())),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/play/ai")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint(type("Payload", (), {
                    "level": 3,
                    "clockLimit": 180,
                    "increment": 2,
                    "color": "random",
                    "variant": "standard",
                })())

        self.assertEqual(result["game"]["playerColor"], "black")
        self.assertEqual(result["game"]["debug"]["playerColorReason"], "lichess username matched black")
        self.assertEqual(result["game"]["lastMove"], "e2e4")

    def test_play_ai_prefers_username_color_over_created_player_field(self):
        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def challenge_ai(self, **kwargs):
                return {"id": "game123", "player": "white"}

            def stream_game_state(self, game_id):
                return {
                    "id": game_id,
                    "white": {"name": "Lichess AI", "rating": 1500},
                    "black": {"name": "player1"},
                    "state": {"moves": "e2e4", "status": "started"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(chess.Board())),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/play/ai")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint(type("Payload", (), {
                    "level": 3,
                    "clockLimit": 180,
                    "increment": 2,
                    "color": "random",
                    "variant": "standard",
                })())

        self.assertEqual(result["game"]["playerColor"], "black")
        self.assertEqual(result["game"]["debug"]["playerColorReason"], "lichess username matched black")

    def test_play_ai_requires_starting_position_before_calling_lichess(self):
        class FakeLichessClient:
            called = False

            def __init__(self, token):
                self.token = token

            def challenge_ai(self, **kwargs):
                FakeLichessClient.called = True
                return {"id": "game123"}

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            occupancy = expected_occupancy_from_board(chess.Board())
            occupancy["e2"] = False
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(occupancy),
                game_session=GameSession(),
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/play/ai")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                with self.assertRaises(Exception) as raised:
                    route.endpoint(type("Payload", (), {
                        "level": 3,
                        "clockLimit": 180,
                        "increment": 2,
                        "color": "random",
                        "variant": "standard",
                    })())

        self.assertEqual(getattr(raised.exception, "status_code", None), 409)
        self.assertFalse(FakeLichessClient.called)

    def test_submit_physical_move_posts_to_lichess_and_updates_session(self):
        calls = []

        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def make_move(self, game_id, uci):
                calls.append((game_id, uci))

            def stream_game_state(self, game_id):
                return {
                    "id": game_id,
                    "white": {"name": "player1"},
                    "black": {"name": "Lichess AI"},
                    "state": {"moves": "e2e4", "status": "started"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession(game_id="game123")
            before = expected_occupancy_from_board(session.board)
            session.mark_synced(before)
            after_board = session.board.copy()
            after_board.push(chess.Move.from_uci("e2e4"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(after_board)),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/game/submit-physical")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint()

        self.assertEqual(result["submitted"], True)
        self.assertEqual(result["move"], "e2e4")
        self.assertEqual(calls, [("game123", "e2e4")])

    def test_next_puzzle_loads_puzzle_into_session(self):
        payload = self.puzzle_payload()

        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def puzzle_batch(self, angle="mix", nb=1):
                return {"puzzles": [payload]}

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzles/next")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint()

        self.assertEqual(result["game"]["mode"], "puzzle_setup")
        self.assertEqual(result["game"]["puzzle"]["id"], "puzzle1")
        self.assertEqual(result["game"]["pieces"]["e4"], "P")

    def test_next_puzzle_uses_batch_endpoint_for_fresh_puzzle(self):
        payload = self.puzzle_payload()

        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def puzzle_batch(self, angle="mix", nb=1):
                return {"puzzles": [payload]}

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzles/next")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint()

        self.assertEqual(result["game"]["puzzle"]["id"], "puzzle1")
        self.assertEqual(result["puzzle"]["id"], "puzzle1")

    def test_next_puzzle_falls_back_to_anonymous_batch_when_auth_repeats_current(self):
        current = self.puzzle_payload()
        current["puzzle"]["id"] = "current"
        fresh = self.puzzle_payload()
        fresh["puzzle"]["id"] = "fresh"
        created_tokens = []

        class FakeLichessClient:
            def __init__(self, token, **kwargs):
                self.token = token
                created_tokens.append(token)

            def puzzle_batch(self, angle="mix", nb=1):
                if self.token:
                    return {"puzzles": [current]}
                return {"puzzles": [fresh]}

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession()
            session.load_puzzle(current)
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzles/next")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint()

        self.assertEqual(result["game"]["puzzle"]["id"], "fresh")
        self.assertEqual(created_tokens, ["secret", ""])

    def test_start_and_submit_puzzle_physical_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            before = expected_occupancy_from_board(session.board)
            after_board = session.board.copy()
            after_board.push(chess.Move.from_uci("g1f3"))
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(before),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            start_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzle/start")
            result = start_route.endpoint()

            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(after_board)),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            submit_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzle/submit-physical")
            submit_result = submit_route.endpoint()

        self.assertEqual(result["game"]["mode"], "puzzle_play")
        self.assertEqual(submit_result["accepted"], True)
        self.assertEqual(submit_result["move"], "g1f3")
        self.assertEqual(submit_result["reply"], "b8c6")

    def test_live_state_auto_accepts_correct_puzzle_move_after_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            before = expected_occupancy_from_board(session.board)
            after_board = session.board.copy()
            after_board.push(chess.Move.from_uci("g1f3"))
            session.start_puzzle(before)
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(expected_occupancy_from_board(after_board)),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/live-state")

            state = route.endpoint()

        self.assertEqual(state["game"]["lastMove"], "b8c6")
        self.assertEqual(state["game"]["puzzle"]["solutionIndex"], 2)
        self.assertEqual(state["sync"]["missing"], ["c6"])
        self.assertEqual(state["sync"]["extra"], ["b8"])

    def test_live_state_marks_puzzle_synced_after_opponent_reply_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            before = expected_occupancy_from_board(session.board)
            user_board = session.board.copy()
            user_board.push(chess.Move.from_uci("g1f3"))
            user_after = expected_occupancy_from_board(user_board)
            reply_board = user_board.copy()
            reply_board.push(chess.Move.from_uci("b8c6"))
            reply_after = expected_occupancy_from_board(reply_board)
            session.start_puzzle(before)
            session.submit_puzzle_move(user_after)
            leds = MemoryLedController()
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(reply_after),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=leds,
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/live-state")

            state = route.endpoint()

        self.assertTrue(state["sync"]["matches"])
        self.assertEqual(state["leds"]["mode"], "idle")
        self.assertEqual(state["game"]["pieces"]["c6"], "n")
        self.assertNotIn("b8", state["game"]["pieces"])
        self.assertEqual(session.last_occupancy, reply_after)

    def test_start_puzzle_requires_physical_board_to_match_puzzle_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            occupancy = expected_occupancy_from_board(session.board)
            occupancy["g1"] = False
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(occupancy),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzle/start")

            with self.assertRaises(Exception) as raised:
                route.endpoint()

        self.assertEqual(getattr(raised.exception, "status_code", None), 409)
        self.assertEqual(session.status, "puzzle_setup")

    def test_test_mode_starts_puzzle_with_partial_board_and_accepts_delta_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.update_settings(test_mode=True)
            session = GameSession()
            session.load_puzzle(self.puzzle_payload())
            partial_before = {square: False for square in chess.SQUARE_NAMES}
            partial_before["g1"] = True
            partial_after = dict(partial_before)
            partial_after["g1"] = False
            partial_after["f3"] = True
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(partial_before),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            start_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzle/start")
            start_result = start_route.endpoint()

            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(partial_after),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            submit_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/puzzle/submit-physical")
            submit_result = submit_route.endpoint()

        self.assertEqual(start_result["game"]["mode"], "puzzle_play")
        self.assertEqual(submit_result["accepted"], True)
        self.assertEqual(submit_result["move"], "g1f3")

    def test_test_mode_lifted_partial_piece_shows_legal_targets_from_baseline(self):
        session = GameSession()
        session.load_puzzle(self.puzzle_payload())
        partial_before = {square: False for square in chess.SQUARE_NAMES}
        partial_before["g1"] = True
        partial_after = dict(partial_before)
        partial_after["g1"] = False
        session.start_puzzle(partial_before)
        leds = MemoryLedController()
        leds.apply_settings(type("Settings", (), {"enabled": True, "brightness": 0.1})())

        state = build_live_state(
            StaticSensorReader(partial_after),
            session,
            leds,
            test_mode=True,
        )

        self.assertEqual(state["leds"]["mode"], "legal-targets")
        self.assertEqual(set(state["leds"]["highlightedSquares"]), {"e2", "f3", "h3"})

    def test_live_state_applies_black_orientation_to_led_settings(self):
        session = GameSession()
        session.set_player_color("black", "test black orientation")
        leds = MemoryLedController()
        leds.apply_settings(type("Settings", (), {"enabled": True, "brightness": 0.1, "orientation": "white"})())

        build_live_state(
            StaticSensorReader(),
            session,
            leds,
            test_mode=True,
            board_orientation="white",
        )

        self.assertEqual(leds.settings.orientation, "black")

    def test_idle_state_shows_setup_guidance_until_starting_board_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            occupancy = expected_occupancy_from_board(chess.Board())
            occupancy["e2"] = False
            leds = MemoryLedController()

            state = build_state(
                store,
                StaticSensorReader(occupancy),
                GameSession(),
                WifiManager(runner=lambda args: ""),
                leds,
            )

        self.assertEqual(state["leds"]["mode"], "setup")
        self.assertIn("e2", state["leds"]["highlightedSquares"])

    def test_refresh_game_updates_position_clocks_and_draw_offer(self):
        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def stream_game_state(self, game_id):
                return {
                    "id": game_id,
                    "white": {"name": "player1"},
                    "black": {"name": "opponent"},
                    "state": {
                        "moves": "e2e4 e7e5",
                        "status": "started",
                        "wtime": 175000,
                        "btime": 174000,
                        "bdraw": True,
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession(game_id="game123")
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            route = next(route for route in app.routes if getattr(route, "path", None) == "/api/game/refresh")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                result = route.endpoint()

        self.assertEqual(result["game"]["lastMove"], "e7e5")
        self.assertEqual(result["game"]["clock"]["whiteMs"], 175000)
        self.assertEqual(result["game"]["drawOffer"], "black")
        self.assertEqual(result["game"]["pieces"]["e5"], "p")

    def test_draw_and_resign_routes_call_lichess_client(self):
        calls = []

        class FakeLichessClient:
            def __init__(self, token):
                self.token = token

            def handle_draw(self, game_id, accept):
                calls.append(("draw", game_id, accept))

            def resign(self, game_id):
                calls.append(("resign", game_id))

        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            store.save_lichess_token("secret", username="player1")
            session = GameSession(game_id="game123")
            app = create_app(
                config_store=store,
                sensor_reader=StaticSensorReader(),
                game_session=session,
                wifi_manager=WifiManager(runner=lambda args: ""),
                led_controller=MemoryLedController(),
            )
            draw_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/game/draw/{answer}")
            resign_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/game/resign")

            with patch("chessboard_app.server.LichessClient", FakeLichessClient):
                draw_route.endpoint("yes")
                draw_route.endpoint("no")
                resign_route.endpoint()

        self.assertEqual(calls, [
            ("draw", "game123", True),
            ("draw", "game123", False),
            ("resign", "game123"),
        ])


if __name__ == "__main__":
    unittest.main()
