"""Write the scenario datasets as Parquet files: python -m sim.generate"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from sim.line import SCENARIOS, SIGNALS, generate


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Convert a DataFrame to Parquet through DuckDB (no pyarrow dependency).

    NaN values are converted to SQL NULL so that downstream models treat them as missing data.
    """
    select_signals = ", ".join(f"CASE WHEN isnan({c}) THEN NULL ELSE {c} END AS {c}" for c in SIGNALS)
    con = duckdb.connect()
    try:
        con.register("df_in", df)
        con.execute(
            f"COPY (SELECT scenario, ts, machine_id, state, {select_signals} "
            f"FROM df_in ORDER BY ts, machine_id) TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/raw", help="output directory")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for scenario_id in SCENARIOS:
        df = generate(scenario_id, seed=args.seed)
        path = out / f"{scenario_id}.parquet"
        write_parquet(df, path)
        print(f"wrote {path} ({len(df):,} rows)")


if __name__ == "__main__":
    main()
