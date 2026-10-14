"""Zero-shot прогноз Chronos-2. Модель одна на процесс."""

from __future__ import annotations

import logging
import threading
from typing import Any

import pandas as pd

from app.config import Settings
from app.series import to_iso8601

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pipeline: Any = None
_error: str | None = None


def reset_chronos_state() -> None:
    """Сбросить кэш. Нужно тестам, в рабочем процессе не вызывается."""
    global _pipeline, _error
    with _lock:
        _pipeline = None
        _error = None


def get_pipeline(settings: Settings) -> Any:
    global _pipeline, _error
    with _lock:
        if _pipeline is not None:
            return _pipeline
        if _error is not None:
            raise RuntimeError(_error)
        try:
            from chronos import Chronos2Pipeline

            logger.info("Загрузка %s, устройство %s", settings.chronos_model, settings.chronos_device)
            _pipeline = Chronos2Pipeline.from_pretrained(
                settings.chronos_model,
                device_map=settings.chronos_device,
            )
            logger.info("Модель %s загружена", settings.chronos_model)
            return _pipeline
        except Exception as exc:
            _error = f"Chronos-2 не загрузилась: {exc}"
            logger.exception(_error)
            raise RuntimeError(_error) from exc


def preload_chronos(settings: Settings) -> None:
    try:
        get_pipeline(settings)
    except Exception:
        logger.exception("Фоновая загрузка Chronos-2 не удалась. Запросы prophet продолжат работать.")


def forecast_with_chronos(
    frame: pd.DataFrame,
    series_id: str,
    horizon: int,
    frequency: str,
    settings: Settings,
) -> tuple[list[dict[str, object]], dict[str, float]]:
    pipeline = get_pipeline(settings)
    context = pd.DataFrame(
        {
            "id": series_id,
            "timestamp": frame.index.tz_convert("UTC").tz_localize(None),
            "target": frame["value"].astype(float).to_numpy(),
        }
    )
    predicted = pipeline.predict_df(
        context,
        prediction_length=horizon,
        quantile_levels=[0.1, 0.5, 0.9],
        id_column="id",
        timestamp_column="timestamp",
        target="target",
        freq=frequency,
    )
    columns = set(predicted.columns)
    for required in ("timestamp", "0.1", "0.5", "0.9"):
        if required not in columns and not (required == "0.5" and "predictions" in columns):
            raise RuntimeError(f"Ответ Chronos-2 не содержит столбец {required}. Столбцы: {sorted(columns)}")

    points: list[dict[str, object]] = []
    for record in predicted.to_dict(orient="records"):
        median = record["0.5"] if "0.5" in record else record["predictions"]
        value = float(median)
        lower = float(record["0.1"])
        upper = float(record["0.9"])
        if not all(item == item and item not in {float("inf"), float("-inf")} for item in (value, lower, upper)):
            raise RuntimeError("Chronos-2 вернула нечисловое значение")
        points.append(
            {
                "timestamp": to_iso8601(record["timestamp"]),
                "value": round(value, 6),
                "lower": round(lower, 6),
                "upper": round(upper, 6),
            }
        )
    if len(points) != horizon:
        raise RuntimeError(f"Chronos-2 вернула {len(points)} точек вместо {horizon}")
    return points, {}
