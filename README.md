# pi-stomp MIDI Bridge

A Python script meant to be used as a lightweight daemon to intercept Program
Change (PC) messages from a MIDI controller and translate them into Control
Change (CC) messages for the pi-stomp ecosystem.

It can also switch pedalboards from the same controller. Translated CC messages
are written to a `snd-virmidi` raw MIDI device, so MOD UI sees them arriving
from a hardware port and MIDI Learn works on any plugin parameter.

Effect toggles read the actual current state from mod-ui's `/websocket` feed
before deciding which way to flip, instead of guessing from the last press
this bridge saw. That keeps your switches correct even right after startup,
after loading a different pedalboard, or after toggling the same effect from
the pi-stomp's own footswitches or the web UI — cases where a purely local
on/off guess would otherwise desync from the pedal's actual state. Credit to
[pi-stomp](https://github.com/TreeFallSound/pi-stomp)'s own `modalapi` for
confirming this is how the pi-stomp's onboard switches solve the same
problem; no code from it is used here (pi-stomp is AGPL-3.0, this project is
MIT), just the same publicly-documented `/websocket` protocol.

## Prerequisites

1. Install Python Dependencies

    ```bash
    sudo apt update
    sudo apt install python3-mido python3-rtmidi python3-websockets
    ```

2. Enable the VirMIDI Kernel Module

    MOD UI only lists MIDI ports that JACK reports as *hardware*, so a software
    port (the kind `mido`/`rtmidi` can create) will never show up in its MIDI
    device list, no matter what it is named. The `snd-virmidi` kernel module
    provides a real sound card whose raw MIDI node this script writes to, which
    MOD UI happily accepts.

    > **Important:** always pin VirMIDI to a high card index. Without `index=`,
    > it is loaded early at boot and takes ALSA card 0, which is the card
    > `/etc/jackdrc` starts JACK on (`-d hw:0`). JACK then fails to start,
    > taking `mod-host` and `mod-ui` down with it, and the pi-stomp screen
    > stays white.

    Load it immediately:

    ```bash
    sudo modprobe snd-virmidi index=3 midi_devs=1
    ```

    To make it survive a reboot:

    ```bash
    echo "snd-virmidi" | sudo tee -a /etc/modules
    echo "options snd-virmidi index=3 midi_devs=1" | sudo tee /etc/modprobe.d/snd-virmidi.conf
    ```

    Verify that your audio card is still card 0 afterwards:

    ```bash
    cat /proc/asound/cards
    ```

    Optionally, make JACK immune to card reordering altogether by referring to
    the card by name instead of index in `/etc/jackdrc` (substitute your own
    card id from the output above):

    ```
    -d alsa -d hw:IQaudIOCODEC
    ```


## Installation

1. Clone the repository:

    ```sh
    git clone https://github.com/eduardomcv/pistomp-midi-bridge.git
    cd pistomp-midi-bridge
    ```

2. Create your configuration file:

    ```sh
      cp config.example.json config.json
    ```


3. Create your service file:

    ```sh
    cp midi-bridge.example.service midi-bridge.service
    ```

## Configuration (`config.json`)

Edit `config.json` and adjust to your needs:

* **`device.search_keywords`**: Set `search_keywords` to match your controller
    (e.g. `["SINCO"]`).
* **`device.output_channel`**: The MIDI channel (0-15) the translated CC messages
    will be sent on.
* **`pedalboards`**: Map PC numbers to the exact names of your pedalboards.
* **`effect_toggles`**: Map PC numbers to the CC numbers you want to output.
* **`system.mod_ws_url`** (optional): mod-ui's WebSocket endpoint, used to read
    live plugin state. Defaults to `mod_api_url` with `http://` swapped for
    `ws://` and `/websocket` appended, which is correct unless you've changed
    mod-ui's default port.

A given PC number may appear in `pedalboards` or in `effect_toggles`, but not in
both; the script refuses to start otherwise. Controllers that send a different
PC range per bank make this easy to arrange — on an M-Vave Chocolate, for
instance, bank 1 sends PC 0-3 and bank 2 sends PC 4-7, so one bank can drive
effect toggles while the other switches pedalboards.

> **Note on MIDI channel numbering:** `device.output_channel` here is the
> literal wire channel (0-15) sent in the raw MIDI status byte, and mod-ui's
> `midi_map` messages report that same wire channel directly (confirmed
> against a live `/websocket` capture in
> `tests/fixtures/mod_ui_connect_dump.txt`). pi-stomp's own
> `hardware.midi.channel` in `default_config.yml` is *not* a plain wire
> channel: pi-stomp's `get_real_midi_channel()` (`pistomp/hardware.py`)
> subtracts 1 from any non-zero value before using it — a workaround for
> what pi-stomp's own source calls a "LAME bug in Mod" — so its
> commonly-seen `channel: 14` actually produces wire channel 13. Setting
> both to `14` does *not* put them on the same wire channel — that's a
> coincidence of the example values, not a collision to avoid. Check
> `aseqdump` if you're unsure which wire channel a given config value
> actually produces.

### Example `config.json`

```json
{
    "device": {
        "search_keywords": [
            "MIDI"
        ],
        "output_channel": 14
    },
    "pedalboards": {
        "4": "My_Pedalboard",
        "5": "My_Other_Pedalboard"
    },
    "effect_toggles": {
        "0": 110,
        "1": 111,
        "2": 112,
        "3": 113
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

## Usage

Test the script manually (mirrors what the systemd service runs):

```bash
PYTHONPATH=src python3 -m pistomp_midi_bridge.main
```

### MOD UI Setup

1. Open the MOD UI web interface.
2. Click **MIDI Ports** at the bottom.
3. Ensure **Separated mode** and **Enable Virtual MIDI Loopback** are checked.
4. Check the box next to **Virtual Raw MIDI** and click **Save**.
5. Use **MIDI Learn** on any plugin parameter to map your controller.

### Running as a Service

To run this automatically in the background as a systemd service, there is an
example `midi-bridge.service` file included. The easiest way to set it up is to
link it to the systemd directory and enable it:

1. Link the service file to the systemd directory:

    ```bash
    sudo ln -s /path/to/repository/midi-bridge.service /etc/systemd/system/
    
    ```

2. Reload the systemd daemon:

    ```bash
    sudo systemctl daemon-reload
    ```

3. Enable and start the service:

    ```bash
    sudo systemctl enable --now midi-bridge.service
    ```

## Troubleshooting

### The pi-stomp screen is white and MOD UI is unreachable

Almost always an ALSA card ordering problem, not the bridge itself. Check:

```bash
cat /proc/asound/cards
systemctl status jack.service --no-pager
```

If VirMIDI is card 0, JACK cannot open the audio card and everything downstream
of it fails. Fix the index as described in the prerequisites and reboot:

```bash
echo "options snd-virmidi index=3 midi_devs=1" | sudo tee /etc/modprobe.d/snd-virmidi.conf
sudo systemctl reset-failed jack.service mod-ui.service
sudo reboot
```

### The bridge logs translated CC messages but nothing happens in MOD UI

Confirm that **Virtual Raw MIDI** is checked in MOD UI's MIDI Ports dialog, then
verify the messages actually reach the sequencer:

```bash
aseqdump -l                 # find the VirMIDI client number
aseqdump -p <client>:0      # stomp a switch, control changes should appear
```

### Log lines say "no live binding yet, blind toggle"

The bridge couldn't connect to mod-ui's WebSocket, or the current pedalboard
has no MIDI mapping on that channel/CC. Check:

```bash
journalctl -u midi-bridge.service | grep "WebSocket connection failed"
```

If mod-ui is reachable at `system.mod_api_url` but the WebSocket URL differs
(e.g. non-default port), set `system.mod_ws_url` explicitly in `config.json`.

## Development

Install dependencies (pinned to match the apt packages used on the pi-stomp
itself, so tests run against the same versions the device runs):

```bash
uv sync --group dev
```

Run the test suite:

```bash
uv run pytest
```

`tests/fixtures/mod_ui_connect_dump.txt` is a real capture of mod-ui's
`/websocket` feed from a running pi-stomp, used to test the WebSocket message
parser (`mod_state.py`) against actual wire data rather than guessed formats.
