#!/usr/bin/env python3

import argparse
import logging
import signal
import sys

from bridge import run_bridge
from config import load_config
from midi import find_virmidi_device
from mod_state import ModState, ModStateClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

try:
    import mido
except ImportError:
    logger.error(
        "Missing 'mido' library. Please run: sudo apt install python3-mido python3-rtmidi"
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="MIDI PC/CC Bridge for pi-stomp")
    parser.add_argument(
        "-c", "--config", default="config.json", help="Path to config.json file"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    system = config.system

    mod_state = ModState()

    mod_state_client = ModStateClient(system.mod_ws_url, mod_state)
    mod_state_client.start()

    # Turn systemd's SIGTERM into SystemExit so the MIDI ports get released.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    virmidi_device = find_virmidi_device()

    if not virmidi_device:
        logger.error(
            "VirMIDI device not found. Run 'sudo modprobe snd-virmidi index=3 midi_devs=1'"
        )
        sys.exit(1)

    mido_backend = mido.Backend("mido.backends.rtmidi")

    run_bridge(
        config=config,
        virmidi_device=virmidi_device,
        mido_backend=mido_backend,
        mod_state=mod_state,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
