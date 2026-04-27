import argparse
import os
import sys


def import_circuitpython_board():
    """Avoid importing local files when we need CircuitPython's board module."""
    here = os.path.abspath(os.path.dirname(__file__))
    cwd = os.path.abspath(os.getcwd())
    sys.path = [
        path
        for path in sys.path
        if os.path.abspath(path or cwd) != here
    ]
    import board  # type: ignore

    return board


def parse_color(value):
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("color must be R,G,B")
    try:
        color = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("color values must be integers") from exc
    if any(part < 0 or part > 255 for part in color):
        raise argparse.ArgumentTypeError("color values must be between 0 and 255")
    return color


def main():
    parser = argparse.ArgumentParser(description="Turn on all DotStar LEDs.")
    parser.add_argument("--count", type=int, default=81)
    parser.add_argument("--brightness", type=float, default=0.1)
    parser.add_argument("--color", type=parse_color, default=(255, 255, 255))
    args = parser.parse_args()

    circuit_board = import_circuitpython_board()
    import adafruit_dotstar as dotstar  # type: ignore

    pixels = dotstar.DotStar(
        circuit_board.SCK,
        circuit_board.MOSI,
        args.count,
        brightness=args.brightness,
        auto_write=False,
    )
    pixels.fill(args.color)
    pixels.show()

    print(f"Turned on {args.count} LEDs at brightness {args.brightness}.")
    print("Press Enter to turn them off.")
    input()

    pixels.fill((0, 0, 0))
    pixels.show()


if __name__ == "__main__":
    main()
