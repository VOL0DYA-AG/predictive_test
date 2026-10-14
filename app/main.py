"""MQTT-воркер: читает запросы и публикует прогноз."""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import sys
import threading
from pathlib import Path

from app.config import Settings
from app.service import error_body, handle_request
from app.topics import username_from_request_topic

logger = logging.getLogger("forecast")
HEALTH_FILE = Path("/tmp/forecast-healthy")
_CONNECT_HINTS = {
    1: "неверная версия протокола",
    2: "идентификатор клиента отклонён",
    3: "брокер недоступен",
    4: "неверный логин или пароль воркера",
    5: "воркер не авторизован, проверьте ACL и имя MQTT_WORKER_USERNAME",
}


def _mark_healthy(connected: bool) -> None:
    if connected:
        HEALTH_FILE.write_text("ok\n", encoding="utf-8")
    else:
        HEALTH_FILE.unlink(missing_ok=True)


def _dump(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, indent=2)


def serve(settings: Settings) -> None:
    import paho.mqtt.client as mqtt

    os.environ["HF_HOME"] = settings.hf_home
    os.environ.setdefault("MPLBACKEND", "Agg")
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    if settings.chronos_preload:
        from app.forecasting.chronos_model import preload_chronos

        threading.Thread(
            target=preload_chronos,
            args=(settings,),
            name="chronos-preload",
            daemon=True,
        ).start()

    jobs: queue.Queue[tuple[str, bytes] | None] = queue.Queue(maxsize=settings.queue_size)
    stop = threading.Event()

    def publish(client: mqtt.Client, topic: str, body: dict, *, wait: bool) -> None:
        payload = _dump(body)
        message = client.publish(topic, payload, qos=settings.mqtt_qos, retain=False)
        if not wait:
            return
        message.wait_for_publish(timeout=30)
        if message.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Не удалось опубликовать ответ в %s, код %s", topic, message.rc)

    def worker(client: mqtt.Client) -> None:
        while True:
            job = jobs.get()
            try:
                if job is None:
                    return
                topic, payload = job
                username = username_from_request_topic(topic, settings.topic_prefix)
                if username is None:
                    logger.warning("Пропущено сообщение вне топика запроса: %s", topic)
                    continue
                logger.info("Запрос от %s, %s байт", username, len(payload))
                body = handle_request(payload, username, settings)
                publish(client, settings.response_topic(username), body, wait=True)
                if "error" in body:
                    logger.warning("Ответ с ошибкой для %s: %s", username, body["error"])
                else:
                    logger.info(
                        "Ответ для %s, request_id=%s, %s мс",
                        username,
                        body.get("request_id"),
                        body.get("elapsed_ms"),
                    )
            except Exception:
                logger.exception("Сбой обработки сообщения")
            finally:
                jobs.task_done()

    def on_connect(client: mqtt.Client, userdata: object, flags: dict, rc: int) -> None:
        del userdata, flags
        if rc != 0:
            _mark_healthy(False)
            logger.error("MQTT отказ в подключении, код %s (%s)", rc, _CONNECT_HINTS.get(rc, "неизвестная причина"))
            return
        client.subscribe(settings.request_filter, qos=settings.mqtt_qos)
        _mark_healthy(True)
        logger.info("Подключено к %s:%s, подписка %s", settings.mqtt_host, settings.mqtt_port, settings.request_filter)

    def on_disconnect(client: mqtt.Client, userdata: object, rc: int) -> None:
        del client, userdata
        _mark_healthy(False)
        if rc != 0:
            logger.warning("Соединение с брокером прервалось, код %s. Клиент переподключится.", rc)

    def on_message(client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
        del userdata
        try:
            jobs.put_nowait((message.topic, bytes(message.payload)))
        except queue.Full:
            username = username_from_request_topic(message.topic, settings.topic_prefix) or settings.mqtt_username
            logger.error("Очередь заполнена, запрос %s отклонён", message.topic)
            try:
                publish(
                    client,
                    settings.response_topic(username),
                    error_body(None, username, "Очередь расчёта заполнена, повторите запрос"),
                    wait=False,
                )
            except Exception:
                logger.exception("Не удалось опубликовать отказ из-за полной очереди")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        client_id=settings.mqtt_client_id,
        clean_session=False,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    thread = threading.Thread(target=worker, args=(client,), name="forecast-jobs", daemon=False)
    thread.start()

    def request_stop(signum: int, frame: object) -> None:
        del frame
        logger.info("Сигнал %s, останавливаюсь", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    while not stop.is_set():
        try:
            client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive)
            client.loop_start()
            break
        except Exception:
            logger.exception("Нет соединения с брокером %s:%s, повтор через 5 с", settings.mqtt_host, settings.mqtt_port)
            stop.wait(5)

    if not stop.is_set():
        stop.wait()
    client.disconnect()
    client.loop_stop()
    jobs.put(None)
    thread.join(timeout=150)
    _mark_healthy(False)


def main() -> None:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Воркер прогноза запускается, модель по умолчанию в запросе задаёт клиент")
    serve(settings)


if __name__ == "__main__":
    main()
