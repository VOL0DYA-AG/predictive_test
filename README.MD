# Пилот предиктивной аналитики временных рядов

Сервис принимает историю измерений от зарегистрированного контура IoT или SCADA по MQTT и отвечает прогнозом. В ответе числовой ряд и короткий русский текст: куда, скорее всего, пойдёт график и на каких цифрах это основано.

Внутри две модели:

- **Prophet** (Facebook) обучается на конкретном запросе. От неё есть тренд и, когда истории хватает, сезонность. Границы прогноза — центральный интервал 80%.
- **Chronos-2** (`amazon/chronos-2`, пакет `chronos-forecasting`) — готовая модель на 120 млн параметров. Она не дообучается на запросе и сразу отдаёт квантили 0.1, 0.5 и 0.9.

Текст собирается правилами из этих чисел. Отдельной языковой модели нет: формулировка повторяема и не требует внешнего API. Это чтение формы прогноза, а не причинная диагностика оборудования.

Обмен только через MQTT. HTTP-порта у сервиса нет.

## Последовательный запуск на Ubuntu

Ниже путь с чистого сервера Ubuntu 22.04 или 24.04 до первого ответа. Команды рассчитаны на пользователя с `sudo`. Дальше везде предполагается, что текущий каталог — корень этого репозитория.

Нужно примерно 8 ГБ RAM, 20 ГБ свободного диска и исходящий HTTPS: при сборке образа качаются PyTorch, Prophet и CmdStan, при первом запуске Chronos-2 качает веса с Hugging Face. Первая сборка долгая, часто 15–40 минут, потому что CmdStan компилируется.

### 1. Установить Docker Engine и Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Выйдите из SSH и зайдите снова, чтобы группа `docker` применилась. Проверка:

```bash
docker compose version
```

Должна быть команда `docker compose`, не отдельный пакет `docker-compose` v1.

### 2. Получить код

```bash
git clone <адрес-этого-репозитория> forecast
cd forecast
```

### 3. Задать пароли

```bash
cp .env.example .env
nano .env
```

Замените `change-me-worker` и `change-me-demo` на свои пароли. Пока в файле остаются эти заглушки, сервис тоже запустится, но пароли уже есть в репозитории и не годятся для машины, доступной из сети.

Имена и пароли пишутся без кавычек и без пробелов. Разрешены буквы, цифры и символы `_ . / + = @ % -`. Символы `$`, кавычки, пробел и обратный слэш нельзя: healthcheck брокера передаёт пароль в командную строку.

`DEMO_CLIENT_USERNAME` не должен совпадать с `MQTT_WORKER_USERNAME`.

Файл `.env` в git не попадает.

### 4. Собрать образ и запустить

```bash
docker compose up -d --build
```

Compose читает `.env` из текущего каталога сам. Сначала собирается образ `forecast`, затем стартует брокер, после его healthcheck — воркер.

Пока идёт сборка, смотреть журнал:

```bash
docker compose logs -f
```

Выход из просмотра журнала: `Ctrl+C`. Контейнеры при этом не останавливаются.

### 5. Проверить, что контейнеры живы

```bash
docker compose ps
```

У `mosquitto` и `forecast` в статусе должно быть `healthy`.

Брокер становится healthy, когда служебный пользователь смог подписаться на свой топик ответа. Воркер становится healthy, когда открыл соединение с брокером. Загрузка Chronos-2 к этой проверке не привязана и может ещё идти.

Дождитесь в журнале воркера строки `Модель amazon/chronos-2 загружена`:

```bash
docker compose logs -f forecast
```

Если Hugging Face недоступен, в журнале будет ошибка загрузки. Прогноз Prophet при этом работает: в JSON запроса поставьте `"model": "prophet"`.

### 6. Подписаться на ответ

В отдельном терминале, из корня репозитория:

```bash
./scripts/demo-sub.sh
```

