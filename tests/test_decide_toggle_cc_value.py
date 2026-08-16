from midi import decide_toggle_cc_value
from mod_state import Binding

# mod-host's :bypass CC semantics (from effects.c:2366):
#   CC < 64  → bypassed=true  (effect OFF, bypass=1.0)
#   CC >= 64 → bypassed=false (effect ON,  bypass=0.0)
#
# So to toggle a :bypass binding:
#   value=1.0 (currently bypassed/OFF) → want ON  → send 127 (>= 64 → un-bypass)
#   value=0.0 (currently active/ON)    → want OFF → send 0   (<  64 → bypass)
#
# For plain params (not :bypass) the CC maps linearly min→max,
# so the midpoint rule still applies:
#   value < midpoint  → send 127 (push toward max)
#   value >= midpoint → send 0   (push toward min)


def test_bypass_currently_off_sends_127_to_turn_on():
    """Effect is bypassed (value=1.0); CC=127 un-bypasses it."""
    binding = Binding(
        instance="Noisegate", symbol=":bypass", value=1.0, minimum=0.0, maximum=1.0
    )
    assert decide_toggle_cc_value(binding, fallback_is_on=False) == 127


def test_bypass_currently_on_sends_0_to_turn_off():
    """Effect is active (value=0.0); CC=0 bypasses it."""
    binding = Binding(
        instance="Noisegate", symbol=":bypass", value=0.0, minimum=0.0, maximum=1.0
    )
    assert decide_toggle_cc_value(binding, fallback_is_on=False) == 0


def test_plain_param_below_midpoint_sends_127():
    """Plain param below midpoint; CC=127 pushes it toward max."""
    binding = Binding(
        instance="stereo", symbol="mute", value=0.0, minimum=0.0, maximum=1.0
    )
    assert decide_toggle_cc_value(binding, fallback_is_on=False) == 127


def test_plain_param_at_or_above_midpoint_sends_0():
    """Plain param at/above midpoint; CC=0 pushes it toward min."""
    binding = Binding(
        instance="stereo", symbol="mute", value=1.0, minimum=0.0, maximum=1.0
    )
    assert decide_toggle_cc_value(binding, fallback_is_on=False) == 0


def test_no_binding_falls_back_to_tracked_state_off_to_on():
    assert decide_toggle_cc_value(None, fallback_is_on=False) == 127


def test_no_binding_falls_back_to_tracked_state_on_to_off():
    assert decide_toggle_cc_value(None, fallback_is_on=True) == 0
