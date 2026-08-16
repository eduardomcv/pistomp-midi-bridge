import asyncio

import pytest
import websockets

from mod_state import ModState, ModStateClient


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
async def test_run_forever_survives_connection_refused():
    state = ModState()
    # Nothing listens on this port.
    client = ModStateClient("ws://127.0.0.1:1", state, reconnect_delay=0.01)

    task = asyncio.create_task(client.run_forever())
    await asyncio.sleep(0.1)
    client.stop()
    await asyncio.wait_for(task, timeout=2)
