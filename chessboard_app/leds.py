from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Sequence

import chess

from led_mapping import LED_GRID, SQUARE_TO_LED


SETUP_BREATH_PERIOD = 32
SETUP_PATTERN_PERIOD = 48
MISSING_COLOR = (80, 8, 8)
EXTRA_COLOR = (95, 36, 0)


@dataclass(frozen=True)
class LedSettings:
    enabled: bool = False
    brightness: float = 0.1


class DisabledLedController:
    def __init__(self):
        self.settings = LedSettings()
        self.test_pattern = "idle"

    def apply_settings(self, settings: LedSettings) -> None:
        self.settings = settings

    def run_test(self, pattern: str) -> None:
        if pattern not in {"all", "border", "square", "idle"}:
            raise ValueError("unknown LED test pattern")
        self.test_pattern = pattern

    def clear(self) -> None:
        self.test_pattern = "idle"

    def show_legal_targets(self, board: chess.Board, from_square: str) -> None:
        self.test_pattern = "legal-targets"

    def show_move(self, uci: str) -> None:
        self.test_pattern = "move"

    def show_setup_guidance(
        self,
        missing_squares: Sequence[str],
        extra_squares: Sequence[str],
        frame: int = 0,
    ) -> None:
        self.test_pattern = "setup"

    def show_ready_animation(self, delay: float = 0.008) -> None:
        self.test_pattern = "ready"

    def status(self) -> dict[str, object]:
        return {
            "available": False,
            "enabled": self.settings.enabled,
            "brightness": self.settings.brightness,
            "mode": "disabled",
            "testPattern": self.test_pattern,
        }


class MemoryLedController(DisabledLedController):
    def __init__(self):
        super().__init__()
        self.mode = "idle"
        self.highlighted_squares: list[str] = []
        self.extra_squares: list[str] = []
        self.setup_frame = 0

    def clear(self) -> None:
        self.mode = "idle"
        self.highlighted_squares = []
        self.extra_squares = []

    def run_test(self, pattern: str) -> None:
        super().run_test(pattern)
        self.mode = pattern
        self.highlighted_squares = []
        self.extra_squares = []

    def show_legal_targets(self, board: chess.Board, from_square: str) -> None:
        self.mode = "legal-targets"
        self.extra_squares = []
        source = chess.parse_square(from_square)
        self.highlighted_squares = [
            chess.square_name(move.to_square)
            for move in board.legal_moves
            if move.from_square == source
        ]

    def show_move(self, uci: str) -> None:
        self.mode = "move"
        self.extra_squares = []
        self.highlighted_squares = [uci[:2], uci[2:4]]

    def show_setup_guidance(
        self,
        missing_squares: Sequence[str],
        extra_squares: Sequence[str],
        frame: int = 0,
    ) -> None:
        self.mode = "setup"
        self.highlighted_squares = list(missing_squares)
        self.extra_squares = list(extra_squares)
        self.setup_frame = frame

    def show_ready_animation(self, delay: float = 0.008) -> None:
        self.mode = "ready"
        self.highlighted_squares = []
        self.extra_squares = []

    def status(self) -> dict[str, object]:
        return {
            "available": True,
            "enabled": self.settings.enabled,
            "brightness": self.settings.brightness,
            "mode": self.mode,
            "testPattern": self.test_pattern,
            "highlightedSquares": self.highlighted_squares,
            "extraSquares": self.extra_squares,
        }


