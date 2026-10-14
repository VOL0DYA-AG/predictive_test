"""Настройки воркера из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _text(name: str, default: str | None = None) -> str:
    value = _raw(name)
    if value is None:
        if default is None:
            raise ValueError(f"Не задана переменная {name}")
        return default
    return value


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = _raw(name)
    if value is None:
        number = default
    else:
        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError(f"{name} должна быть целым числом, получено «{value}»") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} должна быть от {minimum} до {maximum}, получено {number}")
    return number


def _boolean(name: str, default: bool) -> bool:
    value = _raw(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} должна быть true или false, получено «{value}»")


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_username: str = "forecast-worker"
    mqtt_password: str = "change-me-worker"
    mqtt_client_id: str = "forecast-worker"
    mqtt_qos: int = 1
    mqtt_keepalive: int = 60
    topic_prefix: str = "forecast/v1"
    chronos_model: str = "amazon/chronos-2"
    chronos_device: str = "cpu"
    chronos_preload: bool = True
    hf_home: str = "/opt/hf"
    max_series: int = 8
    max_points: int = 5000
    max_horizon: int = 512
    min_points: int = 10
    queue_size: int = 8
    log_level: str = "INFO"

    @property
    def request_filter(self) -> str:
        return f"{self.topic_prefix}/+/request"

    def response_topic(self, username: str) -> str:
        return f"{self.topic_prefix}/{username}/response"

    @classmethod
    def from_env(cls) -> Settings:
        username = _text("MQTT_WORKER_USERNAME", "forecast-worker")
        topic_prefix = _text("MQTT_TOPIC_PREFIX", "forecast/v1").strip("/")
        if not topic_prefix or "+" in topic_prefix or "#" in topic_prefix:
            raise ValueError("MQTT_TOPIC_PREFIX не должен быть пустым и не должен содержать + или #")
        device = _text("CHRONOS_DEVICE", "cpu").lower()
        if device not in {"cpu", "cuda"}:
            raise ValueError("CHRONOS_DEVICE должна быть cpu или cuda")
        log_level = _text("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL должна быть DEBUG, INFO, WARNING, ERROR или CRITICAL")
        min_points = _integer("MIN_POINTS", 10, minimum=2, maximum=100_000)
        max_points = _integer("MAX_POINTS", 5000, minimum=min_points, maximum=1_000_000)
        return cls(
            mqtt_host=_text("MQTT_HOST", "mosquitto"),
            mqtt_port=_integer("MQTT_PORT", 1883, minimum=1, maximum=65535),
            mqtt_username=username,
            mqtt_password=_text("MQTT_WORKER_PASSWORD"),
            mqtt_client_id=_text("MQTT_CLIENT_ID", username),
            mqtt_qos=_integer("MQTT_QOS", 1, minimum=0, maximum=2),
            mqtt_keepalive=_integer("MQTT_KEEPALIVE", 60, minimum=5, maximum=65535),
            topic_prefix=topic_prefix,
            chronos_model=_text("CHRONOS_MODEL", "amazon/chronos-2"),
            chronos_device=device,
            chronos_preload=_boolean("CHRONOS_PRELOAD", True),
            hf_home=_text("HF_HOME", "/opt/hf"),
            max_series=_integer("MAX_SERIES", 8, minimum=1, maximum=100),
            max_points=max_points,
            max_horizon=_integer("MAX_HORIZON", 512, minimum=1, maximum=10_000),
            min_points=min_points,
            queue_size=_integer("QUEUE_SIZE", 8, minimum=1, maximum=1000),
            log_level=log_level,
        )
