"""OPC UA collector: reads the line from the OPC UA server into a Parquet file.

    python -m sim.collector --samples 360 --out data/raw/live.parquet

The file uses the same schema as the simulator output (scenario = "live"), so
``python -m scripts.build_data`` includes it and the dbt models, detectors and web
app handle it like any other scenario.
"""
from __future__ import annotations

import argparse
import asyncio
import math
from pathlib import Path

import pandas as pd
from asyncua import Client

from sim.generate import write_parquet
from sim.line import MACHINES, SAMPLE_SECONDS, SIGNALS
from sim.opcua_server import NAMESPACE


async def collect(url: str, samples: int, poll_s: float, timeout_s: float = 300.0) -> pd.DataFrame:
    rows: list[dict] = []
    async with Client(url=url, timeout=10) as client:
        ns = await client.get_namespace_index(NAMESPACE)
        line = await client.nodes.objects.get_child([f"{ns}:Line"])
        sample_node = await line.get_child([f"{ns}:SampleTime"])
        machine_nodes: dict[str, dict[str, object]] = {}
        for machine in MACHINES:
            obj = await line.get_child([f"{ns}:{machine}"])
            machine_nodes[machine] = {name: await obj.get_child([f"{ns}:{name}"]) for name in ["state", *SIGNALS]}

        order = [(m, n) for m in MACHINES for n in ["state", *SIGNALS]]
        read_nodes = [sample_node] + [machine_nodes[m][n] for m, n in order]
        last = ""
        deadline = asyncio.get_running_loop().time() + timeout_s
        seen = 0
        while seen < samples and asyncio.get_running_loop().time() < deadline:
            values = await client.read_values(read_nodes)
            stamp = values[0]
            if stamp and stamp != last:
                last = stamp
                seen += 1
                by_machine: dict[str, dict] = {m: {"scenario": "live", "ts": pd.Timestamp(stamp), "machine_id": m} for m in MACHINES}
                for (m, n), v in zip(order, values[1:]):
                    by_machine[m][n] = v
                rows.extend(by_machine.values())
            await asyncio.sleep(poll_s)
    df = pd.DataFrame(rows)
    for sig in SIGNALS:
        df[sig] = pd.to_numeric(df[sig], errors="coerce").map(lambda x: x if x is None or not math.isinf(x) else float("nan"))
    return df[["scenario", "ts", "machine_id", "state", *SIGNALS]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="opc.tcp://127.0.0.1:4840/plantops/")
    parser.add_argument("--samples", type=int, default=360, help="number of 10 s samples to record (360 = 1 h of data)")
    parser.add_argument("--speed", type=float, default=120.0, help="speed factor used by the server (sets the poll rate)")
    parser.add_argument("--out", default="data/raw/live.parquet")
    args = parser.parse_args()

    poll = max(SAMPLE_SECONDS / args.speed / 4, 0.005)
    df = asyncio.run(collect(args.url, args.samples, poll))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_parquet(df, out)
    print(f"wrote {out} ({len(df):,} rows, {df['ts'].nunique()} samples)")


if __name__ == "__main__":
    main()
