import unittest

import chess

from chessboard_app.move_detection import MoveDetectionResult, detect_move
from chessboard_app.sensors import expected_occupancy_from_board


def occupancy_after(board, move_uci):
    moved = board.copy()
    moved.push(chess.Move.from_uci(move_uci))
    return expected_occupancy_from_board(moved)


class MoveDetectionTest(unittest.TestCase):
    def test_detects_normal_legal_move(self):
        board = chess.Board()
        before = expected_occupancy_from_board(board)
        after = occupancy_after(board, "e2e4")

        result = detect_move(board, before, after)

        self.assertEqual(result, MoveDetectionResult("move", "e2e4", None))

    def test_detects_capture(self):
        board = chess.Board("8/8/8/3p4/4P3/8/8/8 w - - 0 1")
        before = expected_occupancy_from_board(board)
        after = occupancy_after(board, "e4d5")

        result = detect_move(board, before, after)

        self.assertEqual(result, MoveDetectionResult("move", "e4d5", None))

    def test_detects_castling(self):
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        before = expected_occupancy_from_board(board)
        after = occupancy_after(board, "e1g1")

        result = detect_move(board, before, after)

        self.assertEqual(result, MoveDetectionResult("move", "e1g1", None))

    def test_detects_en_passant(self):
        board = chess.Board("8/8/8/3pP3/8/8/8/8 w - d6 0 1")
        before = expected_occupancy_from_board(board)
        after = occupancy_after(board, "e5d6")

        result = detect_move(board, before, after)

        self.assertEqual(result, MoveDetectionResult("move", "e5d6", None))

    def test_reports_promotion_choice_needed(self):
        board = chess.Board("8/P7/8/8/8/8/8/8 w - - 0 1")
        before = expected_occupancy_from_board(board)
        after = occupancy_after(board, "a7a8q")

        result = detect_move(board, before, after)

        self.assertEqual(result.kind, "promotion_required")
        self.assertEqual(result.uci, "a7a8")

    def test_rejects_illegal_transition(self):
        board = chess.Board()
        before = expected_occupancy_from_board(board)
        after = dict(before)
        after["e2"] = False
        after["e5"] = True

        result = detect_move(board, before, after)

        self.assertEqual(result.kind, "illegal")
        self.assertIsNone(result.uci)


if __name__ == "__main__":
    unittest.main()
