import json

import pytest

from pistomp_midi_bridge.config import load_config

VALID_CONFIG = {
    "device": {"search_keywords": ["MIDI"], "output_channel": 0},
    "pedalboards": {"4": "My_Pedalboard"},
    "effect_toggles": {"0": 110},
    "system": {
        "mod_api_url": "http://localhost:80",
        "pedalboards_dir": "/home/pistomp/data/.pedalboards/",
    },
    "settings": {"pedalboard_cooldown_sec": 2.5, "effect_toggle_cooldown_sec": 0.2},
}


def _write_config(tmp_path, **overrides) -> str:
    config = {**VALID_CONFIG, **overrides}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return str(config_path)


def test_load_config_accepts_a_valid_config(tmp_path):
    config = load_config(_write_config(tmp_path))

    assert config.device.output_channel == 0
    assert config.pedalboards == {4: "My_Pedalboard"}
    assert config.effect_toggles == {0: 110}


def test_load_config_exits_on_out_of_range_output_channel(tmp_path):
    path = _write_config(
        tmp_path, device={"search_keywords": ["MIDI"], "output_channel": 16}
    )

    with pytest.raises(SystemExit):
        load_config(path)


def test_load_config_exits_on_out_of_range_cc(tmp_path):
    path = _write_config(tmp_path, effect_toggles={"0": 128})

    with pytest.raises(SystemExit):
        load_config(path)


def test_load_config_exits_on_pc_overlap_between_pedalboards_and_effect_toggles(
    tmp_path,
):
    path = _write_config(
        tmp_path,
        pedalboards={"0": "My_Pedalboard"},
        effect_toggles={"0": 110},
    )

    with pytest.raises(SystemExit):
        load_config(path)
