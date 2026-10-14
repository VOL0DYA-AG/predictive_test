#!/bin/sh
# Пересобирает файл паролей из .env и clients.extra. Нужен после правки этих файлов.
set -eu
cd "$(dirname "$0")/.."
docker compose up -d --wait --force-recreate --no-deps mosquitto
docker compose up -d --force-recreate --no-deps forecast
echo "Брокер и воркер пересозданы. Пароли взяты из текущего .env и clients.extra."
echo "Клиентам SCADA нужно переподключиться. Том mosquitto-data с очередью QoS 1 сохранён."
