import unittest

import chess

from chessboard_app.game_session import GameSession, parse_clocks
from chessboard_app.sensors import expected_occupancy_from_board


class GameSessionTest(unittest.TestCase):
    def puzzle_payload(self):
        return {
            "game": {
                "id": "setupGame",
                "pgn": "e4 e5",
                "players": [
                    {"color": "white", "name": "White", "rating": 1500},
                    {"color": "black", "name": "Black", "rating": 1500},
                ],
            },
            "puzzle": {
                "id": "puzzle1",
                "rating": 1200,
                "themes": ["opening", "short"],
                "initialPly": 2,
                "solution": ["g1f3", "b8c6"],
            },
        }

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
        self.assertEqual(state["pieces"]["e4"], "P")
        self.assertEqual(state["pieces"]["e5"], "p")

    def test_tracks_draw_offer_from_lichess_state(self):
        session = GameSession()

        session.update_from_lichess_state({
            "id": "game1",
            "state": {"moves": "e2e4", "wtime": 1000, "btime": 2000, "bdraw": True},
        })

        state = session.public_state()
        self.assertEqual(state["drawOffer"], "black")

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

    def test_tracks_synced_snapshot_and_applies_submitted_move(self):
        session = GameSession()
        before = expected_occupancy_from_board(session.board)
        after_board = session.board.copy()
        after_board.push(chess.Move.from_uci("e2e4"))
        after = expected_occupancy_from_board(after_board)

        session.mark_synced(before)
        result = session.detect_move_from_last_snapshot(after)
        session.apply_submitted_move(result.uci, after)

        self.assertEqual(result.uci, "e2e4")
        self.assertEqual(session.last_move, "e2e4")
        self.assertEqual(session.last_occupancy, after)
        self.assertEqual(session.board.peek(), chess.Move.from_uci("e2e4"))

    def test_loads_puzzle_position_and_public_piece_map(self):
        session = GameSession()

        session.load_puzzle(self.puzzle_payload())

        state = session.public_state()
        expected = chess.Board()
        expected.push(chess.Move.from_uci("e2e4"))
        expected.push(chess.Move.from_uci("e7e5"))
        self.assertEqual(state["mode"], "puzzle_setup")
        self.assertEqual(state["fen"], expected.fen())
        self.assertEqual(state["puzzle"]["id"], "puzzle1")
        self.assertEqual(state["puzzle"]["rating"], 1200)
        self.assertEqual(state["puzzle"]["solutionIndex"], 0)
        self.assertEqual(state["pieces"]["e4"], "P")
        self.assertEqual(state["pieces"]["e5"], "p")
        self.assertEqual(state["pieces"]["g1"], "N")
        self.assertEqual(state["playerColor"], "white")
        self.assertEqual(state["debug"]["playerColorReason"], "puzzle side to move after PGN")

    def test_puzzle_player_color_is_side_to_move_after_setup_position(self):
        session = GameSession()
        payload = self.puzzle_payload()
        payload["game"]["pgn"] = "d4"
        payload["puzzle"]["solution"] = ["g8f6"]

        session.load_puzzle(payload)

        self.assertEqual(session.public_state()["turn"], "black")
        self.assertEqual(session.public_state()["playerColor"], "black")
        self.assertEqual(session.public_state()["debug"]["playerColorReason"], "puzzle side to move after PGN")

    def test_puzzle_accepts_correct_move_applies_reply_and_completes(self):
        session = GameSession()
        session.load_puzzle(self.puzzle_payload())
        before = expected_occupancy_from_board(session.board)
        after_board = session.board.copy()
        after_board.push(chess.Move.from_uci("g1f3"))
        after = expected_occupancy_from_board(after_board)
        reply_board = after_board.copy()
        reply_board.push(chess.Move.from_uci("b8c6"))
        reply_after = expected_occupancy_from_board(reply_board)

        session.start_puzzle(before)
        result = session.submit_puzzle_move(after)

        self.assertEqual(result["accepted"], True)
        self.assertEqual(result["move"], "g1f3")
        self.assertEqual(result["reply"], "b8c6")
        self.assertEqual(session.last_move, "b8c6")
        self.assertEqual(session.public_state()["puzzle"]["status"], "complete")
        self.assertEqual(session.public_state()["puzzle"]["solutionIndex"], 2)
        self.assertEqual(session.public_state()["pieces"]["b8"], "n")
        self.assertNotIn("c6", session.public_state()["pieces"])

        session.mark_synced(reply_after)

        self.assertNotIn("b8", session.public_state()["pieces"])
        self.assertEqual(session.public_state()["pieces"]["c6"], "n")

    def test_puzzle_syncs_after_player_copies_reply_without_detecting_new_move(self):
        session = GameSession()
        session.load_puzzle(self.puzzle_payload())
        before = expected_occupancy_from_board(session.board)
        user_board = session.board.copy()
        user_board.push(chess.Move.from_uci("g1f3"))
        user_after = expected_occupancy_from_board(user_board)
        reply_board = user_board.copy()
        reply_board.push(chess.Move.from_uci("b8c6"))
        reply_after = expected_occupancy_from_board(reply_board)

        session.start_puzzle(before)
        session.submit_puzzle_move(user_after)
        result = session.submit_puzzle_move(reply_after, allow_unsynced=True)

        self.assertEqual(result["accepted"], False)
        self.assertEqual(result["kind"], "synced")
        self.assertEqual(result["message"], "Board synced. Puzzle is complete.")
        self.assertEqual(session.last_occupancy, reply_after)

    def test_puzzle_syncs_after_reply_in_longer_puzzle_and_keeps_playing(self):
        payload = self.puzzle_payload()
        payload["puzzle"]["solution"] = ["g1f3", "b8c6", "f1b5"]
        session = GameSession()
        session.load_puzzle(payload)
        before = expected_occupancy_from_board(session.board)
        user_board = session.board.copy()
        user_board.push(chess.Move.from_uci("g1f3"))
        user_after = expected_occupancy_from_board(user_board)
        reply_board = user_board.copy()
        reply_board.push(chess.Move.from_uci("b8c6"))
        reply_after = expected_occupancy_from_board(reply_board)

        session.start_puzzle(before)
        session.submit_puzzle_move(user_after)
        result = session.submit_puzzle_move(reply_after, allow_unsynced=True)

        self.assertEqual(result["accepted"], False)
        self.assertEqual(result["kind"], "synced")
        self.assertEqual(result["message"], "Board synced. Play the next puzzle move.")
        self.assertEqual(session.status, "puzzle_play")
        self.assertEqual(session.last_occupancy, reply_after)

    def test_puzzle_rejects_wrong_physical_move_without_advancing(self):
        session = GameSession()
        session.load_puzzle(self.puzzle_payload())
        before = expected_occupancy_from_board(session.board)
        wrong_board = session.board.copy()
        wrong_board.push(chess.Move.from_uci("d2d4"))

        session.start_puzzle(before)
        result = session.submit_puzzle_move(expected_occupancy_from_board(wrong_board))

        self.assertEqual(result["accepted"], False)
        self.assertEqual(result["expected"], "g1f3")
        self.assertEqual(session.public_state()["puzzle"]["solutionIndex"], 0)


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
