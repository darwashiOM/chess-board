from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedSettings:
    enabled: bool = False
    brightness: float = 0.1


class DisabledLedController:
    def __init__(self):
        self.settings = LedSettings()
        self.test_pattern = "idle"

    def apply_settings(self, settings: LedSettings) -> None:
        self.settings = settings

    def run_test(self, pattern: str) -> None:
        if pattern not in {"all", "border", "square", "idle"}:
            raise ValueError("unknown LED test pattern")
        self.test_pattern = pattern

    def status(self) -> dict[str, object]:
        return {
            "available": False,
            "enabled": self.settings.enabled,
            "brightness": self.settings.brightness,
            "mode": "disabled",
            "testPattern": self.test_pattern,
        }
