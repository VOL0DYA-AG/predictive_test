#!/bin/sh
# Добавляет MQTT-клиента в deploy/mosquitto/clients.extra и перезапускает брокер.
# Использование: scripts/register-client.sh USERNAME PASSWORD
set -eu
if [ "$#" -ne 2 ]; then
    echo "Использование: scripts/register-client.sh USERNAME PASSWORD" >&2
    exit 1
fi
user="$1"
pass="$2"
case "$user" in
    ""|*[!A-Za-z0-9_.-]*)
        echo "Недопустимое имя. Разрешены A-Z a-z 0-9 _ . -" >&2
        exit 1
        ;;
esac
case "$pass" in
    ""|*[!A-Za-z0-9_./+=@%-]*)
        echo "Недопустимый пароль. Разрешены A-Z a-z 0-9 _ . / + = @ % -" >&2
        exit 1
        ;;
esac

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
file="$root/deploy/mosquitto/clients.extra"
env_file="$root/.env"
if [ -f "$env_file" ]; then
    worker=$(sed -n 's/^MQTT_WORKER_USERNAME=//p' "$env_file" | tail -n 1)
    if [ -n "$worker" ] && [ "$user" = "$worker" ]; then
        echo "Имя $user занято воркером прогноза. Пароль воркера меняется в .env." >&2
        exit 1
    fi
fi

tmp=$(mktemp)
if [ -f "$file" ]; then
    awk -F: -v name="$user" 'NF == 0 || $1 != name { print }' "$file" > "$tmp"
else
    : > "$tmp"
fi
printf '%s:%s\n' "$user" "$pass" >> "$tmp"
mv "$tmp" "$file"

cd "$root"
docker compose up -d --wait --force-recreate --no-deps mosquitto
prefix=forecast/v1
if [ -f "$env_file" ]; then
    found=$(sed -n 's/^MQTT_TOPIC_PREFIX=//p' "$env_file" | tail -n 1 || true)
    if [ -n "$found" ]; then
        prefix=$found
    fi
fi
echo "Клиент $user записан, контейнер брокера пересоздан."
echo "Топик запроса: ${prefix}/${user}/request"
echo "Топик ответа:  ${prefix}/${user}/response"
