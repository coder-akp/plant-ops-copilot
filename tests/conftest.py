"""Shared fixtures: the database is built once per test session (real dbt run)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def built_db(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("plantops")
    env = {**os.environ, "PLANTOPS_RAW_DIR": str(base / "raw"), "PLANTOPS_DB": str(base / "plantops.duckdb"),
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    proc = subprocess.run([sys.executable, "-m", "scripts.build_data"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return base / "plantops.duckdb"


@pytest.fixture(scope="session")
def db(built_db):
    from app import data
    from app.tools import clear_caches

    data.configure(built_db)
    clear_caches()
    return built_db