Скрипт читает `.env` и подписывается на `forecast/v1/<DEMO_CLIENT_USERNAME>/response`. Окно нужно оставить открытым. Подписка должна быть раньше публикации: у демо-клиента обычная сессия, и ответ, пришедший в пустоту, никто не сохранит.

### 7. Отправить пример

В третьем терминале:

```bash
./scripts/demo-pub.sh
```

Скрипт публикует [examples/forecast_request.json](examples/forecast_request.json): 72 часовых точки температуры, горизонт 24 часа, обе модели. В первом терминале появится JSON с блоками `forecasts` и полем `summary.text`.

Первый расчёт Prophet дольше следующих: CmdStan компилирует модель. Chronos-2 на CPU тоже занимает заметное время.

Остановить подписку: `Ctrl+C` в терминале `demo-sub.sh`.

### 8. Остановить сервис

```bash
docker compose down
```

Тома с паролями, очередью брокера и весами Chronos-2 сохраняются. Следующий `docker compose up -d` поднимется без повторной загрузки весов.

`docker compose down -v` удаляет тома. После этого пароли соберутся заново из `.env`, а веса Chronos-2 скачаются ещё раз.

## Подключить свой контур

Имя MQTT-пользователя — это имя контура. Отдельного поля «клиент» в JSON нет: брокер пускает только тех, кто есть в файле паролей, а ACL пускает пользователя `plant-1` только в топики `forecast/v1/plant-1/...`.

1. Придумайте имя и пароль в тех же символах, что и для `.env`.
2. Выполните:

```bash
./scripts/register-client.sh plant-1 plant-secret-1
```

Кириллицу в пароль класть нельзя. Допустимы только буквы латиницы, цифры и символы `_ . / + = @ % -`.

Скрипт дописывает строку в [deploy/mosquitto/clients.extra](deploy/mosquitto/clients.extra) и пересоздаёт контейнер брокера. Воркер прогноза не пересобирается: веса остаются в памяти. Уже подключённые клиенты на время рестарта брокера отваливаются и должны переподключиться.

3. Контур подключается к `IP-сервера:1883` (порт — значение `MQTT_PUBLISH_PORT`).
4. Подписывается на `forecast/v1/plant-1/response` с QoS 1.
5. Публикует JSON в `forecast/v1/plant-1/request` с QoS 1.

Для промышленного клиента лучше постоянная сессия: фиксированный client id и clean session = false. Тогда брокер подержит ответ QoS 1, если контур на минуту отключился. Демо-скрипт так не делает, поэтому подписка в нём идёт раньше публикации.

Чужой топик брокер не доставляет. На MQTT 3.1.1 публикация в чужой топик часто выглядит успешной: подтверждение QoS есть, а подписчик сообщение не получает. Если ответа нет, сначала проверьте, что имя пользователя и уровень топика совпадают.

Повторять в `clients.extra` пользователей из `.env` не нужно. Если имя совпадёт, пароль из `clients.extra` победит: этот файл применяется после `.env`.

После ручной правки `clients.extra` или смены пароля в `.env`:

```bash
./scripts/reload-passwords.sh
```

Скрипт пересоздаёт и брокер, и воркер. Пересоздание воркера нужно, потому что Docker запоминает переменные окружения на момент создания контейнера: простой `restart` оставил бы старый пароль. Пока воркер стартует, Chronos-2 читается из тома, заново из сети она не качается.

Строка `user` в [deploy/mosquitto/acl](deploy/mosquitto/acl) должна совпадать с `MQTT_WORKER_USERNAME`, а префикс топиков в ACL — с `MQTT_TOPIC_PREFIX`. Иначе брокер не стартует и в журнале будет текст проверки.

## Формат сообщений

Запрос, топик `forecast/v1/<username>/request`:

```json
{
  "request_id": "demo-001",
  "model": "both",
  "horizon": 24,
  "frequency": "h",
  "series": [
    {
      "id": "temp-01",
      "metric": "temperature",
      "unit": "C",
      "points": [
        {"timestamp": "2026-10-11T00:00:00Z", "value": 20.0}
      ]
    }
  ]
}
```

