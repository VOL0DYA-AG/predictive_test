import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.config import Settings
from app.series import to_iso8601
from app.service import handle_request

ROOT = Path(__file__).resolve().parents[1]


def _points(count: int = 12) -> list[dict]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        {"timestamp": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "value": 10 + i * 0.5}
        for i in range(count)
    ]


def _payload(**overrides) -> bytes:
    body = {
        "request_id": "req-1",
        "model": "prophet",
        "horizon": 4,
        "frequency": "h",
        "series": [{"id": "temp-01", "metric": "temperature", "unit": "C", "points": _points()}],
    }
    body.update(overrides)
    return json.dumps(body).encode()


def _rising(frame, horizon, frequency):
    last = float(frame["value"].iloc[-1])
    offset = pd.tseries.frequencies.to_offset(frequency)
    start = frame.index[-1]
    points = []
    for step in range(1, horizon + 1):
        value = last + step
        points.append(
            {
                "timestamp": to_iso8601(start + step * pd.to_timedelta(offset)),
                "value": value,
                "lower": value - 0.5,
                "upper": value + 0.5,
            }
        )
    return points, {"trend_delta": 1.25, "daily_span": 0.4}


def _falling(frame, series_id, horizon, frequency, settings):
    del series_id, settings
    points, _components = _rising(frame, horizon, frequency)
    last = float(frame["value"].iloc[-1])
    for step, point in enumerate(points, start=1):
        value = last - step
        point["value"] = value
        point["lower"] = value - 0.5
        point["upper"] = value + 0.5
    return points, {}


def test_prophet_response_shape():
    body = handle_request(_payload(), "demo-scada", Settings(), prophet_runner=_rising)
    assert "error" not in body
    assert body["client"] == "demo-scada"
    assert body["request_id"] == "req-1"
    assert body["forecasts"][0]["model"] == "prophet"
    assert len(body["forecasts"][0]["series"][0]["points"]) == 4
    assert body["summary"]["direction"] == "up"
    assert "Prophet" in body["summary"]["text"]
    assert body["warnings"] == []


def test_invalid_json_and_short_series():
    assert "JSON" in handle_request(b"{", "demo-scada", Settings())["error"]
    short = handle_request(_payload(series=[{"id": "temp-01", "points": _points(3)}]), "demo-scada", Settings())
    assert "минимум" in short["error"]
    assert short["request_id"] == "req-1"


def test_both_models_keep_prophet_when_chronos_fails():
    def broken(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("нет весов")

    body = handle_request(
        _payload(model="both"),
        "demo-scada",
        Settings(),
        prophet_runner=_rising,
        chronos_runner=broken,
    )
    assert "error" not in body
    assert [block["model"] for block in body["forecasts"]] == ["prophet"]
    assert body["warnings"]
    assert "не посчиталась" in body["summary"]["text"]


def test_requested_chronos_failure_is_an_error():
    def broken(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("нет весов")

    body = handle_request(
        _payload(model="chronos-2"),
        "demo-scada",
        Settings(),
        chronos_runner=broken,
    )
    assert "нет весов" in body["error"]


def test_models_can_disagree():
    body = handle_request(
        _payload(model="both"),
        "plant-1",
        Settings(),
        prophet_runner=_rising,
        chronos_runner=_falling,
    )
    assert body["summary"]["direction"] == "mixed"
    assert "расходятся" in body["summary"]["text"]


def test_example_file_is_a_valid_request():
    example = json.loads((ROOT / "examples" / "forecast_request.json").read_text(encoding="utf-8"))
    raw = json.dumps(example).encode()
    body = handle_request(raw, "demo-scada", Settings(), prophet_runner=_rising, chronos_runner=_falling)
    assert "error" not in body
    assert body["horizon"] == 24
    assert len(body["forecasts"]) == 2
