"""Выравнивание истории на регулярный шаг."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.schemas import SeriesIn


def to_iso8601(value: object) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc(value: datetime) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def normalize_frequency(frequency: str) -> str:
    try:
        offset = pd.tseries.frequencies.to_offset(frequency)
    except ValueError as exc:
        raise ValueError(f"Неизвестный frequency: {frequency}") from exc
    if offset is None or pd.to_timedelta(offset) <= pd.Timedelta(0):
        raise ValueError(f"Неизвестный frequency: {frequency}")
    return offset.freqstr


def infer_frequency(index: pd.DatetimeIndex) -> str:
    if len(index) < 2:
        raise ValueError("Нужно минимум две точки, чтобы оценить шаг ряда")
    guessed = pd.infer_freq(index)
    if guessed:
        return normalize_frequency(guessed)
    delta = index.to_series().diff().dropna().median()
    if pd.isna(delta) or delta <= pd.Timedelta(0):
        raise ValueError("Не удалось оценить шаг ряда: метки времени не возрастают")
    seconds = float(delta.total_seconds())
    if seconds < 90:
        return normalize_frequency(f"{max(1, int(round(seconds)))}s")
    if seconds < 90 * 60:
        minutes = max(1, int(round(seconds / 60)))
        return normalize_frequency("min" if minutes == 1 else f"{minutes}min")
    if seconds < 36 * 3600:
        hours = max(1, int(round(seconds / 3600)))
        return normalize_frequency("h" if hours == 1 else f"{hours}h")
    days = max(1, int(round(seconds / 86400)))
    return normalize_frequency("D" if days == 1 else f"{days}D")


def prepare_series(
    series: SeriesIn,
    frequency: str | None,
    *,
    max_points: int,
    min_points: int,
) -> tuple[pd.DataFrame, str]:
    """Вернуть ряд с регулярным индексом UTC и канонический шаг pandas."""
    frame = pd.DataFrame(
        {
            "timestamp": [_as_utc(point.timestamp) for point in series.points],
            "value": [point.value for point in series.points],
        }
    )
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if len(frame) < min_points:
        raise ValueError(
            f"Ряд {series.id}: нужно минимум {min_points} точек с разными метками, получено {len(frame)}"
        )
    if len(frame) > max_points:
        raise ValueError(f"Ряд {series.id}: {len(frame)} точек, лимит {max_points}")

    freq = normalize_frequency(frequency) if frequency else infer_frequency(pd.DatetimeIndex(frame["timestamp"]))
    offset = pd.tseries.frequencies.to_offset(freq)
    step = pd.to_timedelta(offset)
    start = frame["timestamp"].iloc[0]
    end = frame["timestamp"].iloc[-1]
    count = int(round((end - start) / step)) + 1
    if count > max_points:
        raise ValueError(
            f"Ряд {series.id}: на шаге {freq} между первой и последней точкой получается {count} значений, лимит {max_points}"
        )

    regular = frame.set_index("timestamp").resample(offset).mean(numeric_only=True)
    if regular.empty or "value" not in regular.columns:
        raise ValueError(f"Ряд {series.id}: после выравнивания шага не осталось значений")
    regular["value"] = regular["value"].interpolate(limit_direction="both")
    regular = regular.dropna(subset=["value"])
    if len(regular) < min_points:
        raise ValueError(
            f"Ряд {series.id}: после выравнивания шага {freq} осталось {len(regular)} точек, нужно минимум {min_points}"
        )
    regular.index = pd.DatetimeIndex(regular.index).tz_convert("UTC")
    return regular, freq