| Поле | Смысл |
| --- | --- |
| `request_id` | Ваш идентификатор. Вернётся в ответе. Если поля нет, сервис сам поставит короткий id. |
| `model` | `prophet`, `chronos-2` или `both`. По умолчанию `both`. |
| `horizon` | Сколько шагов предсказать. По умолчанию 24. Потолок задаёт `MAX_HORIZON` (512). |
| `frequency` | Шаг pandas: `min`, `h`, `D`, `15min`, `1h`. Пустое поле — шаг оценивается по меткам. |
| `series` | От 1 до `MAX_SERIES` рядов. У каждого ряда свой `id`. |
| `series[].points` | История. Минимум `MIN_POINTS` (10), максимум `MAX_POINTS` (5000). |
| `metric`, `unit` | Подписи для текста. На расчёт не влияют. |

Метки времени — ISO-8601. Без часового пояса считаются UTC. Перед расчётом ряд выравнивается на регулярную сетку: повтор метки схлопывается (остаётся последнее значение), редкие пропуски заполняются линейно. Если между первой и последней точкой на заданном шаге получается больше `MAX_POINTS` значений, запрос отклоняется.

Ответ, топик `forecast/v1/<username>/response`. Сокращённый вид, в реальном ответе точек столько, сколько `horizon`:

```json
{
  "request_id": "demo-001",
  "client": "demo-scada",
  "model": "both",
  "frequency": "h",
  "horizon": 24,
  "forecasts": [
    {
      "model": "prophet",
      "series": [
        {
          "id": "temp-01",
          "metric": "temperature",
          "unit": "C",
          "frequency": "h",
          "direction": "up",
          "points": [
            {"timestamp": "2026-10-14T00:00:00Z", "value": 22.4, "lower": 21.1, "upper": 23.7}
          ]
        }
      ]
    }
  ],
  "summary": {
    "direction": "up",
    "text": "Prophet и Chronos-2 совпадают по направлению: вверх.\n..."
  },
  "warnings": [],
  "elapsed_ms": 1800
}
```

`value` — медиана (у Prophet это `yhat`). `lower` и `upper` — границы. `direction` у ряда и в сводке: `up`, `down`, `flat`. Если модели или ряды смотрят в разные стороны, у сводки `mixed`.

Направление `flat`, если конец горизонта отличается от последней исторической точки меньше чем на 2% (для значений около нуля порог считается от единицы). Уверенность в тексте: высокая, если средняя ширина интервала меньше 5% от последнего значения, средняя до 20%, иначе низкая.

При `"model": "both"`, если одна модель упала, а вторая посчиталась, ответ успешный, причина лежит в `warnings` и в конце `summary.text`. Если не посчиталась ни одна, или запрошена была только одна и она упала, вместо прогноза приходит:

```json
{
  "request_id": "demo-001",
  "client": "demo-scada",
  "error": "текст причины"
}
```

Воркер считает один запрос за раз. Следующие ждут в очереди длиной `QUEUE_SIZE`. Если очередь полна, в ответ уходит ошибка «Очередь расчёта заполнена».

Пакет целиком, вместе со служебным заголовком MQTT, не может быть больше 10 МиБ (`max_packet_size`).

## Что означает текст

Абзац Prophet использует тренд и размах суточной, недельной или годовой сезонности, если модель их выделила. Если сезонность на коротком ряду не сошлась, Prophet пересчитывается без неё, и этих фраз в тексте не будет.

Абзац Chronos-2 прямо говорит, что сезонность отдельно не выделялась: вывод сделан по медиане и квантилям 0.1 и 0.9.

Последняя фраза всегда одна и та же: текст собран по форме прогноза, это не причинная диагностика оборудования. Если в истории меньше 48 точек, добавляется оговорка, что сезонные выводы ориентировочные.

## Переменные окружения

Файл-образец — [.env.example](.env.example). Compose подставляет его и в конфигурацию запуска, и внутрь контейнеров через `env_file`.

