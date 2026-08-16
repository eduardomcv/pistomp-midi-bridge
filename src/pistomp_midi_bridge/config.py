import json
import logging
import os
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Device:
    output_channel: int
    search_keywords: list[str]


@dataclass(frozen=True)
class System:
    mod_api_url: str
    mod_ws_url: str
    pedalboards_dir: str


@dataclass(frozen=True)
class Settings:
    pedalboard_cooldown_sec: float
    effect_toggle_cooldown_sec: float


@dataclass(frozen=True)
class Config:
    device: Device
    pedalboards: dict[int, str]
    effect_toggles: dict[int, int]
    system: System
    settings: Settings


def validate_config(config: Config) -> None:
    channel = config.device.output_channel

    if not 0 <= channel <= 15:
        logger.error(f"'output_channel' must be between 0 and 15, got {channel}.")
        sys.exit(1)

    for pc, cc in config.effect_toggles.items():
        if not 0 <= cc <= 127:
            logger.error(f"CC number for PC {pc} must be between 0 and 127, got {cc}.")
            sys.exit(1)

    overlap = set(config.pedalboards) & set(config.effect_toggles)

    if overlap:
        logger.error(
            f"PC numbers {sorted(overlap)} are mapped in both 'pedalboards' and 'effect_toggles'."
        )
        sys.exit(1)


def load_config(config_path: str) -> Config:
    if not os.path.exists(config_path):
        logger.error(
            f"Config file not found at {config_path}\nPlease copy config.example.json to config.json and edit it."
        )
        sys.exit(1)

    with open(config_path, "r") as f:
        try:
            raw_config = json.load(f)
        except json.JSONDecodeError:
            logger.exception("Failed to load config.json.")
            sys.exit(1)

    try:
        pedalboards: dict[int, str] = {
            int(key): val for key, val in raw_config.get("pedalboards", {}).items()
        }

        effect_toggles: dict[int, int] = {
            int(key): int(val)
            for key, val in raw_config.get("effect_toggles", {}).items()
        }
    except ValueError:
        logger.error(
            "All keys in 'pedalboards' and 'effect_toggles' must be integers (e.g., \"0\", \"1\")."
        )
        sys.exit(1)

    config = Config(
        device=Device(
            output_channel=raw_config.get("device", {}).get("output_channel", 0),
            search_keywords=raw_config.get("device", {}).get(
                "search_keywords", ["MIDI", "Controller"]
            ),
        ),
        pedalboards=pedalboards,
        effect_toggles=effect_toggles,
        system=System(
            mod_api_url=raw_config.get("system", {}).get(
                "mod_api_url", "http://localhost:80"
            ),
            pedalboards_dir=raw_config.get("system", {}).get(
                "pedalboards_dir", "/home/pistomp/data/.pedalboards"
            ),
            mod_ws_url=raw_config.get("system", {}).get(
                "mod_ws_url",
                raw_config.get("system", {})
                .get("mod_api_url", "http://localhost:80")
                .replace("http://", "ws://", 1)
                + "/websocket",
            ),
        ),
        settings=Settings(
            pedalboard_cooldown_sec=raw_config.get("settings", {}).get(
                "pedalboard_cooldown_sec", 2.5
            ),
            effect_toggle_cooldown_sec=raw_config.get("settings", {}).get(
                "effect_toggle_cooldown_sec", 0.2
            ),
        ),
    )

    validate_config(config)

    return config
