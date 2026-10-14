from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.schemas import PointIn, SeriesIn
from app.series import infer_frequency, prepare_series


def _series(count: int, *, step: timedelta = timedelta(hours=1), value_at=lambda i: 10 + i) -> SeriesIn:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return SeriesIn(
        id="temp-01",
        metric="temperature",
        unit="C",
        points=[
            PointIn(timestamp=start + step * i, value=value_at(i))
            for i in range(count)
        ],
    )


def test_prepare_hourly_series_keeps_step():
    frame, frequency = prepare_series(_series(12), None, max_points=100, min_points=10)
    assert len(frame) == 12
    assert frame.index[1] - frame.index[0] == pd.Timedelta(hours=1)
    assert infer_frequency(frame.index) == frequency


def test_duplicate_timestamps_keep_the_last_value():
    series = _series(12)
    series.points.append(PointIn(timestamp=series.points[0].timestamp, value=99))
    frame, _frequency = prepare_series(series, "h", max_points=100, min_points=10)
    assert float(frame["value"].iloc[0]) == 99


def test_span_over_the_limit_is_rejected():
    series = _series(10, step=timedelta(days=1))
    with pytest.raises(ValueError, match="лимит"):
        prepare_series(series, "h", max_points=48, min_points=10)
