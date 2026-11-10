"""Deterministic simulator of a small bottling line with injectable faults.

The simulator represents the operational-technology (OT) side of the project. It
produces the signals that a PLC/SCADA historian would deliver (machine state,
temperature, vibration, motor current, cycle time, rejects) at a 10 s sampling
interval.

Every scenario is fully reproducible (seeded), so the detection tools, the tests
and the recorded agent replays stay stable.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

MACHINES = ["FILLER-01", "CAPPER-01", "LABELER-01", "PACKER-01"]
SIGNALS = ["temp_c", "vibration_mm_s", "motor_current_a", "cycle_time_s", "rejects_per_min"]
SAMPLE_SECONDS = 10
DURATION_HOURS = 6
N_SAMPLES = DURATION_HOURS * 3600 // SAMPLE_SECONDS  # 2160
SHIFT_START = pd.Timestamp("2026-03-02 06:00:00")

# Nominal (mean) values per machine
NOMINAL = {
    "FILLER-01": {"temp_c": 41.0, "vibration_mm_s": 2.1, "motor_current_a": 14.0, "cycle_time_s": 1.80, "rejects_per_min": 0.6},
    "CAPPER-01": {"temp_c": 52.0, "vibration_mm_s": 1.6, "motor_current_a": 9.5, "cycle_time_s": 1.80, "rejects_per_min": 0.4},
    "LABELER-01": {"temp_c": 36.0, "vibration_mm_s": 1.2, "motor_current_a": 6.0, "cycle_time_s": 1.80, "rejects_per_min": 0.7},
    "PACKER-01": {"temp_c": 38.0, "vibration_mm_s": 1.8, "motor_current_a": 11.0, "cycle_time_s": 3.60, "rejects_per_min": 0.3},
}
NOISE_STD = {"temp_c": 0.6, "vibration_mm_s": 0.12, "motor_current_a": 0.35, "cycle_time_s": 0.03, "rejects_per_min": 0.25}

CLEAN_START_IDX = int(3.0 * 3600 / SAMPLE_SECONDS)   # line cleaning (CIP) at 09:00
CLEAN_LEN = 60                                        # 10 minutes


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    story: str
    ground_truth: str


SCENARIOS: dict[str, Scenario] = {
    "healthy": Scenario(
        "healthy",
        "Normal shift",
        "A regular six-hour shift with the usual short stops and a scheduled cleaning. Nothing is wrong.",
        "No fault injected. A good system reports that no action is required and does not invent problems.",
    ),
    "bearing_wear": Scenario(
        "bearing_wear",
        "Creeping bearing wear",
        "The filler gets louder and draws more current as the shift goes on, but nothing has tripped yet.",
        "FILLER-01: gearbox/motor bearing wear starting at 07:30. Vibration and motor current drift upward; "
        "the vibration alert limit (4.5 mm/s) is crossed around 10:40, followed by micro-stops.",
    ),
    "overheating": Scenario(
        "overheating",
        "Repeated thermal trips",
        "The capper keeps stopping. Operators reset it again and again.",
        "CAPPER-01: cooling fan failure at 08:30. Temperature climbs exponentially, the thermal protection trips "
        "at 68 degC, and the pattern repeats roughly every 25 minutes.",
    ),
    "sensor_fault": Scenario(
        "sensor_fault",
        "Suspicious temperature reading",
        "The labeler's temperature looks oddly perfect for a while and then disappears.",
        "LABELER-01: temperature sensor stuck at a constant value from 08:00 for 90 minutes, then a 20 minute "
        "signal dropout. Motor current and vibration stay normal, so the machine itself is fine.",
    ),
}


def _stable_seed(seed: int, scenario: str, machine: str) -> int:
    return seed + zlib.crc32(f"{scenario}/{machine}".encode()) % 1_000_000


def _ar1(rng: np.random.Generator, n: int, std: float, phi: float = 0.85) -> np.ndarray:
    """AR(1) noise with the requested marginal standard deviation."""
    innovations = rng.normal(0.0, std * math.sqrt(1 - phi**2), n)
    out = np.empty(n)
    out[0] = rng.normal(0.0, std)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + innovations[i]
    return out


def _simulate_machine(scenario: str, machine: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(_stable_seed(seed, scenario, machine))
    nom = NOMINAL[machine]
    n = N_SAMPLES
    t_h = np.arange(n) * SAMPLE_SECONDS / 3600.0

    sig = {
        "temp_c": nom["temp_c"] + 0.8 * np.sin(2 * math.pi * t_h / 6.0) + _ar1(rng, n, NOISE_STD["temp_c"]),
        "vibration_mm_s": nom["vibration_mm_s"] + _ar1(rng, n, NOISE_STD["vibration_mm_s"]),
        "motor_current_a": nom["motor_current_a"] + _ar1(rng, n, NOISE_STD["motor_current_a"]),
        "cycle_time_s": nom["cycle_time_s"] + _ar1(rng, n, NOISE_STD["cycle_time_s"], phi=0.5),
        "rejects_per_min": np.clip(nom["rejects_per_min"] + rng.normal(0, NOISE_STD["rejects_per_min"], n), 0, None),
    }

    fault = np.zeros(n, dtype=bool)  # samples forced into the FAULT state

    if scenario == "bearing_wear" and machine == "FILLER-01":
        t0 = 1.5
        prog = np.clip((t_h - t0) / (DURATION_HOURS - t0), 0, 1)
        sig["vibration_mm_s"] = sig["vibration_mm_s"] + 4.0 * prog**2 + rng.normal(0, 0.10, n) * (1 + 2 * prog)
        sig["motor_current_a"] = sig["motor_current_a"] + 1.9 * prog**1.5
        sig["cycle_time_s"] = sig["cycle_time_s"] + 0.05 * prog
        over = sig["vibration_mm_s"] > 4.5
        p_stop = np.where(over, 0.003 * (sig["vibration_mm_s"] - 4.0), 0.0)
        i = 0
        while i < n:
            if rng.random() < p_stop[i]:
                length = int(rng.integers(3, 10))
                fault[i : i + length] = True
                i += length
            else:
                i += 1

    if scenario == "overheating" and machine == "CAPPER-01":
        fan_idx = int(2.5 * 3600 / SAMPLE_SECONDS)
        excess = 0.0
        trip_until = -1
        base_temp = sig["temp_c"].copy()
        temp = base_temp.copy()
        for i in range(n):
            if i < fan_idx:
                continue
            if i < trip_until:
                excess = max(8.0, excess - 0.12)
                fault[i] = True
            else:
                excess += (24.0 - excess) / 240.0
                if base_temp[i] + excess > 68.0:
                    trip_until = i + 60
                    fault[i] = True
            temp[i] = base_temp[i] + excess
        sig["temp_c"] = temp
        extra = np.clip((temp - base_temp) / 24.0, 0, 1)
        sig["motor_current_a"] = sig["motor_current_a"] + 0.9 * extra
        sig["rejects_per_min"] = sig["rejects_per_min"] + 1.2 * extra

    if scenario == "sensor_fault" and machine == "LABELER-01":
        start = int(2.0 * 3600 / SAMPLE_SECONDS)
        stuck_len = 90 * 60 // SAMPLE_SECONDS
        drop_len = 20 * 60 // SAMPLE_SECONDS
        temp = sig["temp_c"].copy()
        temp[start : start + stuck_len] = temp[start]
        temp[start + stuck_len : start + stuck_len + drop_len] = np.nan
        sig["temp_c"] = temp

    # Machine states
    state = np.array(["RUN"] * n, dtype=object)
    for _ in range(5):  # short starved or blocked stops
        start = int(rng.integers(30, n - 40))
        state[start : start + int(rng.integers(6, 24))] = "IDLE"
    state[CLEAN_START_IDX : CLEAN_START_IDX + CLEAN_LEN] = "CLEAN"
    state[fault] = "FAULT"

    not_run = state != "RUN"
    sig["motor_current_a"] = np.where(not_run, 0.2 * nom["motor_current_a"] + rng.normal(0, 0.05, n), sig["motor_current_a"])
    sig["vibration_mm_s"] = np.where(not_run, 0.25 + rng.normal(0, 0.03, n), sig["vibration_mm_s"])
    sig["cycle_time_s"] = np.where(not_run, np.nan, sig["cycle_time_s"])
    sig["rejects_per_min"] = np.where(not_run, 0.0, sig["rejects_per_min"])

    ts = SHIFT_START + pd.to_timedelta(np.arange(n) * SAMPLE_SECONDS, unit="s")
    df = pd.DataFrame({"scenario": scenario, "ts": ts, "machine_id": machine, "state": state})
    for name in SIGNALS:
        df[name] = np.round(sig[name], 3)
    return df


def generate(scenario: str, seed: int = 7) -> pd.DataFrame:
    """Return the full long-format dataset for one scenario (all machines)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    frames = [_simulate_machine(scenario, m, seed) for m in MACHINES]
    return pd.concat(frames, ignore_index=True).sort_values(["ts", "machine_id"]).reset_index(drop=True)
