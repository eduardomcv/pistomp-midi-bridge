# pi-stomp MIDI Bridge

A Python script meant to be used as a lightweight daemon to intercept Program
Change (PC) messages from a MIDI controller and translate them into Control
Change (CC) messages for the pi-stomp ecosystem.

It bypasses MOD UI's strict software port filters by injecting translated MIDI
bytes directly into a kernel-level raw hardware loopback.

## Prerequisites

1. Install Python Dependencies

    ```bash
    sudo apt update
    sudo apt install python3-mido python3-rtmidi
    ```

2. Enable the VirMIDI Kernel Module
    To bypass MOD UI's software port filters, you must enable the Linux
    `snd-virmidi` kernel module. Run this to load it immediately:

    ```bash
    sudo modprobe snd-virmidi midi_devs=1
    ```

    To ensure it survives a reboot, add it to your startup modules:

    ```bash
    echo "snd-virmidi" | sudo tee -a /etc/modules
    echo "options snd-virmidi midi_devs=1" | sudo tee /etc/modprobe.d/snd-virmidi.conf
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
        "0": "My_Pedalboard",
        "1": "My_Other_Pedalboard"
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
