#!/bin/sh
# Собирает /mosquitto/passwd/passwd из переменных окружения и /clients.extra.
# Запускается от root при каждом старте контейнера брокера и заменяет файл целиком.
set -eu

PASSWD_DIR=/mosquitto/passwd
PASSWD_FILE="$PASSWD_DIR/passwd"
TMP_FILE="$PASSWD_DIR/passwd.tmp"
EXTRA_FILE=/clients.extra

die() {
    echo "mosquitto-init: $*" >&2
    exit 1
}

valid_user() {
    case "$1" in
        ""|*[!A-Za-z0-9_.-]*) return 1 ;;
    esac
    return 0
}

valid_pass() {
    case "$1" in
        ""|*[!A-Za-z0-9_./+=@%-]*) return 1 ;;
    esac
    return 0
}

add_user() {
    user="$1"
    pass="$2"
    valid_user "$user" || die "недопустимое имя '$user'. Разрешены A-Z a-z 0-9 _ . -"
    valid_pass "$pass" || die "пароль пользователя $user содержит неподдерживаемый символ. Разрешены A-Z a-z 0-9 _ . / + = @ % -"
    if [ ! -f "$TMP_FILE" ]; then
        mosquitto_passwd -c -b "$TMP_FILE" "$user" "$pass"
    else
        mosquitto_passwd -b "$TMP_FILE" "$user" "$pass"
    fi
    echo "mosquitto-init: пользователь $user записан"
}

mkdir -p "$PASSWD_DIR"
rm -f "$TMP_FILE"

[ -n "${MQTT_WORKER_USERNAME:-}" ] || die "не задан MQTT_WORKER_USERNAME"
TOPIC_PREFIX="${MQTT_TOPIC_PREFIX:-forecast/v1}"
ACL_FILE=/mosquitto/config/acl
if [ ! -f "$ACL_FILE" ]; then
    die "не найден $ACL_FILE"
fi
grep -x -F -q "user ${MQTT_WORKER_USERNAME}" "$ACL_FILE" || die "в $ACL_FILE нет строки «user ${MQTT_WORKER_USERNAME}». Имя воркера в .env и в ACL должны совпадать."
grep -F -q -- "$TOPIC_PREFIX" "$ACL_FILE" || die "в $ACL_FILE нет префикса топиков «${TOPIC_PREFIX}». MQTT_TOPIC_PREFIX и ACL должны совпадать."
cp "$ACL_FILE" "$PASSWD_DIR/acl"
chown 1883:1883 "$PASSWD_DIR/acl"
chmod 600 "$PASSWD_DIR/acl"
[ -n "${MQTT_WORKER_PASSWORD:-}" ] || die "не задан MQTT_WORKER_PASSWORD"
add_user "$MQTT_WORKER_USERNAME" "$MQTT_WORKER_PASSWORD"

[ -n "${DEMO_CLIENT_USERNAME:-}" ] || die "не задан DEMO_CLIENT_USERNAME"
[ -n "${DEMO_CLIENT_PASSWORD:-}" ] || die "не задан DEMO_CLIENT_PASSWORD"
if [ "$DEMO_CLIENT_USERNAME" = "$MQTT_WORKER_USERNAME" ]; then
    die "DEMO_CLIENT_USERNAME не должен совпадать с MQTT_WORKER_USERNAME"
fi
add_user "$DEMO_CLIENT_USERNAME" "$DEMO_CLIENT_PASSWORD"

if [ -f "$EXTRA_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line=$(printf '%s' "$line" | tr -d '\r')
        case "$line" in
            ""|\#*) continue ;;
        esac
        user=${line%%:*}
        pass=${line#*:}
        if [ "$user" = "$line" ] || [ -z "$user" ] || [ -z "$pass" ]; then
            die "строка в clients.extra должна иметь вид username:password"
        fi
        add_user "$user" "$pass"
    done < "$EXTRA_FILE"
fi

chown 1883:1883 "$PASSWD_DIR" "$TMP_FILE"
chmod 700 "$PASSWD_DIR"
chmod 600 "$TMP_FILE"
mv -f "$TMP_FILE" "$PASSWD_FILE"
chown 1883:1883 "$PASSWD_FILE"
chmod 600 "$PASSWD_FILE"
echo "mosquitto-init: файл паролей собран"
