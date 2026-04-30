import os
import tempfile
import unittest

import chess

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.leds import MemoryLedController
from chessboard_app.sensors import StaticSensorReader
from chessboard_app.sensors import expected_occupancy_from_board
from chessboard_app.server import build_state
from chessboard_app.wifi import WifiManager


class ServerStateTest(unittest.TestCase):
    def enabled_led_store(self, tmp):
        store = AppConfigStore(os.path.join(tmp, "config.json"))
        store.update_settings(leds_enabled=True)
        return store

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

    def test_update_settings_changes_public_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppConfigStore(os.path.join(tmp, "config.json"))
            config = store.update_settings(leds_enabled=True, board_orientation="black")

            self.assertEqual(config.leds_enabled, True)
            self.assertEqual(config.board_orientation, "black")
            state = build_state(store, StaticSensorReader(), GameSession(), WifiManager(runner=lambda args: ""))
            self.assertEqual(state["ledsEnabled"], True)
            self.assertEqual(state["boardOrientation"], "black")

    def test_state_highlights_legal_targets_when_one_piece_is_lifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.enabled_led_store(tmp)
            session = GameSession()
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


if __name__ == "__main__":
    unittest.main()