Исключение — адрес брокера для воркера. В `docker-compose.yml` у сервиса `forecast` жестко заданы `MQTT_HOST=mosquitto` и `MQTT_PORT=1883`. Это имя и порт внутри сети Compose. Менять их в `.env` бесполезно: секция `environment` их перекрывает. Снаружи сервер слушает `MQTT_PUBLISH_PORT`.

| Переменная | Где действует | За что отвечает |
| --- | --- | --- |
| `MQTT_PUBLISH_PORT` | только проброс порта на хост | Какой порт Ubuntu открыт снаружи. Внутри контейнера брокер всегда на 1883. По умолчанию 1883. |
| `MQTT_WORKER_USERNAME` | брокер и воркер | Логин, под которым воркер ходит в MQTT. Должен совпасть со строкой `user` в ACL. По умолчанию `forecast-worker`. Это не логин SCADA. |
| `MQTT_WORKER_PASSWORD` | брокер и воркер | Пароль воркера. Обязателен. В брокер попадает только хеш. |
| `DEMO_CLIENT_USERNAME` | брокер и скрипты демо | Логин для `demo-sub.sh` / `demo-pub.sh`. По умолчанию `demo-scada`. |
| `DEMO_CLIENT_PASSWORD` | брокер и скрипты демо | Пароль демо-клиента. Обязателен. |
| `MQTT_CLIENT_ID` | воркер | Постоянный идентификатор сессии воркера. Один на процесс: второй экземпляр с тем же id вытеснит первый. По умолчанию равен имени воркера. |
| `MQTT_QOS` | воркер и демо-скрипты | 0, 1 или 2. Для пилота 1: брокер хранит сообщение, пока получатель его не подтвердит. |
| `MQTT_KEEPALIVE` | воркер | Секунды между служебными ping. От 5 до 65535, по умолчанию 60. |
| `MQTT_TOPIC_PREFIX` | воркер, ACL, healthcheck | Префикс топиков без слэшей по краям. По умолчанию `forecast/v1`. Запрос: `<префикс>/<username>/request`, ответ: `<префикс>/<username>/response`. |
| `MQTT_HOST` | воркер, задаёт Compose | Имя сервиса брокера, `mosquitto`. В `.env` можно не трогать. |
| `MQTT_PORT` | воркер, задаёт Compose | Порт брокера в сети Compose, всегда `1883`. |
| `CHRONOS_MODEL` | воркер | Идентификатор модели на Hugging Face. Для пилота `amazon/chronos-2`. |
| `CHRONOS_DEVICE` | воркер | `cpu` или `cuda`. На сервере без GPU оставляйте `cpu`. |
| `CHRONOS_PRELOAD` | воркер | `true` — грузить Chronos-2 сразу после старта. `false` — при первом запросе `chronos-2` или `both`. |
| `HF_HOME` | воркер | Каталог весов внутри контейнера. Должен остаться `/opt/hf`: на него смотрит том `hf-cache`. |
| `TORCH_INDEX` | только сборка образа | Откуда ставить PyTorch. CPU: `https://download.pytorch.org/whl/cpu`. CUDA 12.4: `https://download.pytorch.org/whl/cu124`. Смена требует `docker compose up -d --build`. |
| `MAX_SERIES` | воркер | Сколько рядов в одном сообщении. По умолчанию 8. |
| `MAX_POINTS` | воркер | Сколько точек истории у одного ряда и сколько точек получается после выравнивания шага. По умолчанию 5000. |
| `MAX_HORIZON` | воркер | Потолок `horizon`. По умолчанию 512. |
| `MIN_POINTS` | воркер | Минимум точек с разными метками. По умолчанию 10. Не меньше 2. |
| `QUEUE_SIZE` | воркер | Длина очереди ожидающих запросов. По умолчанию 8. |
| `LOG_LEVEL` | воркер | `DEBUG`, `INFO`, `WARNING`, `ERROR` или `CRITICAL`. |

## docker-compose.yml

Два сервиса.

