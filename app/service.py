"""Расчёт ответа на один JSON-запрос. От MQTT не зависит."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.forecasting.narrative import ExplainedSeries, classify_direction, summarize
from app.schemas import ForecastRequest, SeriesIn
from app.series import prepare_series

logger = logging.getLogger(__name__)

ProphetRunner = Callable[[Any, int, str], tuple[list[dict[str, Any]], dict[str, float]]]
ChronosRunner = Callable[[Any, str, int, str, Settings], tuple[list[dict[str, Any]], dict[str, float]]]


def error_body(request_id: str | None, client: str, message: str) -> dict[str, Any]:
    body: dict[str, Any] = {"client": client, "error": message}
    if request_id:
        body["request_id"] = request_id
    return body


def _format_validation(exc: ValidationError) -> str:
    parts = []
    for item in exc.errors():
        location = ".".join(str(piece) for piece in item["loc"]) or "запрос"
        parts.append(f"{location}: {item['msg']}")
    return "Запрос не прошёл проверку: " + "; ".join(parts)


def _enforce_limits(request: ForecastRequest, settings: Settings) -> None:
    if request.horizon > settings.max_horizon:
        raise ValueError(f"horizon {request.horizon} больше лимита {settings.max_horizon}")
    if len(request.series) > settings.max_series:
        raise ValueError(f"В запросе {len(request.series)} рядов, лимит {settings.max_series}")
    seen: set[str] = set()
    for series in request.series:
        if series.id in seen:
            raise ValueError(f"Идентификатор ряда {series.id} повторяется в одном запросе")
        seen.add(series.id)
        count = len(series.points)
        if count < settings.min_points:
            raise ValueError(f"Ряд {series.id}: нужно минимум {settings.min_points} точек, получено {count}")
        if count > settings.max_points:
            raise ValueError(f"Ряд {series.id}: {count} точек, лимит {settings.max_points}")


def _default_prophet(frame: Any, horizon: int, frequency: str) -> tuple[list[dict[str, Any]], dict[str, float]]:
    from app.forecasting.prophet_model import forecast_with_prophet

    return forecast_with_prophet(frame, horizon, frequency)


def _default_chronos(
    frame: Any,
    series_id: str,
    horizon: int,
    frequency: str,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    from app.forecasting.chronos_model import forecast_with_chronos

    return forecast_with_chronos(frame, series_id, horizon, frequency, settings)


def _mean_width(points: list[dict[str, Any]]) -> float:
    widths = [float(point["upper"]) - float(point["lower"]) for point in points]
    return sum(widths) / len(widths)


def _run_model(
    model_name: str,
    prepared: list[tuple[SeriesIn, Any, str]],
    request: ForecastRequest,
    settings: Settings,
    prophet_runner: ProphetRunner,
    chronos_runner: ChronosRunner,
) -> tuple[list[ExplainedSeries], list[dict[str, Any]]]:
    explained: list[ExplainedSeries] = []
    series_payload: list[dict[str, Any]] = []
    for series, frame, frequency in prepared:
        if model_name == "prophet":
            points, components = prophet_runner(frame, request.horizon, frequency)
        else:
            points, components = chronos_runner(frame, series.id, request.horizon, frequency, settings)
        if len(points) != request.horizon:
            raise RuntimeError(f"{model_name} вернула {len(points)} точек вместо {request.horizon}")
        last_value = float(frame["value"].iloc[-1])
        end_value = float(points[-1]["value"])
        item = ExplainedSeries(
            model=model_name,
            series_id=series.id,
            metric=series.metric,
            unit=series.unit,
            direction=classify_direction(last_value, end_value),
            last_value=last_value,
            end_value=end_value,
            mean_width=_mean_width(points),
            components=components,
            history_points=int(len(frame)),
        )
        explained.append(item)
        series_payload.append(
            {
                "id": series.id,
                "metric": series.metric,
                "unit": series.unit,
                "frequency": frequency,
                "direction": item.direction,
                "points": points,
            }
        )
    return explained, series_payload


def handle_request(
    raw: bytes,
    client: str,
    settings: Settings,
    *,
    prophet_runner: ProphetRunner | None = None,
    chronos_runner: ChronosRunner | None = None,
) -> dict[str, Any]:
    prophet_runner = prophet_runner or _default_prophet
    chronos_runner = chronos_runner or _default_chronos
    request_id: str | None = None
    try:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return error_body(None, client, "Тело сообщения не является JSON в кодировке UTF-8")
        if not isinstance(payload, dict):
            return error_body(None, client, "JSON должен быть объектом")
        incoming_id = payload.get("request_id")
        request_id = incoming_id.strip() if isinstance(incoming_id, str) else None
        request = ForecastRequest.model_validate(payload)
        if request.request_id is None:
            request = request.model_copy(update={"request_id": uuid.uuid4().hex[:12]})
        request_id = request.request_id
        _enforce_limits(request, settings)

        prepared: list[tuple[SeriesIn, Any, str]] = []
        for series in request.series:
            frame, frequency = prepare_series(
                series,
                request.frequency,
                max_points=settings.max_points,
                min_points=settings.min_points,
            )
            prepared.append((series, frame, frequency))
        frequencies = {frequency for _, _, frequency in prepared}
        models = ["prophet", "chronos-2"] if request.model == "both" else [request.model]

        started = time.perf_counter()
        blocks: list[dict[str, Any]] = []
        explained: list[ExplainedSeries] = []
        warnings: list[str] = []
        for model_name in models:
            try:
                model_items, series_payload = _run_model(
                    model_name,
                    prepared,
                    request,
                    settings,
                    prophet_runner,
                    chronos_runner,
                )
            except Exception as exc:
                logger.exception("Модель %s не посчитала запрос %s", model_name, request_id)
                if request.model != "both":
                    raise
                warnings.append(f"Модель {model_name} не посчиталась: {exc}")
                continue
            explained.extend(model_items)
            blocks.append({"model": model_name, "series": series_payload})

        if not blocks:
            detail = "; ".join(warnings) if warnings else "ни одна модель не вернула прогноз"
            return error_body(request_id, client, detail)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "request_id": request_id,
            "client": client,
            "model": request.model,
            "frequency": frequencies.pop() if len(frequencies) == 1 else "mixed",
            "horizon": request.horizon,
            "forecasts": blocks,
            "summary": summarize(explained, warnings),
            "warnings": warnings,
            "elapsed_ms": elapsed_ms,
        }
    except ValidationError as exc:
        return error_body(request_id, client, _format_validation(exc))
    except (ValueError, RuntimeError) as exc:
        return error_body(request_id, client, str(exc))
    except Exception:
        logger.exception("Неожиданная ошибка расчёта, клиент %s, запрос %s", client, request_id)
        return error_body(request_id, client, "Внутренняя ошибка расчёта")
