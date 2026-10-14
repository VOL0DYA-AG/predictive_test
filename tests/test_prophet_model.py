import math
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas import PointIn, SeriesIn
from app.series import prepare_series


def test_prophet_forecast_on_synthetic_hourly_series():
    pytest.importorskip("prophet")
    from app.forecasting.prophet_model import forecast_with_prophet

    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    points = []
    for i in range(72):
        value = 20 + 0.03 * i + 2 * math.sin(2 * math.pi * i / 24)
        points.append(PointIn(timestamp=start + timedelta(hours=i), value=value))
    series = SeriesIn(id="temp-01", metric="temperature", unit="C", points=points)
    frame, frequency = prepare_series(series, "h", max_points=5000, min_points=10)
    forecast, components = forecast_with_prophet(frame, 24, frequency)
    assert len(forecast) == 24
    assert "trend_delta" in components
    assert all(point["lower"] <= point["upper"] for point in forecast)
