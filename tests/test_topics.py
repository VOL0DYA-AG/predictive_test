from app.topics import username_from_request_topic


def test_username_from_request_topic():
    assert username_from_request_topic("forecast/v1/demo-scada/request", "forecast/v1") == "demo-scada"
    assert username_from_request_topic("forecast/v1/demo-scada/response", "forecast/v1") is None
    assert username_from_request_topic("other/v1/demo-scada/request", "forecast/v1") is None
    assert username_from_request_topic("forecast/v1/+/request", "forecast/v1") is None
