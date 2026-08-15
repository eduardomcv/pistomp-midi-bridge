#!/usr/bin/env python3

import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

try:
    import mido
except ImportError:
    logger.error(
        "Missing 'mido' library. Please run: sudo apt install python3-mido python3-rtmidi"
    )
    sys.exit(1)


def load_config(config_path: str) -> dict[str, Any]:
    if not os.path.exists(config_path):
        logger.error(
            f"Config file not found at {config_path}\nPlease copy config.example.json to config.json and edit it."
        )
        sys.exit(1)

    with open(config_path, "r") as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError:
            logger.exception("Failed to load config.json.")
            sys.exit(1)

    try:
        config["pedalboards"] = {
            int(key): val for key, val in config.get("pedalboards", {}).items()
        }
        config["effect_toggles"] = {
            int(key): int(val) for key, val in config.get("effect_toggles", {}).items()
        }
    except ValueError:
        logger.error(
            "All keys in 'pedalboards' and 'effect_toggles' must be integers (e.g., \"0\", \"1\")."
        )
        sys.exit(1)

    return config


def load_pedalboard(board_name: str, system_config: dict[str, str]) -> None:
    logger.info(f"Resetting engine and loading: {board_name}")

    api_url = system_config.get("mod_api_url", "http://localhost:80")
    boards_dir = system_config.get(
        "pedalboards_dir", "/home/pistomp/data/.pedalboards/"
    )

    try:
        urllib.request.urlopen(f"{api_url}/reset", timeout=2)
        time.sleep(0.5)
    except (URLError, TimeoutError, HTTPError):
        logger.warning("Could not reset engine. Attempting to load pedalboard...")

    url = f"{api_url}/pedalboard/load_bundle/"
    bundle_path = os.path.join(boards_dir, f"{board_name}.pedalboard")
    data = urllib.parse.urlencode({"bundlepath": bundle_path}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                logger.info(f"Successfully loaded {board_name}")
    except HTTPError as e:
        logger.error(
            f"Failed to load {board_name}. The server returned: {e.code} - {e.reason}"
        )
    except TimeoutError:
        logger.error(f"Failed to load {board_name}. The request timed out.")
    except URLError as e:
        logger.error(f"Failed to reach pi-stomp API. Reason: {e.reason}")


def main():
    parser = argparse.ArgumentParser(description="MIDI PC/CC Bridge for pi-stomp")
    parser.add_argument(
        "-c", "--config", default="config.json", help="Path to config.json file"
    )

    args = parser.parse_args()
    config = load_config(args.config)

    device: dict[str, Any] = config.get("device", {})
    pedalboards: dict[int, str] = config.get("pedalboards", {})
    effect_toggles: dict[int, int] = config.get("effect_toggles", {})
    system: dict[str, Any] = config.get("system", {})
    settings: dict[str, Any] = config.get("settings", {})

    board_cooldown: float = settings.get("pedalboard_cooldown_sec", 2.5)
    effect_toggle_cooldown: float = settings.get("effect_toggle_cooldown_sec", 0.2)

    last_pedalboard_load_time: float = 0
    last_effect_toggle_time: float = 0
    current_board: str | None = None
    toggle_states: dict[int, bool] = {pc: False for pc in effect_toggles}

    rtmidi_backend = mido.Backend("mido.backends.rtmidi")

    virtual_port_name: str = device.get("virtual_port_name", "MIDI-Translator")
    midi_out = rtmidi_backend.open_output(virtual_port_name, virtual=True)

    input_port_name: str | None = None
    keywords: list[str] = device.get("search_keywords", ["MIDI", "Controller"])

    input_names: list[str] = rtmidi_backend.get_input_names()

    for name in input_names:
        if any(keyword in name for keyword in keywords):
            input_port_name = name
            break

    if not input_port_name:
        logger.error(
            f"Could not find MIDI port matching keywords: {keywords}\nAvailable ports: {input_names}"
        )
        sys.exit(1)

    logger.info(f"Listening to '{input_port_name}' for Program Changes...")

    try:
        with rtmidi_backend.open_input(input_port_name) as inport:
            for msg in inport:
                if msg.type != "program_change":
                    continue

                prog_num = msg.program
                now = time.time()

                if prog_num in pedalboards:
                    target_board: str = pedalboards[prog_num]
                    is_off_cooldown: bool = (
                        now - last_pedalboard_load_time > board_cooldown
                    )
                    is_different_board: bool = target_board != current_board

                    if is_off_cooldown and is_different_board:
                        load_pedalboard(board_name=target_board, system_config=system)
                        last_pedalboard_load_time = now
                        current_board = target_board

                elif prog_num in effect_toggles:
                    is_off_cooldown: bool = (
                        now - last_effect_toggle_time > effect_toggle_cooldown
                    )

                    if not is_off_cooldown:
                        continue

                    toggled = not toggle_states[prog_num]
                    toggle_states[prog_num] = toggled

                    cc_num = effect_toggles[prog_num]
                    cc_val = 127 if toggled else 0

                    out_msg = mido.Message(
                        "control_change",
                        channel=0,
                        control=cc_num,
                        value=cc_val,
                    )

                    midi_out.send(out_msg)

                    logger.info(
                        f"Translated PC {prog_num} -> Sent CC {cc_num} (Value {cc_val})"
                    )

                    last_effect_toggle_time = now

    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()
