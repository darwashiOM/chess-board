import os
import tempfile
import unittest

from chessboard_app.config import AppConfigStore
from chessboard_app.game_session import GameSession
from chessboard_app.sensors import StaticSensorReader
from chessboard_app.server import build_state
from chessboard_app.wifi import WifiManager


class ServerStateTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
