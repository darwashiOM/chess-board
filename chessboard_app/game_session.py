from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import chess

from chessboard_app.move_detection import MoveDetectionResult, detect_move
from chessboard_app.sensors import diff_occupancy, expected_occupancy_from_board


def parse_clocks(state: Mapping[str, Any]) -> dict[str, int | None]:
    return {
        "whiteMs": state.get("wtime"),
        "blackMs": state.get("btime"),
    }


def board_from_uci_moves(moves_text: str) -> chess.Board:
    board = chess.Board()
    for uci in moves_text.split():
        board.push(chess.Move.from_uci(uci))
    return board


@dataclass
class GameSession:
    game_id: str | None = None
    board: chess.Board = field(default_factory=chess.Board)
    players: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "white": {"name": None, "rating": None},
        "black": {"name": None, "rating": None},
    })
    clock: dict[str, int | None] = field(default_factory=lambda: {
        "whiteMs": None,
        "blackMs": None,
    })
    status: str = "idle"
    last_move: str | None = None
    player_color: str | None = None

    def update_from_lichess_state(self, event: Mapping[str, Any]) -> None:
        self.game_id = event.get("id", self.game_id)
        self.players = {
            "white": _player_public(event.get("white", {})),
            "black": _player_public(event.get("black", {})),
        }
        state = event.get("state", event)
        moves_text = state.get("moves", "")
        self.board = board_from_uci_moves(moves_text)
        moves = moves_text.split()
        self.last_move = moves[-1] if moves else None
        self.clock = parse_clocks(state)
        self.status = state.get("status", event.get("status", "started"))

    def expected_occupancy(self) -> dict[str, bool]:
        return expected_occupancy_from_board(self.board)

    def sync_status(self, actual_occupancy: Mapping[str, bool]) -> dict[str, Any]:
        return diff_occupancy(self.expected_occupancy(), actual_occupancy)

    def detect_physical_move(
        self,
        before_occupancy: Mapping[str, bool],
        after_occupancy: Mapping[str, bool],
    ) -> MoveDetectionResult:
        return detect_move(self.board, before_occupancy, after_occupancy)

    def public_state(self) -> dict[str, Any]:
        return {
            "id": self.game_id,
            "fen": self.board.fen(),
            "turn": "white" if self.board.turn == chess.WHITE else "black",
            "status": self.status,
            "lastMove": self.last_move,
            "clock": self.clock,
            "players": self.players,
            "playerColor": self.player_color,
        }


def _player_public(player: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": player.get("name") or player.get("user", {}).get("name"),
        "rating": player.get("rating"),
    }
