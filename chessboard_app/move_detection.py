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


def _changed_squares(left: Mapping[str, bool], right: Mapping[str, bool]) -> set[str]:
    return {
        square
        for square in chess.SQUARE_NAMES
        if bool(left.get(square, False)) != bool(right.get(square, False))
    }


def _move_squares(move: chess.Move, board: chess.Board, expected_before: Mapping[str, bool], expected_after: Mapping[str, bool]) -> set[str]:
    squares = _changed_squares(expected_before, expected_after)
    squares.add(chess.square_name(move.from_square))
    squares.add(chess.square_name(move.to_square))
    return squares


def _matches_partial_move(
    board: chess.Board,
    move: chess.Move,
    before: Mapping[str, bool],
    after: Mapping[str, bool],
    expected_before: Mapping[str, bool],
    expected_after: Mapping[str, bool],
) -> bool:
    actual_changed = _changed_squares(before, after)
    expected_changed = _changed_squares(expected_before, expected_after)
    if actual_changed != expected_changed:
        return False
    for square in _move_squares(move, board, expected_before, expected_after):
        if bool(before.get(square, False)) != bool(expected_before.get(square, False)):
            return False
        if bool(after.get(square, False)) != bool(expected_after.get(square, False)):
            return False
    return True


def detect_move(
    board: chess.Board,
    before: Mapping[str, bool],
    after: Mapping[str, bool],
    allow_unsynced: bool = False,
) -> MoveDetectionResult:
    expected_before = expected_occupancy_from_board(board)
    synced_before = _same_occupancy(before, expected_before)
    if not synced_before and not allow_unsynced:
        return MoveDetectionResult("sync_required", reason="before snapshot does not match game position")

    matching_moves = []
    promotion_bases = set()

    for move in board.legal_moves:
        candidate = board.copy()
        candidate.push(move)
        candidate_after = expected_occupancy_from_board(candidate)
        matches = (
            _same_occupancy(after, candidate_after)
            if synced_before
            else _matches_partial_move(board, move, before, after, expected_before, candidate_after)
        )
        if matches:
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
