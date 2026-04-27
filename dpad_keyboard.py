import argparse
import time

from chessboard_app.dpad import QWIIC_DPAD, decode_buttons, key_for_button


def open_bus(bus_number):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus  # type: ignore
    return SMBus(bus_number)


def create_keyboard():
    from evdev import UInput, ecodes

    capabilities = {
        ecodes.EV_KEY: [
            ecodes.KEY_UP,
            ecodes.KEY_DOWN,
            ecodes.KEY_LEFT,
            ecodes.KEY_RIGHT,
            ecodes.KEY_ENTER,
        ]
    }
    return UInput(capabilities, name="chessboard-dpad")


def read_registers(bus, mapping):
    registers = {}
    address = mapping["address"]
    for info in mapping["buttons"].values():
        register = info["register"]
        if register not in registers:
            registers[register] = bus.read_byte_data(address, register)
    return registers


def emit_key(ui, key_name):
    from evdev import ecodes

    code = getattr(ecodes, key_name)
    ui.write(ecodes.EV_KEY, code, 1)
    ui.syn()
    ui.write(ecodes.EV_KEY, code, 0)
    ui.syn()


def main():
    parser = argparse.ArgumentParser(description="Turn the calibrated d-pad into keyboard navigation.")
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--poll-delay", type=float, default=0.05)
    parser.add_argument("--repeat-delay", type=float, default=0.25)
    args = parser.parse_args()

    last_pressed = set()
    last_emit = {}

    with open_bus(args.bus) as bus, create_keyboard() as ui:
        print("D-pad keyboard bridge running.")
        while True:
            registers = read_registers(bus, QWIIC_DPAD)
            pressed = decode_buttons(registers)
            now = time.monotonic()
            for button in sorted(pressed):
                elapsed = now - last_emit.get(button, 0)
                if button not in last_pressed or elapsed >= args.repeat_delay:
                    emit_key(ui, key_for_button(button))
                    last_emit[button] = now
            last_pressed = pressed
            time.sleep(args.poll_delay)


if __name__ == "__main__":
    main()
