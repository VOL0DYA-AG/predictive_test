"""Разбор MQTT-топика запроса."""

from __future__ import annotations


def username_from_request_topic(topic: str, prefix: str) -> str | None:
    head = [part for part in prefix.strip("/").split("/") if part]
    parts = topic.split("/")
    if parts[: len(head)] != head:
        return None
    rest = parts[len(head) :]
    if len(rest) != 2 or rest[1] != "request":
        return None
    username = rest[0]
    if not username or username in {"+", "#"} or "/" in username:
        return None
    return username
