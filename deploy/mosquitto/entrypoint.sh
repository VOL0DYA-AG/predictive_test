#!/bin/sh
# Перед брокером заново собирает файл паролей, затем отдаёт управление
# штатному entrypoint образа eclipse-mosquitto.
set -eu
/bin/sh /opt/init-passwd.sh
if [ "$#" -eq 0 ]; then
    set -- /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
fi
exec /docker-entrypoint.sh "$@"
