"""Прогноз Facebook Prophet на один ряд."""

from __future__ import annotations

import logging

import pandas as pd

from app.series import to_iso8601

logger = logging.getLogger(__name__)


def _components(forecast: pd.DataFrame) -> dict[str, float]:
    found: dict[str, float] = {}
    if "trend" in forecast.columns and len(forecast) >= 1:
        found["trend_delta"] = float(forecast["trend"].iloc[-1] - forecast["trend"].iloc[0])
    for source, target in (("daily", "daily_span"), ("weekly", "weekly_span"), ("yearly", "yearly_span")):
        if source not in forecast.columns:
            continue
        span = float(forecast[source].max() - forecast[source].min())
        if abs(span) >= 1e-9:
            found[target] = span
    return found


def _fit(history: pd.DataFrame, horizon: int, frequency: str, seasonality: dict[str, object]) -> pd.DataFrame:
    from prophet import Prophet

    model = Prophet(interval_width=0.8, **seasonality)
    model.fit(history)
    future = model.make_future_dataframe(periods=horizon, freq=frequency, include_history=False)
    return model.predict(future)


def forecast_with_prophet(frame: pd.DataFrame, horizon: int, frequency: str) -> tuple[list[dict[str, object]], dict[str, float]]:
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
    logging.getLogger("prophet").setLevel(logging.WARNING)
    history = pd.DataFrame(
        {
            "ds": frame.index.tz_convert("UTC").tz_localize(None),
            "y": frame["value"].astype(float).to_numpy(),
        }
    )
    attempts = (
        {"daily_seasonality": "auto", "weekly_seasonality": "auto", "yearly_seasonality": "auto"},
        {"daily_seasonality": False, "weekly_seasonality": False, "yearly_seasonality": False},
    )
    last_error: Exception | None = None
    forecast: pd.DataFrame | None = None
    for seasonality in attempts:
        try:
            forecast = _fit(history, horizon, frequency, seasonality)
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Prophet не сошёлся с сезонностью %s: %s", seasonality, exc)
    if forecast is None:
        raise RuntimeError(f"Prophet не смог построить прогноз: {last_error}")

    points: list[dict[str, object]] = []
    for record in forecast.to_dict(orient="records"):
        value = float(record["yhat"])
        lower = float(record["yhat_lower"])
        upper = float(record["yhat_upper"])
        if not all(map(_finite, (value, lower, upper))):
            raise RuntimeError("Prophet вернул нечисловое значение")
        points.append(
            {
                "timestamp": to_iso8601(record["ds"]),
                "value": round(value, 6),
                "lower": round(lower, 6),
                "upper": round(upper, 6),
            }
        )
    if len(points) != horizon:
        raise RuntimeError(f"Prophet вернул {len(points)} точек вместо {horizon}")
    return points, _components(forecast)


def _finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}