class DotStarLedController(MemoryLedController):
    def __init__(self, pixels, count: int = 81):
        super().__init__()
        self.pixels = pixels
        self.count = count

    @classmethod
    def create(cls, count: int = 81) -> DotStarLedController:
        import board as circuit_board  # type: ignore
        import adafruit_dotstar as dotstar  # type: ignore

        pixels = dotstar.DotStar(
            circuit_board.SCK,
            circuit_board.MOSI,
            count,
            brightness=0.1,
            auto_write=False,
        )
        return cls(pixels, count=count)

    def apply_settings(self, settings: LedSettings) -> None:
        super().apply_settings(settings)
        self.pixels.brightness = settings.brightness
        if not settings.enabled:
            self.clear()

    def clear(self) -> None:
        super().clear()
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    def run_test(self, pattern: str) -> None:
        super().run_test(pattern)
        if not self.settings.enabled:
            self.clear()
            return
        if pattern == "idle":
            self.clear()
        elif pattern == "all":
            self._light_indexes(range(self.count), (0, 0, 80))
        elif pattern == "border":
            border = set()
            for row in (0, 8):
                border.update(range(row * 9, row * 9 + 9))
            for row in range(9):
                border.add(row * 9)
                border.add(row * 9 + 8)
            self._light_indexes(border, (0, 80, 30))
        elif pattern == "square":
            self._light_squares(["e4", "d4", "e5", "d5"], (80, 60, 0))

    def show_legal_targets(self, board: chess.Board, from_square: str) -> None:
        super().show_legal_targets(board, from_square)
        if self.settings.enabled:
            self._light_squares(self.highlighted_squares, (80, 70, 0))

    def show_move(self, uci: str) -> None:
        super().show_move(uci)
        if self.settings.enabled:
            self._light_squares(self.highlighted_squares, (0, 50, 90))

    def show_setup_guidance(
        self,
        missing_squares: Sequence[str],
        extra_squares: Sequence[str],
        frame: int = 0,
    ) -> None:
        super().show_setup_guidance(missing_squares, extra_squares, frame)
        if not self.settings.enabled:
            self.clear()
            return

        self.pixels.fill((0, 0, 0))
        self._render_setup_background(frame)
        self._set_square_markers(missing_squares, MISSING_COLOR)
        self._set_square_markers(extra_squares, EXTRA_COLOR)
        self.pixels.show()

    def show_ready_animation(self, delay: float = 0.008) -> None:
        super().show_ready_animation(delay)
        if not self.settings.enabled:
            self.clear()
            return
        for index in range(self.count):
            self.pixels.fill((0, 0, 0))
            for tail_offset, level in enumerate((1.0, 0.45, 0.18)):
                tail_index = index - tail_offset
                if 0 <= tail_index < self.count:
                    self.pixels[tail_index] = _scale_color((0, 80, 28), level)
            self.pixels.show()
            if delay:
                time.sleep(delay)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    def _light_squares(self, squares: Sequence[str], color: tuple[int, int, int]) -> None:
        indexes = []
        for square in squares:
            indexes.extend(SQUARE_TO_LED.get(square, []))
        self._light_indexes(indexes, color)

    def _set_square_color(self, squares: Sequence[str], color: tuple[int, int, int]) -> None:
        for square in squares:
            for index in SQUARE_TO_LED.get(square, []):
                if 0 <= index < self.count:
                    self.pixels[index] = color

    def _set_square_markers(self, squares: Sequence[str], color: tuple[int, int, int]) -> None:
        for square in squares:
            indexes = SQUARE_TO_LED.get(square, [])
            if indexes:
                index = min(indexes)
                if 0 <= index < self.count:
                    self.pixels[index] = color

    def _render_setup_background(self, frame: int) -> None:
        pattern = (frame // SETUP_PATTERN_PERIOD) % 3
        if pattern == 0:
            self._render_diagonal_wave(frame)
        elif pattern == 1:
            self._render_soft_scan(frame)
        else:
            self._render_comet_field(frame)

    def _render_diagonal_wave(self, frame: int) -> None:
        for row, grid_row in enumerate(LED_GRID):
            for col, index in enumerate(grid_row):
                phase = ((row + col + frame) % 12) / 12
                glow = 0.18 + 0.82 * ((1 - math.cos(phase * math.tau)) / 2)
                self.pixels[index] = _scale_color((26, 12, 2), glow)

    def _render_soft_scan(self, frame: int) -> None:
        scan_col = (frame // 3) % 9
        for row, grid_row in enumerate(LED_GRID):
            for col, index in enumerate(grid_row):
                distance = min(abs(col - scan_col), 9 - abs(col - scan_col))
                glow = max(0.16, 1 - distance * 0.32)
                self.pixels[index] = _scale_color((28, 16, 4), glow)

    def _render_comet_field(self, frame: int) -> None:
        head = frame % self.count
        for index in range(self.count):
            distance = (head - index) % self.count
            if distance <= 5:
                self.pixels[index] = _scale_color((34, 14, 1), 1 - distance * 0.14)
            else:
                self.pixels[index] = (2, 1, 0)

    def _light_indexes(self, indexes, color: tuple[int, int, int]) -> None:
        self.pixels.fill((0, 0, 0))
        for index in indexes:
            if 0 <= index < self.count:
                self.pixels[index] = color
        self.pixels.show()


def _breath_value(frame: int) -> float:
    phase = (frame % SETUP_BREATH_PERIOD) / SETUP_BREATH_PERIOD
    return 0.18 + 0.82 * ((1 - math.cos(phase * math.tau)) / 2)


def _scale_color(color: tuple[int, int, int], scale: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * scale))) for channel in color)
