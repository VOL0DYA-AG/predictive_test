#!/bin/sh
# Подписка на ответы демо-клиента. Запускайте это раньше, чем demo-pub.sh.
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
    echo "Нет файла .env. Скопируйте .env.example в .env и задайте пароли." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a
prefix="${MQTT_TOPIC_PREFIX:-forecast/v1}"
echo "Жду сообщения в ${prefix}/${DEMO_CLIENT_USERNAME}/response"
echo "Остановка: Ctrl+C"
exec docker compose exec mosquitto mosquitto_sub \
    -h 127.0.0.1 \
    -p 1883 \
    -u "$DEMO_CLIENT_USERNAME" \
    -P "$DEMO_CLIENT_PASSWORD" \
    -t "${prefix}/${DEMO_CLIENT_USERNAME}/response" \
    -q "${MQTT_QOS:-1}" \
    -v
