from pistomp_midi_bridge.midi import find_input_port


def test_find_input_port_returns_first_matching_name():
    port_names = [
        "Midi Through:Midi Through Port-0 14:0",
        "SINCO MIDI 1:SINCO MIDI 1 20:0",
    ]

    assert find_input_port(port_names, ["SINCO"]) == "SINCO MIDI 1:SINCO MIDI 1 20:0"


def test_find_input_port_returns_none_when_no_keyword_matches():
    port_names = ["Midi Through:Midi Through Port-0 14:0"]

    assert find_input_port(port_names, ["SINCO"]) is None


def test_find_input_port_matches_any_of_multiple_keywords():
    port_names = ["M-Vave Chocolate:M-Vave Chocolate MIDI 1 24:0"]

    assert find_input_port(port_names, ["SINCO", "M-Vave"]) == port_names[0]