**mosquitto** — образ `eclipse-mosquitto:2`. Свой entrypoint [deploy/mosquitto/entrypoint.sh](deploy/mosquitto/entrypoint.sh) сначала собирает пароли и копию ACL, затем вызывает штатный `/docker-entrypoint.sh`. Команда брокера задана в Compose явно (`/usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf`): если заменить entrypoint и не указать `command`, Compose не подставит команду из образа, и контейнер сразу завершится.

Проброс `${MQTT_PUBLISH_PORT:-1883}:1883` — слева порт хоста, справа порт контейнера.

Тома:

- `mosquitto.conf`, `acl`, скрипты и `clients.extra` смонтированы только на чтение;
- `mosquitto-passwd` — собранный файл хешей и копия ACL;
- `mosquitto-data` — база persistence (`mosquitto.db`): очередь QoS 1 и постоянные сессии.

Healthcheck логинится воркером и подписывается на свой топик ответа с флагом `-E`: клиент выходит сразу после подтверждения подписки, сообщение не ждёт. `restart: unless-stopped` поднимает контейнер после перезагрузки сервера.

**forecast** — сборка из [Dockerfile](Dockerfile). Ждёт, пока брокер станет healthy. Том `hf-cache` на `/opt/hf` хранит веса между пересозданиями контейнера. Healthcheck смотрит файл `/tmp/forecast-healthy`, который воркер создаёт после успешного MQTT-подключения. `stop_grace_period: 3m` даёт досчитать уже начатый прогноз при `docker compose stop`.

Строка `gpus: all` закомментирована. На машине без NVIDIA её нельзя включать: Compose не найдёт runtime.

Сеть одна, имя проекта по умолчанию совпадает с каталогом. Воркер ходит на хост `mosquitto`.

## mosquitto.conf

Файл [deploy/mosquitto/mosquitto.conf](deploy/mosquitto/mosquitto.conf). Паролей в нём нет.

| Директива | Значение | Зачем |
| --- | --- | --- |
| `listener 1883` | порт без адреса | Слушать все интерфейсы контейнера. В Mosquitto 2 без явного listener снаружи подключиться нельзя. |
| `protocol mqtt` | обычный MQTT, не WebSocket | Контуры IoT говорят по MQTT. |
| `socket_domain ipv4` | только IPv4 | Не открывать отдельный IPv6-сокет. |
| `allow_anonymous false` | запрет без пароля | Иначе аноним обходит ACL. |
| `password_file` | `/mosquitto/passwd/passwd` | Хеши. Файл заново собирается при каждом старте контейнера. Править его руками бессмысленно. |
| `acl_file` | `/mosquitto/passwd/acl` | Копия ACL с владельцем `mosquitto` и правами 600. Исходник на хосте может быть 644, брокер 2.1 иначе предупреждает, что в будущем откажется читать «слишком открытый» файл. |
| `persistence true` | включено | Писать очередь и сессии на диск. |
| `persistence_location` | `/mosquitto/data/` | Каталог тома `mosquitto-data`. |
| `autosave_interval 300` | 300 секунд | Снимок базы раз в 5 минут. |
| `autosave_on_changes false` | по таймеру, не по счётчику сообщений | Поток публикаций не форсирует запись на диск. |
| `persistent_client_expiration 7d` | 7 дней | Сессия с clean session = false удаляется, если клиент не возвращался 7 дней. Суффикс `m` у этой директивы означает месяцы, не минуты. |
| `log_dest stdout` | журнал в stdout | Его забирает `docker compose logs`. Отдельный файл не пишем. |
| `log_type` | error, warning, notice, information | Без debug, чтобы не печатать каждое сообщение. |
| `log_timestamp true` | время в строке | Формат задаёт следующая директива. |
| `log_timestamp_format` | `%Y-%m-%dT%H:%M:%S` | Время в журнале брокера. |
| `max_packet_size 10485760` | 10 МиБ | Потолок всего MQTT-пакета. С версии 2.1 у брокера иначе потолок 2 МиБ, длинный пакет из нескольких рядов в него не влезет. Клиент с пакетом больше лимита будет отключён. |
| `max_inflight_messages 20` | 20 | Сколько QoS 1/2 одновременно «в полёте» одному клиенту. |
| `max_queued_messages 1000` | 1000 | Сколько QoS 1/2 держать для отключённого клиента с постоянной сессией. |
| `set_tcp_nodelay true` | без алгоритма Нейгла | Короткие JSON уходят сразу. |
| `max_keepalive 0` | не ограничивать | Ненулевое значение для MQTT 3.1.1 отклоняет клиентов с большим keepalive. Ноль оставляет поведение по умолчанию. |
| `sys_interval 10` | 10 секунд | Как часто обновлять внутренние счётчики `$SYS`. Доступа к `$SYS` в ACL нет. |

