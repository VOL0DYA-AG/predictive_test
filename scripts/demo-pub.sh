#!/bin/sh
# Публикует examples/forecast_request.json от имени демо-клиента.
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
echo "Публикую examples/forecast_request.json в ${prefix}/${DEMO_CLIENT_USERNAME}/request"
docker compose exec -T mosquitto mosquitto_pub \
    -h 127.0.0.1 \
    -p 1883 \
    -u "$DEMO_CLIENT_USERNAME" \
    -P "$DEMO_CLIENT_PASSWORD" \
    -t "${prefix}/${DEMO_CLIENT_USERNAME}/request" \
    -q "${MQTT_QOS:-1}" \
    -s < examples/forecast_request.json
echo "Сообщение отправлено. Ответ смотрите в scripts/demo-sub.sh."
