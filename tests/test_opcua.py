"""OPC UA round trip: simulator server -> collector -> Parquet-ready DataFrame."""
import asyncio

import pandas as pd

from sim.collector import collect
from sim.line import MACHINES, SAMPLE_SECONDS
from sim.opcua_server import serve


async def test_server_and_collector_round_trip():
    port = 48431
    ready = asyncio.Event()
    server = asyncio.create_task(serve("healthy", speed=50, port=port, ready=ready))
    try:
        await asyncio.wait_for(ready.wait(), 20)
        df = await collect(f"opc.tcp://127.0.0.1:{port}/plantops/", samples=30, poll_s=0.005, timeout_s=40)
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)

    assert len(df) == 30 * len(MACHINES)
    assert set(df["machine_id"]) == set(MACHINES) and set(df["scenario"]) == {"live"}
    assert set(df["state"]) <= {"RUN", "IDLE", "CLEAN", "FAULT"}
    stamps = pd.Series(sorted(df["ts"].unique()))
    gaps = stamps.diff().dropna().dt.total_seconds()
    assert (gaps > 0).all() and (gaps % SAMPLE_SECONDS == 0).all()
    assert (gaps == SAMPLE_SECONDS).mean() >= 0.8
    assert df["temp_c"].between(20, 80).all()
