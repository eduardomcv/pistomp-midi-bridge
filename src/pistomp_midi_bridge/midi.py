import glob
import logging
import re

from mido import Backend

from pistomp_midi_bridge.mod_state import Binding

logger = logging.getLogger(__name__)


CARDS_FILE = "/proc/asound/cards"
CARD_LINE = re.compile(r"^\s*(\d+)\s+\[(\w+)\s*\]")


def find_virmidi_device() -> str | None:
    """Locate the VirMIDI raw MIDI node, whatever ALSA card index it landed on.

    MOD UI only lists MIDI ports that JACK reports as hardware, so writing to
    this kernel device is what makes the messages visible to MIDI Learn.
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

        logger.error(
            f"VirMIDI is card {index} but it has no /dev/snd/midiC{index}D* node."
        )

    return None


def find_input_port(backend: Backend, keywords: list[str]) -> str | None:
    for name in backend.get_input_names():
        if any(keyword in name for keyword in keywords):
            return name

    return None


def decide_toggle_cc_value(binding: Binding | None, fallback_is_on: bool) -> int:
    """Pick the CC value that flips a control to its opposite state.

    Prefers mod-ui's actual current value (`binding`) so the switch always
    matches reality, even if this bridge never saw the previous press (e.g.
    the effect was toggled from the pi-stomp's own footswitches, the web UI,
    or a pedalboard loaded with the effect already on). Falls back to a
    locally tracked guess only when mod-ui hasn't reported this control yet.

    :bypass direction (from mod-host effects.c):
        CC < 64  → bypass=1.0 (effect OFF)
        CC >= 64 → bypass=0.0 (effect ON)
    So to un-bypass (value=1.0 → want ON) send 127; to bypass (value=0.0 → want OFF) send 0.
    Plain params map linearly min→max, so the midpoint rule applies in the normal direction.
    """
    if binding is not None:
        if binding.symbol == ":bypass":
            return 127 if binding.value >= binding.midpoint else 0
        return 0 if binding.value >= binding.midpoint else 127

    return 0 if fallback_is_on else 127
