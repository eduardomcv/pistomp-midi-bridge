# pi-stomp MIDI Bridge

A Python script meant to be used as a lightweight daemon for pi-stomp (MODEP)
that allows MIDI foot controllers to control the pi-stomp via Program Change
(PC) messages.

By default, the MOD UI restricts pedalboard switching via USB MIDI and requires
Control Change (CC) messages for effect toggles. This bridge acts as a
translator: it catches PC messages natively via ALSA, triggers pedalboard loads
via the local REST API, and translates higher PC numbers into virtual CC
messages for effect mapping in the MOD UI.

## Prerequisites

This script uses system Python libraries to natively interface with ALSA. Run
this on your pi-stomp:

```sh
sudo apt update
sudo apt install python3-mido python3-rtmidi
```

## Installation

1. Clone the repository:

    ```sh
      git clone https://github.com/eduardomcv/mvave-bridge.git cd mvave-bridge
    ```

2. Create your configuration file:

    ```sh
      cp config.example.json config.json
    ```

3. Install and start the systemd service:

    ```sh
     sudo ln -s /home/pistomp/mvave-bridge/midi-bridge.service /etc/systemd/system/
     sudo systemctl daemon-reload sudo systemctl enable --now midi-bridge.service
    ```

## Configuration (`config.json`)

Edit `config.json` to map your MIDI controller's Program Change numbers.

* **`device`**: Set `search_keywords` to match your controller (e.g.,
  `["SINCO", "M-Vave"]`).
* **`pedalboards`**: Map incoming PC numbers to the exact names of your
  pedalboard bundles.
* **`effect_toggles`**: Map incoming PC numbers to the CC numbers you want to
  output.
* **`settings`**: Debounce cooldowns to prevent double-loading if you
  accidentally double-tap a footswitch.

### Example `config.json`

```json
{
    "device": {
        "search_keywords": [
            "MIDI"
        ],
        "virtual_port_name": "MIDI-Translator"
    },
    "pedalboards": {
        "0": "My_Pedalboard",
        "1": "My_Other_Pedalboard"
    },
    "effect_toggles": {
        "10": 10,
        "11": 11,
        "12": 12,
        "13": 13
    },
    "system": {
        "mod_api_url": "http://localhost:80",
        "pedalboards_dir": "/home/pistomp/data/.pedalboards/"
    },
    "settings": {
        "pedalboard_cooldown_sec": 2.5,
        "effect_toggle_cooldown_sec": 0.2
    }
}
```

## Usage in MOD UI

Once the service is running, it will automatically create a virtual MIDI port.

To map an effect toggle, open the MOD UI, click **MIDI Learn** on the plugin
parameter, and press the corresponding footswitch on your controller (e.g., PC
10). The bridge will instantly translate it to CC 10 and map it to the plugin.

## Troubleshooting

To view live logs and see exactly what the bridge is translating, check the
systemd journal:

```sh
journalctl -u midi-bridge.service -f
```
