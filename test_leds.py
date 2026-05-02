import unittest

import chess

from chessboard_app.leds import (
    DotStarLedController,
    DisabledLedController,
    LedSettings,
    MemoryLedController,
    MISSING_COLOR,
)
from led_mapping import SQUARE_TO_LED


def marker_led(square):
    return min(SQUARE_TO_LED[square])


class FakePixels:
    def __init__(self, count=81):
        self.values = [(0, 0, 0)] * count
        self.show_count = 0
        self.brightness = 1

    def __setitem__(self, index, value):
        self.values[index] = value

    def fill(self, value):
        self.values = [value] * len(self.values)

    def show(self):
        self.show_count += 1


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

        leds.show_setup_guidance(["e2", "d2", "c2"], ["e4"], frame=3)

        self.assertEqual(leds.mode, "setup")
        self.assertEqual(leds.highlighted_squares, ["e2", "d2", "c2"])
        self.assertEqual(leds.extra_squares, ["e4"])
        self.assertEqual(leds.setup_frame, 3)

    def test_dotstar_setup_guidance_animates_only_occupied_squares_and_marks_missing(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1"], ["h8"], frame=1, occupied_squares=["e4"])

        lit = {index for index, value in enumerate(pixels.values) if value != (0, 0, 0)}
        # Missing markers light a single LED; occupied squares light all 4 corners.
        e4_corners = set(SQUARE_TO_LED["e4"])
        expected_lit = {marker_led("a1"), marker_led("h8")} | e4_corners
        self.assertEqual(lit, expected_lit)
        self.assertEqual(pixels.values[marker_led("a1")], MISSING_COLOR)
        self.assertEqual(pixels.show_count, 1)

    def test_dotstar_setup_guidance_uses_dedicated_marker_per_missing_square(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1", "b1", "c1"], [], frame=0, occupied_squares=["h8"])

        for square in ["a1", "b1", "c1"]:
            self.assertEqual(pixels.values[marker_led(square)], MISSING_COLOR)
        self.assertNotEqual(pixels.values[marker_led("h8")], (0, 0, 0))

    def test_dotstar_setup_marker_turns_off_when_square_is_no_longer_missing(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1", "b1"], [], frame=0)
        self.assertEqual(pixels.values[marker_led("a1")], MISSING_COLOR)

        leds.show_setup_guidance(["b1"], [], frame=1)

        self.assertNotEqual(pixels.values[marker_led("a1")], MISSING_COLOR)
        self.assertEqual(pixels.values[marker_led("b1")], MISSING_COLOR)

    def test_dotstar_setup_marker_returns_as_constant_light_red_when_magnet_is_removed_again(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["b1"], [], frame=5, occupied_squares=["h8"])
        self.assertNotEqual(pixels.values[marker_led("a1")], MISSING_COLOR)

        leds.show_setup_guidance(["a1", "b1"], [], frame=80, occupied_squares=["h8"])

        self.assertEqual(pixels.values[marker_led("a1")], MISSING_COLOR)
        self.assertEqual(pixels.values[marker_led("b1")], MISSING_COLOR)

    def test_setup_guidance_animates_full_four_corner_square(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], [], frame=0, occupied_squares=["e4"])

        for index in SQUARE_TO_LED["e4"]:
            self.assertNotEqual(pixels.values[index], (0, 0, 0))

    def test_setup_guidance_breathes_over_time(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], [], frame=0, occupied_squares=["e4"])
        first = pixels.values[SQUARE_TO_LED["e4"][0]]
        leds.show_setup_guidance([], [], frame=16, occupied_squares=["e4"])
        second = pixels.values[SQUARE_TO_LED["e4"][0]]

        self.assertNotEqual(first, second)

    def test_setup_background_uses_warm_colors(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        for frame in [0, 64, 128]:
            leds.show_setup_guidance([], [], frame=frame, occupied_squares=["a1", "b1", "c1"])
            for red, green, blue in pixels.values:
                self.assertGreaterEqual(red + green, blue)

    def test_empty_last_row_does_not_animate(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1"], [], frame=8, occupied_squares=["e4"])

        last_row_squares = ["a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1"]
        last_row_marker_leds = {marker_led(square) for square in last_row_squares}
        animated_last_row = [
            index
            for index in last_row_marker_leds
            if pixels.values[index] != (0, 0, 0) and index != marker_led("a1")
        ]
        self.assertEqual(animated_last_row, [])

    def test_ready_animation_chases_first_to_last_led_and_clears(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_ready_animation(delay=0)

        self.assertEqual(leds.mode, "ready")
        self.assertEqual(pixels.values, [(0, 0, 0)] * 81)
        self.assertGreaterEqual(pixels.show_count, 82)


if __name__ == "__main__":
    unittest.main()
