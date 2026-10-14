import math
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.schemas import PointIn, SeriesIn
from app.series import prepare_series


def test_chronos_forecast_on_synthetic_hourly_series():
    if os.environ.get("RUN_CHRONOS") != "1":
        pytest.skip("Задайте RUN_CHRONOS=1, чтобы скачать amazon/chronos-2 и прогнать модель")
    pytest.importorskip("chronos")
    from app.forecasting.chronos_model import forecast_with_chronos, reset_chronos_state

    reset_chronos_state()
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    points = []
    for i in range(72):
        value = 20 + 0.03 * i + 2 * math.sin(2 * math.pi * i / 24)
        points.append(PointIn(timestamp=start + timedelta(hours=i), value=value))
    series = SeriesIn(id="temp-01", metric="temperature", unit="C", points=points)
    frame, frequency = prepare_series(series, "h", max_points=5000, min_points=10)
    forecast, components = forecast_with_chronos(frame, series.id, 6, frequency, Settings(chronos_device="cpu"))
    assert components == {}
    assert len(forecast) == 6
    assert all(point["lower"] <= point["value"] <= point["upper"] for point in forecast)
