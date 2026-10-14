"""Русский текст по числам прогноза, без внешней языковой модели."""

from __future__ import annotations

from dataclasses import dataclass


DIRECTION_WORDS = {
    "up": "вверх",
    "down": "вниз",
    "flat": "без выраженного наклона",
}
MODEL_TITLES = {
    "prophet": "Prophet",
    "chronos-2": "Chronos-2",
}
_COMPONENT_LABELS = (
    ("trend_delta", "Тренд за горизонт", True),
    ("daily_span", "Размах суточной сезонности", False),
    ("weekly_span", "Размах недельной сезонности", False),
    ("yearly_span", "Размах годовой сезонности", False),
)


def format_number(value: float) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def format_signed(value: float) -> str:
    text = format_number(value)
    if text.startswith("-"):
        return text
    return f"+{text}"


def classify_direction(last_value: float, end_value: float, *, flat_ratio: float = 0.02) -> str:
    delta = end_value - last_value
    base = max(abs(last_value), 1.0)
    if abs(delta) / base < flat_ratio:
        return "flat"
    return "up" if delta > 0 else "down"


def confidence_label(mean_width: float, last_value: float) -> str:
    base = max(abs(last_value), 1.0)
    relative = mean_width / base
    if relative < 0.05:
        return "высокая"
    if relative < 0.20:
        return "средняя"
    return "низкая"


def _series_label(series_id: str, metric: str, unit: str) -> str:
    title = metric or series_id
    details: list[str] = []
    if metric:
        details.append(f"ряд {series_id}")
    if unit:
        details.append(unit)
    if not details:
        return title
    return f"{title} ({', '.join(details)})"


@dataclass(frozen=True)
class ExplainedSeries:
    model: str
    series_id: str
    metric: str
    unit: str
    direction: str
    last_value: float
    end_value: float
    mean_width: float
    components: dict[str, float]
    history_points: int

    def sentence(self) -> str:
        title = MODEL_TITLES.get(self.model, self.model)
        delta = self.end_value - self.last_value
        change = format_signed(delta)
        if self.last_value != 0:
            change += f" ({delta / self.last_value * 100:+.1f}%)"
        parts = [
            (
                f"Модель {title}, {_series_label(self.series_id, self.metric, self.unit)}: "
                f"к концу горизонта медиана {format_number(self.end_value)} "
                f"при последнем значении {format_number(self.last_value)}, изменение {change}."
            ),
            f"Направление: {DIRECTION_WORDS[self.direction]}.",
            (
                f"Средняя ширина интервала {format_number(self.mean_width)}, "
                f"уверенность {confidence_label(self.mean_width, self.last_value)}."
            ),
        ]
        if self.model == "prophet":
            parts.append("Границы — центральный интервал 80%.")
            for key, label, signed in _COMPONENT_LABELS:
                if key not in self.components:
                    continue
                rendered = format_signed(self.components[key]) if signed else format_number(self.components[key])
                parts.append(f"{label} {rendered}.")
        else:
            parts.append("Сезонность отдельно не выделяется: вывод сделан по медиане и квантилям 0.1 и 0.9.")
        return " ".join(parts)


def summarize(items: list[ExplainedSeries], warnings: list[str] | None = None) -> dict[str, str]:
    warnings = warnings or []
    directions = [item.direction for item in items]
    if not directions:
        direction = "flat"
    elif len(set(directions)) == 1:
        direction = directions[0]
    else:
        direction = "mixed"

    lines: list[str] = []
    by_model: dict[str, list[ExplainedSeries]] = {}
    for item in items:
        by_model.setdefault(item.model, []).append(item)

    if "prophet" in by_model and "chronos-2" in by_model:
        prophet_dirs = {item.direction for item in by_model["prophet"]}
        chronos_dirs = {item.direction for item in by_model["chronos-2"]}
        if len(prophet_dirs) == 1 and prophet_dirs == chronos_dirs:
            word = DIRECTION_WORDS[prophet_dirs.pop()]
            lines.append(f"Prophet и Chronos-2 совпадают по направлению: {word}.")
        else:
            lines.append("Prophet и Chronos-2 расходятся по направлению. Смотрите интервалы каждого прогноза.")

    for group in by_model.values():
        for item in group:
            lines.append(item.sentence())

    if any(item.history_points < 48 for item in items):
        lines.append("История короче 48 точек, сезонные выводы ориентировочные.")
    for warning in warnings:
        lines.append(warning)
    lines.append("Текст собран по форме прогноза и компонентам модели, это не причинная диагностика оборудования.")
    return {"direction": direction, "text": "\n".join(lines)}