`per_listener_settings` не задаётся. В Mosquitto 2.1 директива устарела, значение по умолчанию как раз наше: один файл паролей и один ACL на все listener-ы.

Блок `listener 8883` в конце файла закомментирован. Это заготовка TLS. Пароль по порту 1883 идёт открытым текстом. Для пилота в закрытой сети этого достаточно. В интернет порт 1883 лучше не выставлять. Если на сервере включён ufw и контурам нужен доступ:

```bash
sudo ufw allow 1883/tcp
```

Чтобы включить TLS: положить сертификаты, смонтировать их в контейнер, раскомментировать listener 8883 и добавить в сервис `mosquitto` проброс `"8883:8883"`. Пока `require_certificate false`, клиент проверяет сертификат сервера и по-прежнему логинится именем и паролем.

## ACL

Файл [deploy/mosquitto/acl](deploy/mosquitto/acl):

```
user forecast-worker
topic read forecast/v1/+/request
topic write forecast/v1/+/response

pattern write forecast/v1/%u/request
pattern read forecast/v1/%u/response
```

`user` начинает блок правил одного пользователя. `forecast-worker` читает все запросы и пишет все ответы.

`pattern` действует на всех, включая воркера. `%u` подставляет username и занимает весь уровень топика. Поэтому `demo-scada` пишет только в `forecast/v1/demo-scada/request` и читает только `forecast/v1/demo-scada/response`. Подписка healthcheck как раз читает `forecast/v1/forecast-worker/response` по этому правилу.

Нового контура в ACL добавлять не нужно: `%u` покрывает любое имя из файла паролей.

## Пароли

[deploy/mosquitto/init-passwd.sh](deploy/mosquitto/init-passwd.sh) при каждом старте брокера заново собирает `/mosquitto/passwd/passwd` утилитой `mosquitto_passwd`:

1. `MQTT_WORKER_USERNAME` / `MQTT_WORKER_PASSWORD`;
2. `DEMO_CLIENT_USERNAME` / `DEMO_CLIENT_PASSWORD`;
3. строки `username:password` из [deploy/mosquitto/clients.extra](deploy/mosquitto/clients.extra). Пустые строки и строки с `#` пропускаются.

Файл получает владельца uid 1883 (пользователь `mosquitto` в образе) и права 600. Исходные пароли в томе не хранятся, только хеши. Туда же копируется ACL.

Если имя воркера или префикс топиков не находятся в исходном ACL, скрипт завершается с текстом ошибки, и брокер не стартует. Журнал: `docker compose logs mosquitto`.

## Образ forecast

[Dockerfile](Dockerfile) основан на `python:3.11-slim`. В него ставятся компилятор (он нужен CmdStan), `tini` и зависимости из [requirements.txt](requirements.txt): `paho-mqtt`, `pydantic`, `pandas`, `prophet`, `chronos-forecasting`.

PyTorch ставится последним и принудительно с индекса `TORCH_INDEX`, чтобы зависимость Chronos не подменила его на тяжёлую CUDA-сборку. CmdStan собирается в домашний каталог пользователя `forecast` (uid 10001) во время `docker compose build`.

