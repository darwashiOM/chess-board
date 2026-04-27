from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import chess

from chessboard_app.sensors import expected_occupancy_from_board


@dataclass(frozen=True)
class MoveDetectionResult:
    kind: str
    uci: str | None = None
    reason: str | None = None


def _same_occupancy(left: Mapping[str, bool], right: Mapping[str, bool]) -> bool:
    return all(bool(left.get(square, False)) == bool(right.get(square, False)) for square in chess.SQUARE_NAMES)


def _base_promotion_uci(move: chess.Move) -> str:
    return chess.square_name(move.from_square) + chess.square_name(move.to_square)


def detect_move(
    board: chess.Board,
    before: Mapping[str, bool],
    after: Mapping[str, bool],
) -> MoveDetectionResult:
    expected_before = expected_occupancy_from_board(board)
    if not _same_occupancy(before, expected_before):
        return MoveDetectionResult("sync_required", reason="before snapshot does not match game position")

    matching_moves = []
    promotion_bases = set()

    for move in board.legal_moves:
        candidate = board.copy()
        candidate.push(move)
        candidate_after = expected_occupancy_from_board(candidate)
        if _same_occupancy(after, candidate_after):
            if move.promotion:
                promotion_bases.add(_base_promotion_uci(move))
            else:
                matching_moves.append(move)

    if len(matching_moves) == 1:
        return MoveDetectionResult("move", matching_moves[0].uci())
    if len(matching_moves) > 1:
        return MoveDetectionResult("ambiguous", reason="multiple legal moves match the same occupancy")
    if len(promotion_bases) == 1:
        return MoveDetectionResult("promotion_required", next(iter(promotion_bases)))
    if len(promotion_bases) > 1:
        return MoveDetectionResult("ambiguous", reason="multiple promotion moves match the same occupancy")
    return MoveDetectionResult("illegal", reason="no legal move matches the occupancy change")
