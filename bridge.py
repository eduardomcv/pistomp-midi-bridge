import logging
import time

from mido import Backend

from config import Config
from midi import decide_toggle_cc_value, find_input_port
from mod_state import ModState
from pedalboard import load_pedalboard

logger = logging.getLogger(__name__)


RECONNECT_DELAY_SEC = 3.0


def run_bridge(
    config: Config, virmidi_device: str, mido_backend: Backend, mod_state: ModState
) -> None:
    device = config.device
    pedalboards = config.pedalboards
    effect_toggles = config.effect_toggles
    settings = config.settings
    system = config.system

    # Only used when mod-ui hasn't reported this control yet (see
    # decide_toggle_cc_value); once it has, its live value always wins.
    fallback_toggle_states: dict[int, bool] = dict.fromkeys(effect_toggles, False)

    last_pedalboard_load_time: float = 0
    last_effect_toggle_time: float = 0
    current_board: str | None = None

    with open(virmidi_device, "wb", buffering=0) as midi_out:
        logger.info(f"Sending translated CC messages to {virmidi_device}")

        while True:
            input_port_name = find_input_port(mido_backend, device.search_keywords)

            if not input_port_name:
                logger.warning(
                    f"No MIDI input matching {device.search_keywords}. Retrying in {RECONNECT_DELAY_SEC:.0f}s. "
                    f"Available ports: {mido_backend.get_input_names()}"
                )
                time.sleep(RECONNECT_DELAY_SEC)
                continue

            logger.info(f"Listening to '{input_port_name}' for Program Changes...")

            try:
                with mido_backend.open_input(input_port_name) as inport:
                    for msg in inport:
                        if msg.type != "program_change":
                            continue

                        prog_num = msg.program
                        now = time.time()

                        if prog_num in pedalboards:
                            target_board = pedalboards[prog_num]
                            is_off_cooldown = (
                                now - last_pedalboard_load_time
                                > settings.pedalboard_cooldown_sec
                            )
                            is_different_board = target_board != current_board

                            if not (is_off_cooldown and is_different_board):
                                continue

                            load_pedalboard(
                                board_name=target_board,
                                mod_api_url=system.mod_api_url,
                                pedalboards_dir=system.pedalboards_dir,
                            )

                            last_pedalboard_load_time = now
                            current_board = target_board

                            fallback_toggle_states = dict.fromkeys(
                                effect_toggles, False
                            )

                        elif prog_num in effect_toggles:
                            is_off_cooldown = (
                                now - last_effect_toggle_time
                                > settings.effect_toggle_cooldown_sec
                            )

                            if not is_off_cooldown:
                                continue

                            cc_num = effect_toggles[prog_num]
                            binding = mod_state.lookup(device.output_channel, cc_num)
                            cc_val = decide_toggle_cc_value(
                                binding, fallback_is_on=fallback_toggle_states[prog_num]
                            )
                            fallback_toggle_states[prog_num] = cc_val == 127
                            status_byte = 0xB0 + device.output_channel

                            midi_out.write(bytes([status_byte, cc_num, cc_val]))

                            if binding is not None:
                                logger.info(
                                    f"Received PC {prog_num} -> Sent CC {cc_num} = {cc_val} "
                                    f"({binding.instance}:{binding.symbol} was {binding.value})"
                                )
                            else:
                                logger.info(
                                    f"Received PC {prog_num} -> Sent CC {cc_num} = {cc_val} "
                                    "(no live binding yet, blind toggle)"
                                )

                            last_effect_toggle_time = now
            except OSError:
                logger.exception(f"Lost '{input_port_name}'")

            logger.warning(
                f"Input closed. Reconnecting in {RECONNECT_DELAY_SEC:.0f}s..."
            )
            time.sleep(RECONNECT_DELAY_SEC)
