import unittest

import chess

from chessboard_app.game_session import GameSession, parse_clocks
from chessboard_app.sensors import expected_occupancy_from_board


class GameSessionTest(unittest.TestCase):
    def test_loads_game_state_from_moves_and_clocks(self):
        session = GameSession()

        session.update_from_lichess_state({
            "id": "game1",
            "white": {"name": "alice", "rating": 1500},
            "black": {"name": "bob", "rating": 1600},
            "state": {"moves": "e2e4 e7e5", "wtime": 295000, "btime": 296000},
        })

        state = session.public_state()
        self.assertEqual(state["id"], "game1")
        expected = chess.Board()
        expected.push(chess.Move.from_uci("e2e4"))
        expected.push(chess.Move.from_uci("e7e5"))
        self.assertEqual(state["fen"], expected.fen())
        self.assertEqual(state["lastMove"], "e7e5")
        self.assertEqual(state["clock"]["whiteMs"], 295000)
        self.assertEqual(state["players"]["black"]["name"], "bob")

    def test_sync_status_reports_missing_and_extra_squares(self):
        session = GameSession()
        board = chess.Board()
        expected = expected_occupancy_from_board(board)
        actual = dict(expected)
        actual["e2"] = False
        actual["e4"] = True

        sync = session.sync_status(actual)

        self.assertFalse(sync["matches"])
        self.assertEqual(sync["missing"], ["e2"])
        self.assertEqual(sync["extra"], ["e4"])

    def test_detects_and_applies_physical_move(self):
        session = GameSession()
        before = expected_occupancy_from_board(session.board)
        after_board = session.board.copy()
        after_board.push(chess.Move.from_uci("e2e4"))
        after = expected_occupancy_from_board(after_board)

        result = session.detect_physical_move(before, after)

        self.assertEqual(result.kind, "move")
        self.assertEqual(result.uci, "e2e4")


class ClockParsingTest(unittest.TestCase):
    def test_parse_clocks_defaults_missing_values(self):
        self.assertEqual(parse_clocks({}), {"whiteMs": None, "blackMs": None})

    def test_parse_clocks_reads_lichess_state_names(self):
        self.assertEqual(
            parse_clocks({"wtime": 1000, "btime": 2000}),
            {"whiteMs": 1000, "blackMs": 2000},
        )


if __name__ == "__main__":
    unittest.main()
