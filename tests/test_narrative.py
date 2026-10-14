from app.forecasting.narrative import ExplainedSeries, classify_direction, summarize


def _item(model: str, direction_end: float, **overrides) -> ExplainedSeries:
    data = dict(
        model=model,
        series_id="temp-01",
        metric="temperature",
        unit="C",
        direction="up",
        last_value=10.0,
        end_value=direction_end,
        mean_width=1.0,
        components={"trend_delta": 1.5, "daily_span": 0.4} if model == "prophet" else {},
        history_points=72,
    )
    data.update(overrides)
    data["direction"] = classify_direction(data["last_value"], data["end_value"])
    return ExplainedSeries(**data)


def test_classify_direction_thresholds():
    assert classify_direction(10, 12) == "up"
    assert classify_direction(10, 8) == "down"
    assert classify_direction(10, 10.1) == "flat"


def test_prophet_sentence_uses_components():
    text = _item("prophet", 12).sentence()
    assert "Модель Prophet, temperature (ряд temp-01, C)" in text
    assert "медиана 12 при последнем значении 10, изменение +2 (+20.0%)" in text
    assert "Направление: вверх." in text
    assert "уверенность средняя." in text
    assert "центральный интервал 80%" in text
    assert "Тренд за горизонт +1.5." in text
    assert "Размах суточной сезонности 0.4." in text


def test_chronos_sentence_does_not_invent_seasonality():
    text = _item("chronos-2", 12).sentence()
    assert "квантилям 0.1 и 0.9" in text
    assert "Тренд за горизонт" not in text


def test_models_agree_and_disagree():
    agreed = summarize([_item("prophet", 12), _item("chronos-2", 13)])
    assert agreed["direction"] == "up"
    assert agreed["text"].startswith("Prophet и Chronos-2 совпадают по направлению: вверх.")
    assert "не причинная диагностика оборудования" in agreed["text"]

    split = summarize([_item("prophet", 12), _item("chronos-2", 8)])
    assert split["direction"] == "mixed"
    assert "расходятся по направлению" in split["text"]


def test_short_history_warning():
    summary = summarize([_item("prophet", 12, history_points=12)])
    assert "короче 48 точек" in summary["text"]
