"""Проверка JSON-запроса на прогноз."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PointIn(BaseModel):
    timestamp: datetime
    value: float

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value должно быть конечным числом")
        return float(value)


class SeriesIn(BaseModel):
    id: str
    metric: str = ""
    unit: str = ""
    points: list[PointIn] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def clean_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "/" in cleaned or "+" in cleaned or "#" in cleaned:
            raise ValueError("id ряда не должен быть пустым и не должен содержать / + #")
        return cleaned

    @field_validator("metric", "unit")
    @classmethod
    def clean_label(cls, value: str) -> str:
        return value.strip()


class ForecastRequest(BaseModel):
    request_id: str | None = None
    model: Literal["prophet", "chronos-2", "both"] = "both"
    horizon: int = 24
    frequency: str | None = None
    series: list[SeriesIn] = Field(min_length=1)

    @field_validator("request_id")
    @classmethod
    def clean_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("horizon")
    @classmethod
    def positive_horizon(cls, value: int) -> int:
        if value < 1:
            raise ValueError("horizon должен быть не меньше 1")
        return value

    @field_validator("frequency", mode="before")
    @classmethod
    def empty_frequency(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value
