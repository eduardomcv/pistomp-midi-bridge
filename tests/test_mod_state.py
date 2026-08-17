from pistomp_midi_bridge.mod_state import (
    AddPluginMessage,
    LoadingEndMessage,
    LoadingStartMessage,
    MidiMapMessage,
    ModState,
    ParamSetMessage,
    RemoveMessage,
    UnknownMessage,
    parse_message,
)


def test_parse_midi_map():
    msg = parse_message("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    assert msg == MidiMapMessage(
        instance="Noisegate",
        symbol=":bypass",
        channel=14,
        controller=110,
        minimum=0.0,
        maximum=1.0,
    )


def test_parse_param_set():
    msg = parse_message("param_set /graph/stereo mute 0.000000")
    assert msg == ParamSetMessage(instance="stereo", symbol="mute", value=0.0)


def test_parse_add_bypassed():
    msg = parse_message(
        "add /graph/MultiChorus http://calf.sourceforge.net/plugins/MultiChorus 536.0 906.0 1 0_0_0_0 0"
    )
    assert msg == AddPluginMessage(instance="MultiChorus", bypassed=True)


def test_parse_add_not_bypassed():
    msg = parse_message(
        "add /graph/plate urn:dragonfly:plate 2026.0 1086.0 0 0_6_4_0 0"
    )
    assert msg == AddPluginMessage(instance="plate", bypassed=False)


def test_parse_remove_instance():
    msg = parse_message("remove /graph/Noisegate")
    assert msg == RemoveMessage(instance="Noisegate")


def test_parse_remove_all():
    msg = parse_message("remove :all")
    assert msg == RemoveMessage(instance=None)


def test_parse_loading_start():
    assert parse_message("loading_start 0 1") == LoadingStartMessage()


def test_parse_loading_end():
    assert parse_message("loading_end 0") == LoadingEndMessage()


def test_parse_unknown_message_is_ignored():
    msg = parse_message("stats 19.9 0")
    assert msg == UnknownMessage(raw="stats 19.9 0")


def test_feed_skips_parsing_for_unhandled_commands(monkeypatch):
    """`output_set` and `data_ready` alone measured at ~99% of a live
    pi-stomp's `/websocket` traffic, and ModState has never handled either
    -- parse_message() always returns UnknownMessage for them, which feed()
    then does nothing with. Skip parsing entirely for any command we don't
    handle, rather than building a message object and running it through
    six isinstance checks for every one of them."""
    import pistomp_midi_bridge.mod_state as mod_state_module

    original_parse_message = mod_state_module.parse_message
    calls: list[str] = []
    monkeypatch.setattr(
        mod_state_module,
        "parse_message",
        lambda raw: (calls.append(raw), original_parse_message(raw))[1],
    )

    state = ModState()
    state.feed("output_set /graph/stereo level 0.019844")
    state.feed("data_ready 481646")
    state.feed("stats 19.9 0")

    assert calls == []


def test_feed_still_parses_handled_commands(monkeypatch):
    import pistomp_midi_bridge.mod_state as mod_state_module

    original_parse_message = mod_state_module.parse_message
    calls: list[str] = []
    monkeypatch.setattr(
        mod_state_module,
        "parse_message",
        lambda raw: (calls.append(raw), original_parse_message(raw))[1],
    )

    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")

    assert calls == ["midi_map /graph/Noisegate :bypass 14 110 0.0 1.0"]
    assert state.lookup(channel=14, controller=110) is not None


def test_lookup_returns_none_for_unmapped_control():
    state = ModState()
    assert state.lookup(channel=14, controller=110) is None


def test_lookup_returns_current_value_after_midi_map_and_param_set():
    state = ModState()
    state.feed("midi_map /graph/stereo mute 14 113 0.0 1.0")
    state.feed("param_set /graph/stereo mute 1.000000")

    binding = state.lookup(channel=14, controller=113)

    assert binding is not None
    assert binding.instance == "stereo"
    assert binding.symbol == "mute"
    assert binding.value == 1.0
    assert binding.minimum == 0.0
    assert binding.maximum == 1.0


def test_bypass_value_is_seeded_from_add_message():
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed(
        "add /graph/Noisegate http://moddevices.com/plugins/caps/Noisegate 384.3 142.2 0 0_24_9_0 0"
    )

    binding = state.lookup(channel=14, controller=110)

    assert binding is not None
    assert binding.value == 0.0


