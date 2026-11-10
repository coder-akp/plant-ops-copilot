"""Generate the simulator data and build the dbt models: python -m scripts.build_data

Produces data/raw/*.parquet and data/plantops.duckdb. Works on all platforms without make.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    raw = Path(os.environ.get("PLANTOPS_RAW_DIR") or ROOT / "data" / "raw").resolve()
    db = Path(os.environ.get("PLANTOPS_DB") or ROOT / "data" / "plantops.duckdb").resolve()
    os.environ["PLANTOPS_RAW_DIR"] = str(raw)
    os.environ["PLANTOPS_DB"] = str(db)
    os.environ.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")

    sys.path.insert(0, str(ROOT))
    from sim.generate import main as generate_main

    sys.argv = ["sim.generate", "--out", str(raw)]
    generate_main()

    if db.exists():
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        from dbt.cli.main import dbtRunner
    except ImportError:
        print("dbt is not installed. Run: pip install -r requirements-build.txt", file=sys.stderr)
        return 1

    project = str(ROOT / "dbt_project")
    result = dbtRunner().invoke(["build", "--project-dir", project, "--profiles-dir", project, "--quiet"])
    if not result.success:
        print("dbt build failed", file=sys.stderr)
        return 1
    print(f"built {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
