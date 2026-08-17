"""Tracks live plugin state from mod-ui's WebSocket feed.

mod-ui's `/websocket` endpoint broadcasts every change to the running
pedalboard as plain-text lines (see mod-ui's `mod/host.py`, the
`msg_callback(...)` call sites). This module parses the lines relevant to
MIDI-mapped controls and keeps a live `(channel, controller) -> value`
table, so callers can ask "what is this control's current value?" instead
of tracking their own copy that can drift from the pedalboard's actual
state (e.g. after loading a different pedalboard, or after a change made
from the pi-stomp's own footswitches or the web UI).

The wire format was reverse-engineered from mod-ui's source and a live
capture from a running pi-stomp (see tests/fixtures/mod_ui_connect_dump.txt).
pi-stomp's own `modalapi/ws_protocol.py` solves the same problem and was
useful prior art for confirming the protocol, but no code from it is
reused here: pi-stomp is AGPL-3.0 and this project is MIT.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass

import websockets
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MidiMapMessage:
    instance: str
    symbol: str
    channel: int
    controller: int
    minimum: float
    maximum: float


@dataclass(frozen=True)
class ParamSetMessage:
    instance: str
    symbol: str
    value: float


@dataclass(frozen=True)
class AddPluginMessage:
    instance: str
    bypassed: bool


@dataclass(frozen=True)
class RemoveMessage:
    instance: str | None  # None means "remove :all"


@dataclass(frozen=True)
class LoadingStartMessage:
    pass


@dataclass(frozen=True)
class LoadingEndMessage:
    pass


@dataclass(frozen=True)
class UnknownMessage:
    raw: str


Message = (
    MidiMapMessage
    | ParamSetMessage
    | AddPluginMessage
    | RemoveMessage
    | LoadingStartMessage
    | LoadingEndMessage
    | UnknownMessage
)


def _strip_graph_prefix(path: str) -> str:
    return path.removeprefix("/graph/")


def parse_message(raw: str) -> Message:
    cmd, _, rest = raw.partition(" ")

    if cmd == "midi_map":
        path, symbol, channel, controller, minimum, maximum = rest.split(" ")
        return MidiMapMessage(
            instance=_strip_graph_prefix(path),
            symbol=symbol,
            channel=int(channel),
            controller=int(controller),
            minimum=float(minimum),
            maximum=float(maximum),
        )

    if cmd == "param_set":
        path, symbol, value = rest.split(" ", 2)
        return ParamSetMessage(
            instance=_strip_graph_prefix(path), symbol=symbol, value=float(value)
        )

    if cmd == "add":
        fields = rest.split(" ")
        return AddPluginMessage(
            instance=_strip_graph_prefix(fields[0]), bypassed=fields[4] != "0"
        )

    if cmd == "remove":
        target = rest.strip()
        return RemoveMessage(
            instance=None if target == ":all" else _strip_graph_prefix(target)
        )

    if cmd == "loading_start":
        return LoadingStartMessage()

    if cmd == "loading_end":
        return LoadingEndMessage()

    return UnknownMessage(raw=raw)


@dataclass(frozen=True)
class Binding:
    instance: str
    symbol: str
    value: float
    minimum: float
    maximum: float

    @property
    def midpoint(self) -> float:
        return (self.minimum + self.maximum) / 2.0


class ModState:
    """Live `(channel, controller) -> Binding` table, fed by `feed()`.

    Thread-safe: `feed()` is meant to be called from the WebSocket reader
    thread/task, `lookup()` from the MIDI input thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bindings: dict[tuple[int, int], tuple[str, str, float, float]] = {}
        self._values: dict[tuple[str, str], float] = {}
        self._loading = False

    def feed(self, raw: str) -> None:
        msg = parse_message(raw)

        with self._lock:
            if isinstance(msg, MidiMapMessage):
                self._bindings[(msg.channel, msg.controller)] = (
                    msg.instance,
                    msg.symbol,
                    msg.minimum,
                    msg.maximum,
                )
            elif isinstance(msg, ParamSetMessage):
                self._values[(msg.instance, msg.symbol)] = msg.value
            elif isinstance(msg, AddPluginMessage):
                self._values[(msg.instance, ":bypass")] = 1.0 if msg.bypassed else 0.0
            elif isinstance(msg, RemoveMessage):
                self._remove(msg.instance)
            elif isinstance(msg, LoadingStartMessage):
                self._loading = True
            elif isinstance(msg, LoadingEndMessage):
                self._loading = False

    def _remove(self, instance: str | None) -> None:
        if instance is None:
            self._bindings.clear()
            self._values.clear()
            return

        self._bindings = {k: v for k, v in self._bindings.items() if v[0] != instance}
        self._values = {k: v for k, v in self._values.items() if k[0] != instance}

    def mark_disconnected(self) -> None:
        """Call when the WebSocket connection to mod-ui drops.

        Gates lookup() the same way an in-progress pedalboard load does:
        while disconnected, mod-ui's actual state may change (a different
        pedalboard loaded, mod-ui restarted) without us seeing it, so our
        cached values can no longer be trusted as live. The gate lifts once
        a new connection's fresh dump ends with a `loading_end` we actually
        saw; a mid-load reconnect that keeps `_loading` True is intentional
        too, since we didn't observe that load's `loading_start` either.
        """
        with self._lock:
            self._loading = True

    def lookup(self, channel: int, controller: int) -> Binding | None:
        with self._lock:
            if self._loading:
                return None

            entry = self._bindings.get((channel, controller))

            if entry is None:
                return None

            instance, symbol, minimum, maximum = entry
            value = self._values.get((instance, symbol), minimum)
            return Binding(
                instance=instance,
                symbol=symbol,
                value=value,
                minimum=minimum,
                maximum=maximum,
            )


class ModStateClient:
    """Keeps a `ModState` in sync with mod-ui's `/websocket` endpoint.

    `start()`/`stop()` run the connection on a daemon thread, so `feed()` never
    blocks the caller's MIDI input loop. Runs on plain asyncio (rather than
    `websockets.sync`) because the apt-packaged `python3-websockets` on the
    pi-stomp (10.4) predates the synchronous client API (added in 12.0).
    """

    def __init__(self, url: str, state: ModState, reconnect_delay: float = 3.0) -> None:
        self.url = url
        self.state = state
        self.reconnect_delay = reconnect_delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    async def run_once(self) -> None:
        """Connect once and feed messages into state until the connection closes.

        `ping_interval=None` disables websockets' own protocol-level ping,
        matching pi-stomp's own client (modalapi/websocket_bridge.py):
        mod-ui already sends its own application-level "ping" text frames
        (mod/session.py's SESSION.web_ping), which we must reply "pong" to
        below. Leaving the library's ping enabled stacks a second, redundant
        keepalive on top and risks the pi's own ping/pong exchange stalling
        under load and aborting the connection with ConnectionClosedError.
        """
        async with websockets.connect(self.url, ping_interval=None) as ws:
            async for raw in ws:
                if raw == "ping":
                    await ws.send("pong")
                    continue

                self.state.feed(raw)

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except (WebSocketException, OSError) as e:
                logger.warning(f"mod-ui WebSocket connection failed: {e}")
            finally:
                # Whether run_once() returned (server closed cleanly) or
                # raised (abnormal close/refused/etc.), the connection is
                # now down: stop serving cached values as if they were live.
                self.state.mark_disconnected()

            if not self._stop.is_set():
                await asyncio.sleep(self.reconnect_delay)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self.run_forever()), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