def test_live_bypass_param_set_overrides_add_seeded_value():
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed(
        "add /graph/Noisegate http://moddevices.com/plugins/caps/Noisegate 384.3 142.2 0 0_24_9_0 0"
    )
    state.feed("param_set /graph/Noisegate :bypass 1.000000")

    binding = state.lookup(channel=14, controller=110)

    assert binding is not None
    assert binding.value == 1.0


def test_remove_instance_clears_its_binding():
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("midi_map /graph/stereo mute 14 113 0.0 1.0")
    state.feed("remove /graph/Noisegate")

    assert state.lookup(channel=14, controller=110) is None
    assert state.lookup(channel=14, controller=113) is not None


def test_remove_all_clears_every_binding():
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("midi_map /graph/stereo mute 14 113 0.0 1.0")
    state.feed("remove :all")

    assert state.lookup(channel=14, controller=110) is None
    assert state.lookup(channel=14, controller=113) is None


def test_lookup_returns_none_while_loading():
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("loading_start 0 1")

    assert state.lookup(channel=14, controller=110) is None


def test_lookup_resumes_after_loading_end():
    # loading_start always precedes a complete fresh dump on real wire
    # traffic (see the fixture), so the binding is fed after it, not before.
    state = ModState()
    state.feed("loading_start 0 1")
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("loading_end 0")

    assert state.lookup(channel=14, controller=110) is not None


def test_loading_start_clears_previous_bindings():
    """A `loading_start` always precedes a complete fresh state description
    (either a reconnect's full dump, or a newly loaded pedalboard's), so
    clearing here makes ModState self-correcting against changes we never
    saw a message for -- e.g. a MIDI mapping removed while we stayed
    connected. lookup() is already gated by `_loading`, so there's no window
    where the just-cleared table is served as if it were authoritative."""
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("param_set /graph/Noisegate :bypass 1.000000")

    state.feed("loading_start 0 1")
    state.feed("loading_end 0")

    assert state.lookup(channel=14, controller=110) is None


def test_reconnect_dump_replaces_stale_bindings():
    """Simulates unlearning a mapping while connected, then a reconnect: the
    fresh dump (bracketed by loading_start/loading_end) only contains
    currently-valid mappings, so the removed one must not survive it."""
    state = ModState()
    state.feed("midi_map /graph/plate :bypass 14 112 0.0 1.0")
    state.feed("param_set /graph/plate :bypass 0.000000")

    state.feed("loading_start 0 1")
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("param_set /graph/Noisegate :bypass 1.000000")
    state.feed("loading_end 0")

    assert state.lookup(channel=14, controller=112) is None

    binding = state.lookup(channel=14, controller=110)
    assert binding is not None
    assert binding.value == 1.0


def test_mark_disconnected_gates_lookup_until_fresh_loading_end():
    """While disconnected, mod-ui may restart or change state without us
    seeing it, so a cached value can no longer be trusted as "live". Gate
    lookup() the same way an in-progress pedalboard load does, until a new
    connection's loading_end proves the cache is fresh again."""
    state = ModState()
    state.feed("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
    state.feed("param_set /graph/Noisegate :bypass 1.000000")

    state.mark_disconnected()

    assert state.lookup(channel=14, controller=110) is None

    state.feed("loading_end 0")

    assert state.lookup(channel=14, controller=110) is not None


def test_binding_midpoint():
    from pistomp_midi_bridge.mod_state import Binding

    binding = Binding(
        instance="x", symbol=":bypass", value=0.0, minimum=0.0, maximum=1.0
    )
    assert binding.midpoint == 0.5


def test_full_device_capture_produces_correct_bindings():
    state = ModState()

    with open("tests/fixtures/mod_ui_connect_dump.txt") as f:
        for line in f:
            state.feed(line.rstrip("\n"))

    # Noisegate: not bypassed at connect time (add ... 0 ...)
    noisegate = state.lookup(channel=14, controller=110)

    assert noisegate is not None
    assert noisegate.instance == "Noisegate"
    assert noisegate.value == 0.0

    # MultiChorus: bypassed at connect time (add ... 1 ...)
    multichorus = state.lookup(channel=13, controller=61)

    assert multichorus is not None
    assert multichorus.instance == "MultiChorus"
    assert multichorus.value == 1.0

    # stereo:mute is a plain param_set, not seeded from `add`.
    stereo_mute = state.lookup(channel=14, controller=113)

    assert stereo_mute is not None
    assert stereo_mute.instance == "stereo"
    assert stereo_mute.symbol == "mute"
    assert stereo_mute.value == 0.0

    # The dump ends with loading_end, so lookups must not be gated anymore.
    assert noisegate is not None
