"""Deterministic anomaly detection for line signals (no LLM involved).

Methods
-------
* Robust drift detection: median/MAD baseline from the first quarter of the
  shift, 10-minute rolling median, |z| > 4 sustained for at least 20 samples.
* Alarm-limit check (alert and trip) on all samples, regardless of machine state.
* Stuck sensor (flatline) and signal dropout (missing data while running).
* Multivariate check per machine: Isolation Forest trained on the baseline
  window, flagged when at least 60 % of a 5-minute window is anomalous.

The agents do not compute these values. They call tools that wrap this module,
which keeps results reproducible and token usage low.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

SIGNALS = ["temp_c", "vibration_mm_s", "motor_current_a", "cycle_time_s", "rejects_per_min"]
SIGNAL_LABELS = {
    "temp_c": "temperature (degC)",
    "vibration_mm_s": "vibration (mm/s)",
    "motor_current_a": "motor current (A)",
    "cycle_time_s": "cycle time (s)",
    "rejects_per_min": "rejects (per min)",
}
SAMPLE_SECONDS = 10
BASELINE_FRACTION = 0.25
Z_THRESHOLD = 4.0
MIN_DRIFT_SAMPLES = 20
MIN_FLATLINE_SAMPLES = 30
MIN_MISSING_SAMPLES = 60  # 10 minutes
REPORT_THRESHOLD = 20

LIMITS_PATH = Path(__file__).resolve().parent.parent / "config" / "limits.json"


@lru_cache(maxsize=1)
def load_limits() -> dict[str, dict[str, dict[str, float]]]:
    with open(LIMITS_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return inclusive (start, end) index pairs of consecutive True values."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[idx[0], idx[splits + 1]]
    ends = np.r_[idx[splits], idx[-1]]
    return list(zip(starts.tolist(), ends.tolist()))


def _hhmm(ts: pd.Timestamp | None) -> str | None:
    return None if ts is None else pd.Timestamp(ts).strftime("%H:%M")


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _round(x: float | None, nd: int = 2) -> float | None:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return round(float(x), nd)


def _multivariate(machine_df: pd.DataFrame, ref_end: pd.Timestamp) -> dict[str, Any]:
    """Run an Isolation Forest on the running samples of one machine."""
    cols = ["temp_c", "vibration_mm_s", "motor_current_a", "cycle_time_s"]
    run = machine_df[machine_df["state"] == "RUN"]
    ref = run[run.index <= ref_end]
    post = run[run.index > ref_end]
    if len(ref) < 100 or len(post) < 30:
        return {"flag_minutes": 0.0, "first_ts": None}
    med = ref[cols].median()
    sigma = (ref[cols] - med).abs().median() * 1.4826
    sigma = sigma.where(sigma > 1e-6, 1.0)
    x_ref = ((ref[cols].fillna(med) - med) / sigma).to_numpy()
    x_post = ((post[cols].fillna(med) - med) / sigma).to_numpy()
    model = IsolationForest(n_estimators=100, contamination=0.01, random_state=0).fit(x_ref)
    flagged = (model.predict(x_post) == -1).astype(float)
    frac = pd.Series(flagged).rolling(30, min_periods=30).mean().to_numpy()
    sustained = np.nan_to_num(frac, nan=0.0) >= 0.6
    n = int(sustained.sum())
    first = post.index[int(np.flatnonzero(sustained)[0])] if n else None
    return {"flag_minutes": round(n * SAMPLE_SECONDS / 60.0, 1), "first_ts": first}


def scan(df: pd.DataFrame, include_windows: bool = False, top_n: int = 8) -> dict[str, Any]:
    """Scan one scenario (all machines) and return ranked findings."""
    limits = load_limits()
    df = df.sort_values("ts")
    t_start, t_end = df["ts"].min(), df["ts"].max()
    ref_end = t_start + (t_end - t_start) * BASELINE_FRACTION

    findings: list[dict[str, Any]] = []
    machines = sorted(df["machine_id"].unique())

    for machine in machines:
        m = df[df["machine_id"] == machine].set_index("ts")
        run = m[m["state"] == "RUN"]
        mv = _multivariate(m, ref_end)

        for sig in SIGNALS:
            valid = run[sig].dropna()
            ref = valid[valid.index <= ref_end]
            lim = limits.get(machine, {}).get(sig, {})
            alert, trip = lim.get("alert"), lim.get("trip")
            score = 0.0
            types: list[str] = []
            windows: list[dict[str, str]] = []
            ev: dict[str, Any] = {}

            # Missing data while running
            miss_mask = run[sig].isna().to_numpy()
            miss_segs = _segments(miss_mask)
            missing_samples = int(miss_mask.sum())
            if missing_samples >= MIN_MISSING_SAMPLES:
                s, e = max(miss_segs, key=lambda se: se[1] - se[0])
                types.append("signal_dropout")
                score += 30
                ev["missing_minutes"] = round(missing_samples * SAMPLE_SECONDS / 60.0, 1)
                ev["dropout_from"] = _hhmm(run.index[s])
                ev["dropout_to"] = _hhmm(run.index[e])
                windows.append({"type": "dropout", "start": _iso(run.index[s]), "end": _iso(run.index[e])})

            if len(valid) < 60 or len(ref) < 30:
                if types:
                    findings.append(_finding(machine, sig, score, types, ev, windows, mv, include_windows))
                continue

            # Stuck sensor (flatline)
            values = valid.to_numpy()
            eq = np.r_[False, np.diff(values) == 0]
            flat_segs = [(s, e) for s, e in _segments(eq) if (e - s + 1) >= MIN_FLATLINE_SAMPLES]
            if flat_segs:
                s, e = max(flat_segs, key=lambda se: se[1] - se[0])
                types.append("stuck_sensor")
                score += 45
                ev["flatline_minutes"] = round((e - s + 1) * SAMPLE_SECONDS / 60.0, 1)
                ev["flatline_from"] = _hhmm(valid.index[s - 1] if s > 0 else valid.index[s])
                ev["flatline_to"] = _hhmm(valid.index[e])
                ev["flatline_value"] = _round(values[e], 3)
                windows.append({"type": "flatline", "start": _iso(valid.index[max(s - 1, 0)]), "end": _iso(valid.index[e])})

            # Drift versus baseline
            med = float(ref.median())
            sigma = max(float((ref - med).abs().median()) * 1.4826, 0.005 * abs(med), 1e-3)
            smooth = valid.rolling("10min").median()
            z = (smooth - med) / sigma
            post = valid.index > ref_end
            breach = (z.abs() > Z_THRESHOLD).to_numpy() & post
            segs = [(s, e) for s, e in _segments(breach) if (e - s + 1) >= MIN_DRIFT_SAMPLES]
            drift = bool(segs)
            max_z = float(np.nanmax(np.abs(z.to_numpy()[post]))) if post.any() else 0.0
            if drift:
                s, e = max(segs, key=lambda se: se[1] - se[0])
                direction = "up" if float(z.iloc[e]) > 0 else "down"
                types.append(f"drift_{direction}")
                score += min(max_z, 20.0) * 2.5 + 10
                ev["first_breach"] = _hhmm(valid.index[segs[0][0]])
                ev["breach_minutes"] = round(sum(e2 - s2 + 1 for s2, e2 in segs) * SAMPLE_SECONDS / 60.0, 1)
                windows.append({"type": "drift", "start": _iso(valid.index[segs[0][0]]), "end": _iso(valid.index[-1])})

                recent = valid.resample("10min").mean().dropna().tail(9)
                if len(recent) >= 5:
                    x = (recent.index - recent.index[0]).total_seconds().to_numpy() / 3600.0
                    slope = float(np.polyfit(x, recent.to_numpy(), 1)[0])
                    ev["slope_per_hour"] = _round(slope, 3)
                    last = float(recent.iloc[-1])
                    if alert is not None and slope > 0 and last < alert:
                        eta = (alert - last) / slope
                        if eta < 24:
                            ev["hours_to_alert_at_current_trend"] = round(eta, 1)
                            if eta < 4:
                                score += 10

            # Alarm limits (any machine state)
            anyv = m[sig].dropna()
            if alert is not None:
                over = anyv[anyv > alert]
                if len(over):
                    types.append("alert_limit_breach")
                    score += 20
                    ev["first_alert_breach"] = _hhmm(over.index[0])
                    ev["samples_over_alert"] = int(len(over))
            if trip is not None:
                over_t = anyv[anyv >= trip * 0.995]
                if len(over_t):
                    types.append("trip_limit_reached")
                    score += 15
                    ev["first_trip_level"] = _hhmm(over_t.index[0])

            if types:
                ev.update(
                    baseline=_round(med, 3),
                    latest=_round(float(valid.tail(60).mean()), 3),
                    max=_round(float(anyv.max()), 3),
                    max_z=_round(max_z, 1) if drift else None,
                    alert_limit=alert,
                    trip_limit=trip,
                )
                if mv["flag_minutes"] > 0:
                    score += 5
                findings.append(_finding(machine, sig, score, types, ev, windows, mv, include_windows))

    findings = [f for f in findings if f["severity"] >= REPORT_THRESHOLD]
    findings.sort(key=lambda f: -f["severity"])
    flagged_machines = {f["machine_id"] for f in findings}
    return {
        "window": {"start": _iso(t_start), "end": _iso(t_end), "baseline_until": _hhmm(ref_end)},
        "method": "robust z-score vs first-quarter baseline (10 min rolling median), alarm limits, "
        "flatline/dropout checks, IsolationForest per machine",
        "findings": findings[:top_n],
        "machines_without_findings": [m for m in machines if m not in flagged_machines],
    }


def _finding(machine, sig, score, types, ev, windows, mv, include_windows) -> dict[str, Any]:
    out: dict[str, Any] = {
        "machine_id": machine,
        "signal": sig,
        "severity": int(round(min(score, 100))),
        "issues": types,
        "evidence": {k: v for k, v in ev.items() if v is not None},
        "machine_multivariate_anomaly_minutes": mv["flag_minutes"],
    }
    if include_windows:
        out["windows"] = windows
    return out


def hourly_trend(df: pd.DataFrame, machine: str, signal: str) -> dict[str, Any]:
    """Return the hourly average and maximum of one signal (RUN samples) plus its limits."""
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal!r}; choose from {SIGNALS}")
    m = df[(df["machine_id"] == machine)].set_index("ts").sort_index()
    if m.empty:
        raise ValueError(f"unknown machine {machine!r}")
    run = m[m["state"] == "RUN"]
    grouped = run[signal].resample("1h")
    rows = []
    for hour, g in grouped:
        g = g.dropna()
        rows.append(
            {
                "hour": _hhmm(hour),
                "avg": _round(g.mean(), 3) if len(g) else None,
                "max": _round(g.max(), 3) if len(g) else None,
                "valid_samples": int(len(g)),
            }
        )
    lim = load_limits().get(machine, {}).get(signal, {})
    return {"machine_id": machine, "signal": signal, "unit": SIGNAL_LABELS[signal], "hourly": rows, "limits": lim}


def chart_series(df: pd.DataFrame, machine: str, signal: str) -> dict[str, Any]:
    """Return a 1-minute series of one signal, including machine state, for plotting."""
    m = df[df["machine_id"] == machine].set_index("ts").sort_index()
    if m.empty:
        raise ValueError(f"unknown machine {machine!r}")
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal!r}")
    per_min = m[signal].resample("1min").mean()
    state_min = m["state"].resample("1min").agg(lambda s: s.mode().iat[0] if len(s) else "RUN")
    points = [
        {"t": _iso(ts), "v": None if pd.isna(v) else round(float(v), 3), "s": state_min.loc[ts]}
        for ts, v in per_min.items()
    ]
    return {
        "machine_id": machine,
        "signal": signal,
        "label": SIGNAL_LABELS[signal],
        "limits": load_limits().get(machine, {}).get(signal, {}),
        "points": points,
    }
