import unittest

import chess

from chessboard_app.leds import MemoryLedController
from chessboard_app.sensors import expected_occupancy_from_board
from play_local_computer import LocalComputerGame, choose_computer_move


class LocalComputerGameTest(unittest.TestCase):
    def test_choose_computer_move_returns_legal_move(self):
        board = chess.Board()

        move = choose_computer_move(board)

        self.assertIn(move, board.legal_moves)

    def test_player_move_then_computer_move_updates_board_and_lights_reply(self):
        leds = MemoryLedController()
        game = LocalComputerGame(
            leds=leds,
            choose_reply=lambda board: chess.Move.from_uci("e7e5"),
            printer=None,
        )
        before = expected_occupancy_from_board(game.board)
        moved = game.board.copy()
        moved.push(chess.Move.from_uci("e2e4"))
        after = expected_occupancy_from_board(moved)

        result = game.accept_player_position(before, after)

        self.assertEqual(result, "computer_move")
        self.assertEqual(game.pending_computer_move, "e7e5")
        self.assertEqual(leds.highlighted_squares, ["e7", "e5"])
        self.assertEqual(game.board.peek().uci(), "e7e5")

    def test_lifted_piece_lights_legal_targets(self):
        leds = MemoryLedController()
        game = LocalComputerGame(leds=leds, printer=None)
        occupancy = expected_occupancy_from_board(game.board)
        occupancy["e2"] = False

        result = game.handle_snapshot(occupancy)

        self.assertEqual(result, "piece_lifted")
        self.assertEqual(game.pending_before["e2"], True)
        self.assertEqual(leds.highlighted_squares, ["e3", "e4"])

    def test_confirms_computer_move_when_physical_board_matches(self):
        leds = MemoryLedController()
        game = LocalComputerGame(
            leds=leds,
            choose_reply=lambda board: chess.Move.from_uci("e7e5"),
            printer=None,
        )
        before = expected_occupancy_from_board(game.board)
        player_board = game.board.copy()
        player_board.push(chess.Move.from_uci("e2e4"))
        game.accept_player_position(before, expected_occupancy_from_board(player_board))

        result = game.handle_snapshot(expected_occupancy_from_board(game.board))

        self.assertEqual(result, "computer_move_confirmed")
        self.assertIsNone(game.pending_computer_move)
        self.assertEqual(leds.highlighted_squares, [])


if __name__ == "__main__":
    unittest.main()
