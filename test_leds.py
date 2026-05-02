import unittest

import chess

from chessboard_app.orientation import rotate_square_180
from chessboard_app.leds import (
    BLACK_PIECE_COLOR,
    BLACK_PLACED_COLOR,
    DESTINATION_COLOR,
    DotStarLedController,
    DisabledLedController,
    EXTRA_COLOR,
    LEGAL_SOURCE_COLOR,
    LedSettings,
    MemoryLedController,
    MISSING_COLOR,
    SHARED_LED_COLOR,
    WARM_GLOW_COLOR,
    WHITE_PIECE_COLOR,
    WHITE_PLACED_COLOR,
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
    def test_gameplay_colors_are_encoded_for_bgr_led_hardware(self):
        self.assertEqual(WHITE_PIECE_COLOR, (220, 0, 180))
        self.assertEqual(BLACK_PIECE_COLOR, (0, 120, 0))
        self.assertEqual(SHARED_LED_COLOR, (0, 0, 160))
        self.assertEqual(WHITE_PLACED_COLOR, (180, 100, 150))
        self.assertEqual(BLACK_PLACED_COLOR, (180, 100, 150))
        self.assertEqual(DESTINATION_COLOR, (120, 0, 0))
        self.assertEqual(MISSING_COLOR, (6, 14, 200))

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

        leds.show_setup_guidance(["e2", "d2", "c2"], ["e4"], frame=3, expected_board=chess.Board())

        self.assertEqual(leds.mode, "setup")
        self.assertEqual(leds.highlighted_squares, ["e2", "d2", "c2"])
        self.assertEqual(leds.extra_squares, ["e4"])
        self.assertEqual(leds.setup_frame, 3)

    def test_dotstar_setup_guidance_lights_only_missing_and_extra_squares(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1"], ["h8"], frame=12, occupied_squares=["e4"], expected_board=chess.Board())

        lit = {index for index, value in enumerate(pixels.values) if value != (0, 0, 0)}
        expected_lit = set(SQUARE_TO_LED["a1"]) | set(SQUARE_TO_LED["h8"])
        self.assertEqual(lit, expected_lit)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["a1"]], [WHITE_PIECE_COLOR] * 4)
        self.assertEqual(pixels.show_count, 1)

    def test_dotstar_setup_guidance_uses_dedicated_marker_per_missing_square(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1", "b1", "c1"], [], frame=0, occupied_squares=["h8"], expected_board=chess.Board())

        for square in ["a1", "b1", "c1"]:
            values = [pixels.values[index] for index in SQUARE_TO_LED[square]]
            self.assertTrue(any(value in {WHITE_PIECE_COLOR, SHARED_LED_COLOR} for value in values))
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["h8"]], [BLACK_PLACED_COLOR] * 4)

    def test_dotstar_setup_marker_turns_off_when_square_is_no_longer_missing(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1", "b1"], [], frame=0)
        self.assertIn(WARM_GLOW_COLOR, [pixels.values[index] for index in SQUARE_TO_LED["a1"]])

        leds.show_setup_guidance(["b1"], [], frame=8)

        a1_only = set(SQUARE_TO_LED["a1"]) - set(SQUARE_TO_LED["b1"])
        for index in a1_only:
            self.assertNotEqual(pixels.values[index], MISSING_COLOR)
        self.assertIn(WARM_GLOW_COLOR, [pixels.values[index] for index in SQUARE_TO_LED["b1"]])

    def test_dotstar_setup_marker_returns_as_constant_light_red_when_magnet_is_removed_again(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["b1"], [], frame=5, occupied_squares=["h8"], expected_board=chess.Board())
        a1_only = set(SQUARE_TO_LED["a1"]) - set(SQUARE_TO_LED["b1"])
        for index in a1_only:
            self.assertNotEqual(pixels.values[index], MISSING_COLOR)

        leds.show_setup_guidance(["a1", "b1"], [], frame=80, occupied_squares=["h8"], expected_board=chess.Board())

        self.assertIn(WHITE_PIECE_COLOR, [pixels.values[index] for index in SQUARE_TO_LED["a1"]])
        self.assertIn(WHITE_PIECE_COLOR, [pixels.values[index] for index in SQUARE_TO_LED["b1"]])

    def test_missing_square_marks_all_four_corners_without_animation(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["e4"], [], frame=0)
        first_values = [pixels.values[index] for index in SQUARE_TO_LED["e4"]]
        leds.show_setup_guidance(["e4"], [], frame=16)
        second_values = [pixels.values[index] for index in SQUARE_TO_LED["e4"]]

        self.assertEqual(first_values, [WARM_GLOW_COLOR] * 4)
        self.assertEqual(second_values, [WARM_GLOW_COLOR] * 4)

    def test_missing_square_takes_shared_led_from_occupied_neighbor(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        shared = set(SQUARE_TO_LED["a1"]) & set(SQUARE_TO_LED["b1"])
        leds.show_setup_guidance(["b1"], [], frame=8, occupied_squares=["a1"], expected_board=chess.Board())

        for index in shared:
            self.assertEqual(pixels.values[index], SHARED_LED_COLOR)

    def test_same_color_adjacent_missing_pieces_do_not_use_shared_led_color(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["a1", "b1"], [], expected_board=chess.Board(), expected_player_color="white")

        shared = set(SQUARE_TO_LED["a1"]) & set(SQUARE_TO_LED["b1"])
        for index in shared:
            self.assertEqual(pixels.values[index], WHITE_PIECE_COLOR)

    def test_adjacent_missing_puzzle_pieces_use_shared_led_color(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        board = chess.Board("8/8/4k2p/5p1P/8/5PK1/8/8 b - - 2 53")
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1, orientation="black"))

        leds.show_setup_guidance(["h6", "h5"], [], expected_board=board, expected_player_color="black")

        shared = set(SQUARE_TO_LED["a3"]) & set(SQUARE_TO_LED["a4"])
        for index in shared:
            self.assertEqual(pixels.values[index], SHARED_LED_COLOR)

    def test_extra_square_uses_static_blue_without_animation(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], ["e4"], frame=0, occupied_squares=["e4"])
        first_values = [pixels.values[index] for index in SQUARE_TO_LED["e4"]]
        leds.show_setup_guidance([], ["e4"], frame=12, occupied_squares=["e4"])
        second_values = [pixels.values[index] for index in SQUARE_TO_LED["e4"]]

        self.assertEqual(first_values, [EXTRA_COLOR] * 4)
        self.assertEqual(second_values, [EXTRA_COLOR] * 4)

    def test_setup_guidance_confirms_correctly_occupied_expected_pieces_with_piece_mix_colors(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        board = chess.Board()
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], [], frame=0, occupied_squares=["e2", "e7"], expected_board=board)

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [WHITE_PLACED_COLOR] * 4)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e7"]], [BLACK_PLACED_COLOR] * 4)

    def test_setup_guidance_confirms_yellow_and_blue_pieces_with_same_white_color(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        board = chess.Board()
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], [], frame=0, occupied_squares=["e2", "e7"], expected_board=board)

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [BLACK_PLACED_COLOR] * 4)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e7"]], [BLACK_PLACED_COLOR] * 4)

    def test_setup_guidance_leaves_unknown_occupied_square_off_when_it_is_not_missing_or_extra(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance([], [], frame=0, occupied_squares=["e4"])

        for index in SQUARE_TO_LED["e4"]:
            self.assertEqual(pixels.values[index], (0, 0, 0))

    def test_legal_targets_use_different_source_and_destination_colors(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_legal_targets(chess.Board(), "e2")

        destination_indexes = set(SQUARE_TO_LED["e3"]) | set(SQUARE_TO_LED["e4"])
        for index in set(SQUARE_TO_LED["e2"]) - destination_indexes:
            self.assertEqual(pixels.values[index], LEGAL_SOURCE_COLOR)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e4"]], [DESTINATION_COLOR] * 4)

    def test_legal_target_shared_edge_keeps_lifted_source_color(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_legal_targets(chess.Board(), "e2")

        shared_with_e3 = set(SQUARE_TO_LED["e2"]) & set(SQUARE_TO_LED["e3"])
        for index in shared_with_e3:
            self.assertEqual(pixels.values[index], LEGAL_SOURCE_COLOR)

    def test_opponent_move_uses_different_from_and_to_colors(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_move("e7e5")

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e7"]], [LEGAL_SOURCE_COLOR] * 4)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e5"]], [DESTINATION_COLOR] * 4)

    def test_setup_guidance_correct_square_changes_from_missing_red_to_dim_amber(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["e2"], [], frame=0, occupied_squares=[])
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [WARM_GLOW_COLOR] * 4)
        leds.show_setup_guidance([], [], frame=1, occupied_squares=["e2"], expected_board=chess.Board())

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [WHITE_PLACED_COLOR] * 4)

    def test_setup_guidance_missing_expected_squares_use_player_piece_colors(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["e2", "e7"], [], expected_board=chess.Board(), expected_player_color="white")

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [WHITE_PIECE_COLOR] * 4)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e7"]], [BLACK_PIECE_COLOR] * 4)

    def test_setup_guidance_missing_expected_squares_flip_colors_when_player_is_black(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))

        leds.show_setup_guidance(["e2", "e7"], [], expected_board=chess.Board(), expected_player_color="black")

        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e2"]], [BLACK_PIECE_COLOR] * 4)
        self.assertEqual([pixels.values[index] for index in SQUARE_TO_LED["e7"]], [WHITE_PIECE_COLOR] * 4)

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

    def test_clear_sends_multiple_zero_frames_to_reliably_latch_off(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1))
        pixels.values[10] = WHITE_PIECE_COLOR
        pixels.show_count = 0

        leds.clear()

        self.assertEqual(pixels.values, [(0, 0, 0)] * 81)
        self.assertGreaterEqual(pixels.show_count, 3)

    def test_black_orientation_lights_rotated_physical_square(self):
        pixels = FakePixels()
        leds = DotStarLedController(pixels)
        leds.apply_settings(LedSettings(enabled=True, brightness=0.1, orientation="black"))

        leds.show_move("a8a7")

        logical_from = set(SQUARE_TO_LED["a8"])
        physical_from = set(SQUARE_TO_LED[rotate_square_180("a8")])
        self.assertTrue(any(pixels.values[index] == LEGAL_SOURCE_COLOR for index in physical_from))
        self.assertTrue(all(pixels.values[index] == (0, 0, 0) for index in logical_from - physical_from))


if __name__ == "__main__":
    unittest.main()
