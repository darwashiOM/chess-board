import chess


# Fill this with the physical LED indices from the calibration pass.
# Rows are rank 8 down to rank 1; columns are file a through file h plus the
# right-side border corner.
#
# Example shape only:
# LED_GRID = [
#     [ 0,  1,  2,  3,  4,  5,  6,  7,  8],
#     [17, 16, 15, 14, 13, 12, 11, 10,  9],
#     ...
# ]
LED_GRID = [
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None, None],
]


def build_square_to_led(led_grid):
    """
    Return {'a1': [bottom-left, bottom-right, top-right, top-left], ...}.

    led_grid is a 9x9 grid of physical LED indices, written from the board's
    top-left corner to bottom-right corner.
    """
    if len(led_grid) != 9 or any(len(row) != 9 for row in led_grid):
        raise ValueError("led_grid must be 9 rows by 9 columns")

    square_to_led = {}
    for rank in range(1, 9):
        top_row = 8 - rank
        bottom_row = top_row + 1
        for file_index, file_name in enumerate("abcdefgh"):
            square = f"{file_name}{rank}"
            square_to_led[square] = [
                led_grid[bottom_row][file_index],
                led_grid[bottom_row][file_index + 1],
                led_grid[top_row][file_index + 1],
                led_grid[top_row][file_index],
            ]
    return square_to_led


SQUARE_TO_LED = build_square_to_led(LED_GRID)
ALL_SQUARES = [chess.square_name(index) for index in chess.SQUARES]
SQ_TO_IDX = {square: chess.parse_square(square) for square in ALL_SQUARES}