[docker/entrypoint.py](docker/entrypoint.py) при старте контейнера от root готовит каталог `/opt/hf` (том изначально принадлежит root, и пользователь `forecast` иначе не сможет скачать веса), затем сбрасывает права и запускает `python -m app.main`. `tini` стоит процессом 1 и передаёт контейнеру сигнал остановки.

Воркер [app/main.py](app/main.py) подключается к брокеру с `clean_session=false`, подписывается на `<префикс>/+/request` и считает очередь в одном потоке. Имя клиента берётся из топика. Расчёт — [app/service.py](app/service.py), Prophet — [app/forecasting/prophet_model.py](app/forecasting/prophet_model.py), Chronos-2 — [app/forecasting/chronos_model.py](app/forecasting/chronos_model.py), текст — [app/forecasting/narrative.py](app/forecasting/narrative.py).

## GPU

На сервере с NVIDIA:

1. Поставить драйвер и [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
2. В `.env` поставить `CHRONOS_DEVICE=cuda` и `TORCH_INDEX=https://download.pytorch.org/whl/cu124` (или индекс под вашу версию CUDA).
3. В `docker-compose.yml` у сервиса `forecast` раскомментировать `gpus: all`.
4. Пересобрать: `docker compose up -d --build`.

Prophet от GPU не ускоряется, он считается на CPU.

## Если что-то не так

| Что видно | Куда смотреть |
| --- | --- |
| `mosquitto` в статусе Restarting, в журнале только строки `mosquitto-init` | Брокер не остаётся запущенным. Проверьте, что в compose есть `command` с `mosquitto -c ...`, и что init не закончился ошибкой. |
| `нет строки user ...` в журнале брокера | `MQTT_WORKER_USERNAME` и строка `user` в ACL разошлись. |
| `forecast` не становится healthy | Пароль воркера в уже созданном контейнере старый. Запустите `./scripts/reload-passwords.sh`. |
| Ответ не приходит, публикация при этом «успешна» | Подпишитесь раньше отправки. Проверьте топик: `forecast/v1/<ваш-username>/request`. Чужой топик брокер молча выбрасывает. |
| Долго нет ответа, в журнале нет ошибки | Идёт первый расчёт Prophet или Chronos на CPU. Смотрите `docker compose logs -f forecast`. |
| `Chronos-2 не загрузилась` | Нет доступа к Hugging Face или кончилось место в томе `hf-cache`. Запрос с `"model": "prophet"` посчитается. |
| Сборка образа падает на нехватке памяти | Нужно около 8 ГБ RAM на компиляцию CmdStan. |

Полезные команды:

```bash
docker compose logs -f mosquitto
docker compose logs -f forecast
docker compose ps
```

## Разработка и тесты

Юнит-тесты не поднимают брокер и не качают модели:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install pydantic pandas pytest
pytest
```

Тест Prophet в `tests/test_prophet_model.py` сам пропускается, если пакет `prophet` не установлен. Тест Chronos-2 в `tests/test_chronos_model.py` запускается только при `RUN_CHRONOS=1`: он скачивает `amazon/chronos-2`.

## Состав репозитория

```
.env.example                         пример переменных
docker-compose.yml                   брокер и воркер
Dockerfile                           образ воркера
docker/entrypoint.py                 права на каталог весов и сброс uid
deploy/mosquitto/mosquitto.conf      настройки брокера
deploy/mosquitto/acl                 кто какой топик читает и пишет
deploy/mosquitto/clients.extra       дополнительные логины SCADA
deploy/mosquitto/init-passwd.sh      сборка файла паролей при старте
deploy/mosquitto/entrypoint.sh       init, затем штатный entrypoint образа
app/                                 воркер, проверка JSON, модели, текст
examples/forecast_request.json       пример запроса на 72 часа
scripts/demo-sub.sh                  подписка демо-клиента
scripts/demo-pub.sh                  публикация примера
scripts/register-client.sh           новый логин и перезапуск брокера
scripts/reload-passwords.sh          применить .env и clients.extra заново
tests/                               проверки без брокера и без весов
```
