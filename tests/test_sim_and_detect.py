"""Simulator determinism and detector accuracy against the known ground truth."""
import numpy as np
import pytest

from app import data, detect
from sim.line import MACHINES, SCENARIOS, generate


def test_generation_is_deterministic():
    a, b = generate("bearing_wear"), generate("bearing_wear")
    assert a.equals(b)
    assert generate("bearing_wear", seed=8).equals(a) is False


def test_shape_and_states():
    df = generate("healthy")
    assert len(df) == 2160 * len(MACHINES)
    assert set(df["state"]) == {"RUN", "IDLE", "CLEAN"}  # no faults in a healthy shift


def test_fault_signatures_are_injected():
    sensor = generate("sensor_fault")
    lab = sensor[sensor.machine_id == "LABELER-01"].reset_index(drop=True)
    stuck = lab.loc[720:1200, "temp_c"]  # from 08:00 for about 80 minutes
    assert stuck.nunique() == 1
    assert lab["temp_c"].isna().sum() == 120
    bearing = generate("bearing_wear")
    vib = bearing[(bearing.machine_id == "FILLER-01") & (bearing.state == "RUN")]["vibration_mm_s"]
    assert vib.tail(100).mean() > vib.head(100).mean() + 2.0


def test_database_has_all_scenarios(db):
    assert data.available_scenarios() == list(SCENARIOS)
    kpis = {r["machine_id"]: r for r in data.machine_kpis("overheating")}
    assert kpis["CAPPER-01"]["fault_events"] >= 3
    assert kpis["CAPPER-01"]["availability_pct"] < 90
    assert kpis["FILLER-01"]["availability_pct"] > 94


EXPECTED = {
    "bearing_wear": ("FILLER-01", "vibration_mm_s", {"drift_up", "alert_limit_breach"}),
    "overheating": ("CAPPER-01", "temp_c", {"drift_up", "trip_limit_reached"}),
    "sensor_fault": ("LABELER-01", "temp_c", {"stuck_sensor", "signal_dropout"}),
}


@pytest.mark.parametrize("scenario", EXPECTED)
def test_detector_finds_the_injected_fault_first(db, scenario):
    machine, signal, issues = EXPECTED[scenario]
    result = detect.scan(data.scenario_frame(scenario))
    top = result["findings"][0]
    assert (top["machine_id"], top["signal"]) == (machine, signal)
    assert issues <= set(top["issues"])
    others = {f["machine_id"] for f in result["findings"]}
    assert others == {machine}, "no false alarms on the other machines"


def test_detector_reports_nothing_on_a_healthy_shift(db):
    result = detect.scan(data.scenario_frame("healthy"))
    assert result["findings"] == []
    assert len(result["machines_without_findings"]) == 4


def test_sensor_fault_is_not_a_machine_problem(db):
    result = detect.scan(data.scenario_frame("sensor_fault"))
    signals = {f["signal"] for f in result["findings"]}
    assert signals == {"temp_c"}  # current and vibration stay clean


def test_hourly_trend_and_chart_series(db):
    df = data.scenario_frame("bearing_wear")
    trend = detect.hourly_trend(df, "FILLER-01", "vibration_mm_s")
    avgs = [r["avg"] for r in trend["hourly"] if r["avg"] is not None]
    assert avgs[-1] > avgs[0] * 2
    series = detect.chart_series(df, "FILLER-01", "vibration_mm_s")
    assert len(series["points"]) == 360
    with pytest.raises(ValueError):
        detect.hourly_trend(df, "NOPE", "temp_c")
