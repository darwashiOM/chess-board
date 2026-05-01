import unittest

import chess

from chessboard_app.leds import DisabledLedController, LedSettings, MemoryLedController


class LedTest(unittest.TestCase):
    def test_disabled_controller_reports_state(self):
        leds = DisabledLedController()

        leds.apply_settings(LedSettings(enabled=True, brightness=0.4))

        self.assertEqual(leds.status(), {
            "available": False,
            "enabled": True,
            "brightness": 0.4,
            "mode": "disabled",
            "testPattern": "idle",
        })

    def test_disabled_controller_records_test_pattern(self):
        leds = DisabledLedController()

        leds.run_test("border")

        self.assertEqual(leds.status()["testPattern"], "border")
        with self.assertRaises(ValueError):
            leds.run_test("unknown")


class MemoryLedControllerTest(unittest.TestCase):
    def test_highlights_legal_targets_for_lifted_piece(self):
        leds = MemoryLedController()
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_legal_targets(chess.Board(), "e2")

        self.assertEqual(leds.mode, "legal-targets")
        self.assertEqual(leds.highlighted_squares, ["e3", "e4"])

    def test_highlights_last_move_for_opponent_move_to_copy(self):
        leds = MemoryLedController()
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_move("e7e5")

        self.assertEqual(leds.mode, "move")
        self.assertEqual(leds.highlighted_squares, ["e7", "e5"])

    def test_setup_guidance_tracks_missing_and_extra_squares(self):
        leds = MemoryLedController()
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["e2", "d2"], ["e4"], frame=3)

        self.assertEqual(leds.mode, "setup")
        self.assertEqual(leds.highlighted_squares, ["e2", "d2"])
        self.assertEqual(leds.extra_squares, ["e4"])
        self.assertEqual(leds.setup_frame, 3)


if __name__ == "__main__":
    unittest.main()
