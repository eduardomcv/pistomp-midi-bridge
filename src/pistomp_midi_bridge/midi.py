import glob
import logging
import re

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


def find_input_port(port_names: list[str], keywords: list[str]) -> str | None:
    """Pick the first port name matching any keyword.

    Takes an already-fetched port list rather than a `Backend`, so a caller
    polling on a retry loop can reuse one `get_input_names()` call for both
    the match and any "available ports" log line, instead of scanning ALSA
    twice per iteration.
    """
    for name in port_names:
        if any(keyword in name for keyword in keywords):
            return name

    return None


class ToggleEchoTracker:
    """Warns when a sent CC likely has no live MIDI mapping anymore.

    mod-ui's `/websocket` feed never broadcasts `midi_unmap` (only
    `send_modified`, addressed to mod-host itself -- see mod-ui's
    `host.py::address()`), so `ModState` has no way to notice a mapping was
    removed via MIDI Learn's "unlearn" while we stayed connected (loading a
    different pedalboard or reconnecting is covered separately, since a
    fresh dump only contains currently-valid mappings).

    If a mapping is gone, every CC we send has no effect and the control's
    live value never moves between presses -- that pattern is the only
    signal available, so this reports it rather than attempting to recover
    (there is nothing to recover: no CC value does anything once mod-host
    has no mapping for it). Warns once per CC on the first missed press,
    then stays quiet until that CC's value starts moving again, so a
    genuinely dead switch doesn't spam the log on every subsequent press.
    """

    def __init__(self) -> None:
        self._last_value: dict[int, float] = {}
        self._warned: set[int] = set()

    def observe_press(self, cc_num: int, value_before_send: float) -> bool:
        """Record this press; return True the first time a CC's value is
        found unchanged since its previous press (a likely missed echo)."""
        previous = self._last_value.get(cc_num)
        self._last_value[cc_num] = value_before_send

        if previous is None or value_before_send != previous:
            self._warned.discard(cc_num)
            return False

        if cc_num in self._warned:
            return False

        self._warned.add(cc_num)
        return True

    def reset(self) -> None:
        """Call on pedalboard load: values from the old board say nothing
        about whether the new board's mappings are working."""
        self._last_value.clear()
        self._warned.clear()


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
