# pi-stomp MIDI Bridge

A Python script meant to be used as a lightweight daemon to intercept Program
Change (PC) messages from a MIDI controller and translate them into Control
Change (CC) messages for the pi-stomp ecosystem.

It can also switch pedalboards from the same controller. Translated CC messages
are written to a `snd-virmidi` raw MIDI device, so MOD UI sees them arriving
from a hardware port and MIDI Learn works on any plugin parameter.

## Prerequisites

1. Install Python Dependencies

    ```bash
    sudo apt update
    sudo apt install python3-mido python3-rtmidi
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
      git clone https://github.com/eduardomcv/mvave-bridge.git cd mvave-bridge
    ```

2. Create your configuration file:

    ```sh
      cp config.example.json config.json
    ```


3. Create your service file:

    ```sh
      cp midi-bridge.service.example midi-bridge.service
    ```

## Configuration (`config.json`)

Edit `config.json` and adjust to your needs:

* **`device.search_keywords`**: Set `search_keywords` to match your controller
    (e.g. `["SINCO"]`).
* **`device.output_channel`**: The MIDI channel (0-15) the translated CC messages
    will be sent on.
* **`pedalboards`**: Map PC numbers to the exact names of your pedalboards.
* **`effect_toggles`**: Map PC numbers to the CC numbers you want to output.

A given PC number may appear in `pedalboards` or in `effect_toggles`, but not in
both; the script refuses to start otherwise. Controllers that send a different
PC range per bank make this easy to arrange — on an M-Vave Chocolate, for
instance, bank 1 sends PC 0-3 and bank 2 sends PC 4-7, so one bank can drive
effect toggles while the other switches pedalboards.

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

Test the script manually:

```bash
./midi_bridge.py
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
