"""OPC UA server that streams a simulated scenario the way a real line would.

    python -m sim.opcua_server --scenario bearing_wear --speed 120

Address space:  Objects / Line / <MACHINE> / {state, temp_c, vibration_mm_s, ...}
                Objects / Line / SampleTime   (written last for every sample)

``--speed`` is the replay speed factor: 1 = real time (one sample per 10 s),
120 = a six-hour shift in three minutes. The server is the OT side of the project;
sim/collector.py is the matching IT-side client.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from asyncua import Server, ua

from sim.line import MACHINES, SAMPLE_SECONDS, SCENARIOS, SIGNALS, generate

NAMESPACE = "urn:plantops:line"


async def serve(scenario: str, speed: float, port: int, host: str = "127.0.0.1",
                loop_forever: bool = False, ready: asyncio.Event | None = None) -> None:
    df = generate(scenario)
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://{host}:{port}/plantops/")
    server.set_server_name("PlantOps line simulator")
    idx = await server.register_namespace(NAMESPACE)

    line = await server.nodes.objects.add_object(idx, "Line")
    sample_time = await line.add_variable(idx, "SampleTime", "")
    nodes: dict[str, dict[str, object]] = {}
    for machine in MACHINES:
        obj = await line.add_object(idx, machine)
        nodes[machine] = {"state": await obj.add_variable(idx, "state", "RUN")}
        for sig in SIGNALS:
            nodes[machine][sig] = await obj.add_variable(idx, sig, ua.Variant(0.0, ua.VariantType.Double))

    delay = SAMPLE_SECONDS / max(speed, 0.001)
    async with server:
        if ready is not None:
            ready.set()
        while True:
            for ts, chunk in df.groupby("ts", sort=True):
                for row in chunk.itertuples(index=False):
                    machine_nodes = nodes[row.machine_id]
                    await machine_nodes["state"].write_value(row.state)
                    for sig in SIGNALS:
                        value = getattr(row, sig)
                        await machine_nodes[sig].write_value(ua.Variant(float(value), ua.VariantType.Double))
                await sample_time.write_value(ts.strftime("%Y-%m-%dT%H:%M:%S"))
                await asyncio.sleep(delay)
            if not loop_forever:
                await asyncio.sleep(1.0)
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="bearing_wear", choices=list(SCENARIOS))
    parser.add_argument("--speed", type=float, default=120.0, help="replay speed factor (1 = real time)")
    parser.add_argument("--port", type=int, default=4840)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--loop", action="store_true", help="restart the shift when it ends")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print(f"OPC UA server on opc.tcp://{args.host}:{args.port}/plantops/  (scenario={args.scenario}, speed x{args.speed})")
    asyncio.run(serve(args.scenario, args.speed, args.port, args.host, args.loop))


if __name__ == "__main__":
    main()
