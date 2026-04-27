CHIP_ADDRESSES = {
    "U66": 0x20,
    "U67": 0x24,
    "U68": 0x22,
    "U69": 0x26,
}

PIN_COUNT_PER_CHIP = 16


def square_names():
    """Return chess squares in physical calibration order: a8 to h1."""
    return [
        f"{file_name}{rank}"
        for rank in range(8, 0, -1)
        for file_name in "abcdefgh"
    ]


def validate_sensor_map(sensor_map):
    expected_squares = set(square_names())
    actual_squares = set(sensor_map)
    if actual_squares != expected_squares:
        missing = sorted(expected_squares - actual_squares)
        extra = sorted(actual_squares - expected_squares)
        raise ValueError(f"sensor map squares are incomplete: missing={missing}, extra={extra}")

    used = set()
    for square, chip_pin in sensor_map.items():
        chip, pin = chip_pin
        if chip not in CHIP_ADDRESSES:
            raise ValueError(f"{square} uses unknown chip {chip!r}")
        if not isinstance(pin, int) or not 0 <= pin < PIN_COUNT_PER_CHIP:
            raise ValueError(f"{square} uses invalid pin {pin!r}")
        if chip_pin in used:
            raise ValueError(f"duplicate sensor chip/pin assignment: {chip_pin!r}")
        used.add(chip_pin)


# Fill this after running calibrate_sensors.py.
SENSOR_MAP = {
    square: None
    for square in square_names()
}
