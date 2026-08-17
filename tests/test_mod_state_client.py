import asyncio

import pytest
import websockets

from pistomp_midi_bridge.mod_state import ModState, ModStateClient


@pytest.mark.asyncio
async def test_run_once_feeds_state_until_connection_closes():
    async def handler(ws):
        await ws.send("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
        await ws.send("param_set /graph/Noisegate :bypass 1.000000")

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state = ModState()
        client = ModStateClient(f"ws://127.0.0.1:{port}", state)

        await client.run_once()

    binding = state.lookup(channel=14, controller=110)
    assert binding is not None
    assert binding.value == 1.0


@pytest.mark.asyncio
async def test_run_forever_reconnects_after_server_closes_connection():
    connection_count = 0

    async def handler(ws):
        nonlocal connection_count
        connection_count += 1
        await ws.send("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state = ModState()
        client = ModStateClient(f"ws://127.0.0.1:{port}", state, reconnect_delay=0.01)

        task = asyncio.create_task(client.run_forever())
        await asyncio.sleep(0.2)
        client.stop()
        await asyncio.wait_for(task, timeout=2)

    assert connection_count >= 2


@pytest.mark.asyncio
async def test_run_forever_reconnects_after_abnormal_disconnect():
    """An abnormal close (e.g. a stalled ping/pong or a killed mod-ui process)
    raises ConnectionClosedError, not OSError. run_forever must reconnect
    instead of letting the exception escape and silently killing the
    connection loop, leaving ModState serving stale data forever."""
    connection_count = 0

    async def handler(ws):
        nonlocal connection_count
        connection_count += 1
        await ws.send("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
        if connection_count == 1:
            await ws.close(code=1011)  # abnormal: "unexpected condition"

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state = ModState()
        client = ModStateClient(f"ws://127.0.0.1:{port}", state, reconnect_delay=0.01)

        task = asyncio.create_task(client.run_forever())
        await asyncio.sleep(0.2)
        client.stop()
        await asyncio.wait_for(task, timeout=2)

    assert connection_count >= 2


@pytest.mark.asyncio
async def test_run_once_replies_pong_to_mod_ui_ping():
    """mod-ui's SESSION.web_ping (session.py) broadcasts a bare "ping" text
    frame and expects a bare "pong" reply (webserver.py's on_message treats
    "pong" as a no-op ack). We must reply, or mod-ui has no way to know this
    client is still alive."""
    received = []

    async def handler(ws):
        await ws.send("ping")
        received.append(await asyncio.wait_for(ws.recv(), timeout=2))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state = ModState()
        client = ModStateClient(f"ws://127.0.0.1:{port}", state)

        await client.run_once()

    assert received == ["pong"]


@pytest.mark.asyncio
async def test_disconnect_stops_serving_stale_values_until_reconnected():
    """Reproduces the reported bug: once a value is cached, an abnormal
    disconnect must not leave lookup() serving that stale value forever.
    It should gate (return None) while disconnected, and only resume once
    a fresh connection's dump proves the cache is live again."""
    connection_count = 0
    server_ready_for_second_connection = asyncio.Event()
    let_first_connection_close = asyncio.Event()
    let_second_connection_close = asyncio.Event()

    async def handler(ws):
        nonlocal connection_count
        connection_count += 1

        if connection_count == 1:
            await ws.send("midi_map /graph/Noisegate :bypass 14 110 0.0 1.0")
            await ws.send("param_set /graph/Noisegate :bypass 1.000000")
            await let_first_connection_close.wait()
            await ws.close(code=1011)
        else:
            server_ready_for_second_connection.set()
            await let_second_connection_close.wait()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state = ModState()
        client = ModStateClient(f"ws://127.0.0.1:{port}", state, reconnect_delay=0.01)

        task = asyncio.create_task(client.run_forever())

        try:
            # First connection is up and has fed us a live value.
            for _ in range(100):
                if state.lookup(channel=14, controller=110) is not None:
                    break
                await asyncio.sleep(0.01)
            assert state.lookup(channel=14, controller=110) is not None

            # Abnormal disconnect happens; before the reconnect's fresh dump
            # arrives, the cached value must not be served.
            let_first_connection_close.set()
            await asyncio.wait_for(server_ready_for_second_connection.wait(), timeout=2)
            assert state.lookup(channel=14, controller=110) is None
        finally:
            let_second_connection_close.set()
            client.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert connection_count == 2


@pytest.mark.asyncio
async def test_run_forever_survives_connection_refused():
    state = ModState()
    # Nothing listens on this port.
    client = ModStateClient("ws://127.0.0.1:1", state, reconnect_delay=0.01)

    task = asyncio.create_task(client.run_forever())
    await asyncio.sleep(0.1)
    client.stop()
    await asyncio.wait_for(task, timeout=2)
