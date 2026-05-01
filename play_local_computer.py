from __future__ import annotations

import argparse
import random
import time
from typing import Callable, Mapping

import chess

from chessboard_app.leds import DotStarLedController, LedSettings
from chessboard_app.move_detection import detect_move
from chessboard_app.sensors import McpSensorReader, diff_occupancy, expected_occupancy_from_board


ChooseMove = Callable[[chess.Board], chess.Move]


def choose_computer_move(board: chess.Board) -> chess.Move:
    return random.choice(list(board.legal_moves))


def changed_squares(before: Mapping[str, bool], after: Mapping[str, bool]) -> tuple[list[str], list[str]]:
    lifted = [
        square
        for square, was_present in before.items()
        if was_present and not after.get(square, False)
    ]
    placed = [
        square
        for square, is_present in after.items()
        if is_present and not before.get(square, False)
    ]
    return lifted, placed


class LocalComputerGame:
    def __init__(
        self,
        leds,
        choose_reply: ChooseMove = choose_computer_move,
        printer: Callable[[str], None] | None = print,
    ):
        self.board = chess.Board()
        self.leds = leds
        self.choose_reply = choose_reply
        self.printer = printer
        self.last_occupancy = expected_occupancy_from_board(self.board)
        self.pending_before: dict[str, bool] | None = None
        self.pending_from: str | None = None
        self.pending_computer_move: str | None = None

    def handle_snapshot(self, occupancy: Mapping[str, bool]) -> str:
        occupancy = dict(occupancy)

        if self.pending_computer_move:
            if diff_occupancy(expected_occupancy_from_board(self.board), occupancy)["matches"]:
                self.pending_computer_move = None
                self.last_occupancy = occupancy
                self.leds.clear()
                return "computer_move_confirmed"
            self.leds.show_move(self.pending_computer_move)
            return "waiting_for_computer_move"

        if self.pending_before is None:
            lifted, placed = changed_squares(self.last_occupancy, occupancy)
            if len(lifted) == 1 and not placed:
                self.pending_before = dict(self.last_occupancy)
                self.pending_from = lifted[0]
                self.leds.show_legal_targets(self.board, lifted[0])
                self.last_occupancy = occupancy
                return "piece_lifted"
            self.last_occupancy = occupancy
            return "idle"

        lifted, placed = changed_squares(self.last_occupancy, occupancy)
        if self.pending_from and occupancy.get(self.pending_from, False):
            self.pending_before = None
            self.pending_from = None
            self.last_occupancy = occupancy
            self.leds.clear()
            return "move_cancelled"
        if placed:
            before = self.pending_before
            self.pending_before = None
            self.pending_from = None
            self.last_occupancy = occupancy
            return self.accept_player_position(before, occupancy)
        if lifted:
            self.last_occupancy = occupancy
            return "piece_still_lifted"
        self.last_occupancy = occupancy
        return "piece_still_lifted"

    def accept_player_position(self, before: Mapping[str, bool], after: Mapping[str, bool]) -> str:
        result = detect_move(self.board, before, after)
        if result.kind != "move" or result.uci is None:
            self.leds.clear()
            self.print(f"Move not accepted: {result.kind} {result.reason or ''}".strip())
            return result.kind

        player_move = chess.Move.from_uci(result.uci)
        self.board.push(player_move)
        self.print(f"Your move: {player_move.uci()}")

        if self.board.is_game_over():
            self.leds.clear()
            self.print(f"Game over: {self.board.result()}")
            return "game_over"

        reply = self.choose_reply(self.board)
        self.board.push(reply)
        self.pending_computer_move = reply.uci()
        self.leds.show_move(self.pending_computer_move)
        self.print(f"Computer move: {self.pending_computer_move}")
        self.print("Move the lit piece on the board, then the game will continue.")

        if self.board.is_game_over():
            self.print(f"Game over: {self.board.result()}")
        return "computer_move"

    def print(self, message: str) -> None:
        if self.printer:
            self.printer(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a local full-board game against a random computer move generator.")
    parser.add_argument("--brightness", type=float, default=0.1)
    parser.add_argument("--poll-seconds", type=float, default=0.05)
    args = parser.parse_args()

    sensor_reader = McpSensorReader.create()
    leds = DotStarLedController.create()
    leds.apply_settings(LedSettings(enabled=True, brightness=args.brightness))
    game = LocalComputerGame(leds)
    game.last_occupancy = sensor_reader.read().as_dict()

    print("=== Full Chess Board Local Computer Test ===")
    print("Set the pieces to the normal starting position.")
    print("Lift one piece to light legal moves. Place it on a legal square to move.")
    print("The computer replies randomly; move the lit from/to squares for it.")
    print("Press Ctrl+C to stop.")
    print()
    print(game.board)

    try:
        while True:
            time.sleep(args.poll_seconds)
            status = game.handle_snapshot(sensor_reader.read().as_dict())
            if status in {"computer_move_confirmed", "move_cancelled"}:
                print(status.replace("_", " "))
    except KeyboardInterrupt:
        leds.clear()
        print("\nStopped.")


if __name__ == "__main__":
    main()
