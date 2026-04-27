import argparse
import os
import sys
import time

from sensor_mapping import CHIP_ADDRESSES, PIN_COUNT_PER_CHIP, square_names


def import_circuitpython_board():
    """Avoid importing this repo's board.py when we need CircuitPython's board module."""
    here = os.path.abspath(os.path.dirname(__file__))
    cwd = os.path.abspath(os.getcwd())
    sys.path = [
        path
        for path in sys.path
        if os.path.abspath(path or cwd) != here
    ]
    import board  # type: ignore

    return board


def setup_pins():
    circuit_board = import_circuitpython_board()
    import busio  # type: ignore
    import digitalio  # type: ignore
    from adafruit_mcp230xx.mcp23017 import MCP23017  # type: ignore

    i2c = busio.I2C(circuit_board.SCL, circuit_board.SDA)
    pins = {}
    for chip, address in CHIP_ADDRESSES.items():
        mcp = MCP23017(i2c, address=address)
        for pin_num in range(PIN_COUNT_PER_CHIP):
            pin = mcp.get_pin(pin_num)
            pin.direction = digitalio.Direction.INPUT
            pin.pull = digitalio.Pull.UP
            pins[(chip, pin_num)] = pin
    return pins


def read_active_sensors(pins):
    return {
        chip_pin
        for chip_pin, pin in pins.items()
        if pin.value is False
    }


def print_python_map(assignments):
    print()
    print("Paste this into sensor_mapping.py as SENSOR_MAP:")
    print("SENSOR_MAP = {")
    for square in square_names():
        chip, pin = assignments[square]
        print(f'    "{square}": ("{chip}", {pin}),')
    print("}")


def wait_for_single_change(pins, baseline, poll_delay):
    while True:
        time.sleep(poll_delay)
        active = read_active_sensors(pins)
        added = sorted(active - baseline)
        removed = sorted(baseline - active)
        changed = added + removed
        if len(changed) == 1:
            return changed[0], active
        if len(changed) > 1:
            print(f"Multiple sensors changed: {changed}. Return to baseline and try again.")
            while read_active_sensors(pins) != baseline:
                time.sleep(poll_delay)


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate 64 active-low MCP23017 chessboard sensors."
    )
    parser.add_argument(
        "--poll-delay",
        type=float,
        default=0.05,
        help="Seconds between sensor reads.",
    )
    args = parser.parse_args()

    pins = setup_pins()
    assignments = {}

    print("MCP23017 sensor calibration")
    print("Remove loose magnets/pieces before starting so the baseline is stable.")
    print("For each prompted square, place or lift one magnet on that square.")
    print("The script records the one chip/pin whose state changes.")
    input("Press Enter when the board is at baseline.")

    baseline = read_active_sensors(pins)
    print(f"Baseline active sensors: {sorted(baseline)}")

    try:
        for square in square_names():
            print()
            print(f"{square}: change exactly this square now, then wait...")
            chip_pin, active = wait_for_single_change(pins, baseline, args.poll_delay)
            assignments[square] = chip_pin
            print(f"{square} -> {chip_pin[0]} pin {chip_pin[1]}")

            baseline = active
            input("Press Enter after you are ready for the next square.")

        print_python_map(assignments)
    except KeyboardInterrupt:
        print()
        print("Stopped early.")
        if assignments:
            print_python_map(assignments)


if __name__ == "__main__":
    main()
