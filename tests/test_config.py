import pytest

from app.config import Settings

_NAMES = [
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_WORKER_USERNAME",
    "MQTT_WORKER_PASSWORD",
    "MQTT_CLIENT_ID",
    "MQTT_QOS",
    "MQTT_KEEPALIVE",
    "MQTT_TOPIC_PREFIX",
    "CHRONOS_MODEL",
    "CHRONOS_DEVICE",
    "CHRONOS_PRELOAD",
    "HF_HOME",
    "MAX_SERIES",
    "MAX_POINTS",
    "MAX_HORIZON",
    "MIN_POINTS",
    "QUEUE_SIZE",
    "LOG_LEVEL",
]


@pytest.fixture
def clean_env(monkeypatch):
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_password_is_required(clean_env):
    with pytest.raises(ValueError, match="MQTT_WORKER_PASSWORD"):
        Settings.from_env()


def test_reads_limits_and_topics(clean_env):
    clean_env.setenv("MQTT_WORKER_PASSWORD", "secret")
    clean_env.setenv("MQTT_TOPIC_PREFIX", "/forecast/v1/")
    clean_env.setenv("MAX_HORIZON", "48")
    clean_env.setenv("CHRONOS_PRELOAD", "false")
    clean_env.setenv("CHRONOS_DEVICE", "CPU")
    settings = Settings.from_env()
    assert settings.topic_prefix == "forecast/v1"
    assert settings.request_filter == "forecast/v1/+/request"
    assert settings.response_topic("plant-1") == "forecast/v1/plant-1/response"
    assert settings.max_horizon == 48
    assert settings.chronos_preload is False
    assert settings.chronos_device == "cpu"


def test_rejects_bad_qos(clean_env):
    clean_env.setenv("MQTT_WORKER_PASSWORD", "secret")
    clean_env.setenv("MQTT_QOS", "9")
    with pytest.raises(ValueError, match="MQTT_QOS"):
        Settings.from_env()
