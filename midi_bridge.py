#!/usr/bin/env python3

import argparse
import glob
import json
import logging
import os
import re
import signal
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

CARDS_FILE = "/proc/asound/cards"
CARD_LINE = re.compile(r"^\s*(\d+)\s+\[(\w+)\s*\]")
RECONNECT_DELAY_SEC = 3.0


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

    channel = config.get("device", {}).get("output_channel", 0)

    if not 0 <= channel <= 15:
        logger.error(f"'output_channel' must be between 0 and 15, got {channel}.")
        sys.exit(1)

    for pc, cc in config["effect_toggles"].items():
        if not 0 <= cc <= 127:
            logger.error(f"CC number for PC {pc} must be between 0 and 127, got {cc}.")
            sys.exit(1)

    overlap = set(config["pedalboards"]) & set(config["effect_toggles"])

    if overlap:
        logger.error(
            f"PC numbers {sorted(overlap)} are mapped in both 'pedalboards' and 'effect_toggles'."
        )
        sys.exit(1)

    return config


def find_virmidi_device() -> str | None:
    """Locate the VirMIDI raw MIDI device node, whatever ALSA card index it landed on.

    MOD UI only lists MIDI ports that JACK reports as hardware, so a software
    port (such as the ones mido/rtmidi create) can never be selected in its
    MIDI device list. snd-virmidi is a real kernel sound card, so writing raw
    bytes to its rawmidi node makes them arrive as hardware MIDI.
    """
    try:
        with open(CARDS_FILE, "r") as f:
            cards = f.read()
    except OSError:
        logger.exception(f"Could not read {CARDS_FILE}.")
        return None

    for line in cards.splitlines():
        match = CARD_LINE.match(line)

        if not match or match.group(2) != "VirMIDI":
            continue

        index = match.group(1)
        devices = sorted(glob.glob(f"/dev/snd/midiC{index}D*"))

        if devices:
            return devices[0]

        logger.error(f"VirMIDI is card {index} but it has no /dev/snd/midiC{index}D* node.")

    return None


def find_input_port(backend: mido.Backend, keywords: list[str]) -> str | None:
    for name in backend.get_input_names():
        if any(keyword in name for keyword in keywords):
            return name

    return None


def load_pedalboard(board_name: str, system_config: dict[str, str]) -> None:
    logger.info(f"Resetting engine and loading: {board_name}")

    api_url = system_config.get("mod_api_url", "http://localhost:80")
    boards_dir = system_config.get("pedalboards_dir", "/home/pistomp/data/.pedalboards/")

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
    pedalboards: dict[int, str] = config["pedalboards"]
    effect_toggles: dict[int, int] = config["effect_toggles"]
    system: dict[str, Any] = config.get("system", {})
    settings: dict[str, Any] = config.get("settings", {})

    out_channel: int = device.get("output_channel", 0)
    keywords: list[str] = device.get("search_keywords", ["MIDI", "Controller"])

    board_cooldown: float = settings.get("pedalboard_cooldown_sec", 2.5)
    effect_toggle_cooldown: float = settings.get("effect_toggle_cooldown_sec", 0.2)

    last_pedalboard_load_time: float = 0
    last_effect_toggle_time: float = 0
    current_board: str | None = None
    toggle_states: dict[int, bool] = dict.fromkeys(effect_toggles, False)

    # systemd stops the service with SIGTERM. Turning it into SystemExit lets the
    # context managers below release the MIDI ports before the process goes away.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    virmidi_device = find_virmidi_device()

    if not virmidi_device:
        logger.error(
            "VirMIDI device not found. Run 'sudo modprobe snd-virmidi index=3 midi_devs=1'"
        )
        sys.exit(1)

    backend = mido.Backend("mido.backends.rtmidi")

    with open(virmidi_device, "wb", buffering=0) as midi_out:
        logger.info(f"Sending translated CC messages to {virmidi_device}")

        while True:
            input_port_name = find_input_port(backend, keywords)

            if not input_port_name:
                logger.warning(
                    f"No MIDI input matching {keywords}. Retrying in {RECONNECT_DELAY_SEC:.0f}s. "
                    f"Available ports: {backend.get_input_names()}"
                )
                time.sleep(RECONNECT_DELAY_SEC)
                continue

            logger.info(f"Listening to '{input_port_name}' for Program Changes...")

            try:
                with backend.open_input(input_port_name) as inport:
                    for msg in inport:
                        if msg.type != "program_change":
                            continue

                        prog_num = msg.program
                        now = time.time()

                        if prog_num in pedalboards:
                            target_board = pedalboards[prog_num]
                            is_off_cooldown = (
                                now - last_pedalboard_load_time > board_cooldown
                            )
                            is_different_board = target_board != current_board

                            if not (is_off_cooldown and is_different_board):
                                continue

                            load_pedalboard(
                                board_name=target_board, system_config=system
                            )

                            last_pedalboard_load_time = now
                            current_board = target_board

                            # A fresh pedalboard starts with every effect at its
                            # saved state, so our tracked toggles no longer match.
                            toggle_states = dict.fromkeys(effect_toggles, False)

                        elif prog_num in effect_toggles:
                            is_off_cooldown = (
                                now - last_effect_toggle_time > effect_toggle_cooldown
                            )

                            if not is_off_cooldown:
                                continue

                            toggled = not toggle_states[prog_num]
                            toggle_states[prog_num] = toggled

                            cc_num = effect_toggles[prog_num]
                            cc_val = 127 if toggled else 0
                            status_byte = 0xB0 + out_channel

                            midi_out.write(bytes([status_byte, cc_num, cc_val]))

                            logger.info(
                                f"Received PC {prog_num} -> Sent CC {cc_num} (Value {cc_val})"
                            )

                            last_effect_toggle_time = now
            except OSError as e:
                logger.warning(f"Lost '{input_port_name}': {e}")

            # mido stops iterating when the port closes, which happens whenever the
            # controller is unplugged. Go back and wait for it to reappear.
            logger.warning(f"Input closed. Reconnecting in {RECONNECT_DELAY_SEC:.0f}s...")
            time.sleep(RECONNECT_DELAY_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
