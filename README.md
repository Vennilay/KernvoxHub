# KernvoxHub

KernvoxHub — backend-сервис для централизованного мониторинга Linux-серверов через SSH. Сервис периодически собирает системные метрики, хранит историю в PostgreSQL/TimescaleDB и предоставляет REST API для Android-клиента Kernvox и других интеграций.

Проект разворачивается как Docker Compose-стек и включает API, отдельный процесс сбора метрик, базу данных, Redis, Nginx и автоматическое обновление TLS-сертификатов.

## Возможности

- мониторинг CPU, RAM, корневого раздела, сетевого трафика и uptime;
- получение списка процессов по SSH в реальном времени;
- хранение истории метрик в PostgreSQL с поддержкой TimescaleDB hypertable;
- выдача исходных и агрегированных временных рядов;
- управление серверами через REST API и CLI;
- перезагрузка удалённого сервера с отдельным ключом подтверждения;
- аудит команд перезагрузки;
- SSH-аутентификация по паролю или приватному ключу;
- шифрование SSH-паролей, приватных ключей и host key с помощью Fernet;
- проверка SSH host key при повторных подключениях;
- API-аутентификация, ограничение неудачных попыток входа и временная блокировка по IP;
- HTTP-режим для локальной установки и HTTPS через Let's Encrypt для публичного домена;
- установка и обновление через shell-скрипты.

## Архитектура

```text
Android-клиент / API-клиент
            |
            | HTTP(S), X-API-Key
            v
         Nginx
            |
            v
      FastAPI backend -------- Redis
            |                   |
            |                   +-- хэши API-токенов и auth rate limit
            v
 PostgreSQL + TimescaleDB
            ^
            |
       Collector
            |
            | SSH
            v
      Linux-серверы
```

| Компонент | Назначение |
|---|---|
| `backend` | REST API, авторизация, управление серверами и действиями |
| `collector` | отдельный планировщик сбора метрик по SSH |
| `postgres` | серверы, метрики и журнал действий |
| `redis` | хэши дополнительных API-токенов, кэш валидации и auth rate limit |
| `nginx` | reverse proxy, HTTP/HTTPS и security headers |
| `certbot` | автоматическое продление сертификатов Let's Encrypt |

Collector изолирован от API: сбой сбора метрик не останавливает чтение уже сохранённых данных. Список активных серверов синхронизируется с планировщиком каждые `15–60` секунд, а интервал опроса задаётся через `COLLECTOR_INTERVAL`.

## Технологии

- Python 3.11;
- FastAPI и Uvicorn;
- SQLAlchemy 2;
- PostgreSQL 16 и TimescaleDB;
- Redis 7;
- Paramiko;
- APScheduler;
- Pydantic 2;
- Nginx, Certbot и Docker Compose.

## Требования

Для сервера, на котором запускается KernvoxHub:

- Linux;
- Git;
- Docker Engine;
- Docker Compose v2 или `docker-compose`;
- OpenSSL;
- домен с корректной DNS-записью, если нужен HTTPS.

Installer умеет устанавливать недостающие Docker, Compose и системные зависимости на Debian/Ubuntu, RHEL/Fedora-подобных и Arch-подобных дистрибутивах.

Для контролируемых серверов:

- Linux с доступными `/proc`, `ps`, `df` и стандартными shell-утилитами;
- SSH-доступ с хоста KernvoxHub;
- пароль или поддерживаемый Paramiko приватный ключ;
- `sudo` или root-доступ только для функции перезагрузки.

## Быстрый старт

```bash
git clone https://github.com/Vennilay/KernvoxHub.git
cd KernvoxHub
chmod +x setup.sh
./setup.sh
```

Installer:

1. проверит системные зависимости;
2. запросит домен, email, CORS origins и интервал сбора;
3. создаст `.env` и сгенерирует секреты;
4. установит права `600` на `.env`;
5. соберёт и запустит Docker Compose-стек;
6. дождётся готовности PostgreSQL, Redis, backend, Nginx и collector;
7. установит команды `kernvoxhub` и `kernvoxhub-update` в `/usr/local/bin`;
8. при необходимости запустит настройку Let's Encrypt.

Проверка состояния:

```bash
kernvoxhub status
docker compose ps
curl http://127.0.0.1/api/v1/health
```

Локальный health check с loopback-адреса доступен без API-ключа. Для внешнего запроса требуется `X-API-Key`:

```bash
curl https://api.example.com/api/v1/health \
  -H "X-API-Key: <API_TOKEN>"
```

Корневой маршрут, Swagger UI, ReDoc и OpenAPI schema намеренно отключены и возвращают `404`.

## Секреты доступа

Все основные секреты создаются во время `setup.sh` и находятся в `.env` в каталоге установки.

Получить bootstrap API-токен:

```bash
sed -n 's/^API_TOKEN=//p' .env
```

Получить отдельный ключ серверных действий, необходимый для перезагрузки:

```bash
sed -n 's/^SERVER_ACTION_TOKEN=//p' .env
```

Выпустить дополнительный API-токен:

```bash
docker compose exec backend python -m cli.main generate-token
```

Дополнительный токен показывается один раз. В Redis сохраняется только его SHA-256-хэш. Bootstrap-токен из `API_TOKEN` остаётся доступным через `.env`.

Не публикуйте `.env`, токены, приватные ключи, сертификаты и дампы базы данных.

## Добавление сервера

Интерактивное добавление с проверкой SSH-соединения:

```bash
kernvoxhub add-server --test-connection
```

CLI запросит:

- отображаемое имя;
- IP-адрес или домен;
- SSH-порт;
- SSH-пользователя;
- способ аутентификации: пароль или приватный ключ.

Ключ можно передать из доступного внутри контейнера файла или вставить целиком в терминал. Для нового сервера должен быть указан ровно один способ SSH-аутентификации.

Основные команды:

```bash
kernvoxhub list-servers
kernvoxhub test-server <ID>
kernvoxhub metrics <ID>
kernvoxhub setup-reboot-sudo <ID>
kernvoxhub reboot-server <ID> --yes
```

Дополнительные backend CLI-команды:

```bash
docker compose exec backend python -m cli.main status
docker compose exec backend python -m cli.main delete-server <ID>
docker compose exec backend python -m cli.main metrics <ID> --limit 10
```

Удаление сервера является мягким: запись остаётся в БД, но получает `is_active=false`, скрывается из API и больше не опрашивается collector.

## SSH host key

При первом успешном подключении KernvoxHub сохраняет host key сервера по принципу Trust On First Use. При последующих подключениях ключ сравнивается с сохранённым.

Если host key изменился:

- SSH-соединение прерывается;
- сбор метрик или действие не выполняется;
- событие логируется как возможная MITM-атака;
- для API-перезагрузки создаётся audit-запись со статусом `host_key_mismatch`.

При изменении `host` или `port` через API старый host key сбрасывается, поскольку он относится к прежней SSH-точке.

## Настройка перезагрузки

Если SSH-пользователь не является root, ему нужен строго ограниченный `sudo` без пароля для команд перезагрузки. Настроить правило можно через KernvoxHub:

```bash
kernvoxhub setup-reboot-sudo <ID>
```

Команда создаёт на удалённом сервере файл:

```text
/etc/sudoers.d/kernvoxhub-reboot
```

Разрешаются только варианты `shutdown -r now`, `systemctl reboot` и `reboot`. Конфигурация предварительно проверяется через `visudo`, если он установлен.

Для сервера с SSH-паролем backend также может однократно передать этот пароль в `sudo -S`. Для key-only подключения рекомендуется настроить NOPASSWD-правило. Одноразовый sudo-пароль, введённый в CLI, не сохраняется.

Перезагрузка через API:

```bash
curl -X POST https://api.example.com/api/v1/servers/1/actions/reboot \
  -H "X-API-Key: <API_TOKEN>" \
  -H "X-Action-Key: <SERVER_ACTION_TOKEN>"
```

Успешный запрос возвращает `202 Accepted`. Если `SERVER_ACTION_TOKEN` не задан, endpoint работает в fail-closed режиме и возвращает `503`.

История действий:

```bash
curl https://api.example.com/api/v1/servers/1/actions \
  -H "X-API-Key: <API_TOKEN>"
```

## Аутентификация и защита API

Все рабочие API-маршруты требуют заголовок:

```http
X-API-Key: <API_TOKEN>
```

Исключения:

- `/`, `/docs`, `/redoc` и `/openapi.json` возвращают нейтральный `404`;
- `/api/v1/health` разрешён без ключа только для loopback-клиента.

После 10 неудачных попыток авторизации за 60 секунд IP временно блокируется на 5 минут. Состояние ограничителя хранится в Redis. При недоступности Redis валидный bootstrap API-токен продолжает работать.

Дополнительные уровни защиты:

| Назначение | Заголовок | Переменная |
|---|---|---|
| обычный API-доступ | `X-API-Key` | `API_TOKEN` или выпущенный Redis-токен |
| перезагрузка сервера | `X-Action-Key` | `SERVER_ACTION_TOKEN` |
| запись метрик через API | `X-Internal-Key` | `INTERNAL_API_KEY` |

`INTERNAL_API_KEY` проверяется только для `POST /metrics`. Installer всегда генерирует его. Если переменная намеренно оставлена пустой, endpoint записи защищён только обычным `X-API-Key`.

## REST API

### Серверы

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/api/v1/servers?skip=0&limit=100` | список активных серверов |
| `POST` | `/api/v1/servers` | создание сервера |
| `GET` | `/api/v1/servers/{id}` | получение сервера |
| `PUT` | `/api/v1/servers/{id}` | частичное обновление |
| `DELETE` | `/api/v1/servers/{id}` | деактивация сервера |

Секретные SSH-поля никогда не включаются в API-ответы.

### Метрики

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/api/v1/servers/{id}/metrics?limit=1` | последние `1–10` измерений |
| `GET` | `/api/v1/servers/{id}/metrics/history` | история, фильтры `from`, `to`, `limit` |
| `GET` | `/api/v1/servers/{id}/metrics/timeseries` | исходный или агрегированный временной ряд |
| `POST` | `/api/v1/servers/{id}/metrics` | внутренняя запись метрики |

Параметры временного ряда:

- `interval`: `raw`, `1m`, `5m`, `15m`, `1h`, `6h`, `1d`;
- `order`: `asc` или `desc`;
- `from`, `to`: ISO 8601 datetime;
- `limit`: от `1` до `2000`.

Для каждого агрегированного интервала возвращаются средние, минимальные и максимальные CPU/RAM/disk, средние сетевые счётчики и uptime, число измерений и доля доступности.

### Действия

| Метод | Endpoint | Назначение |
|---|---|---|
| `POST` | `/api/v1/servers/{id}/actions/reboot` | отправка команды перезагрузки |
| `GET` | `/api/v1/servers/{id}/actions?limit=50` | журнал действий, максимум 200 записей |

### Android API

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/api/v1/android/dashboard` | сводка по активным серверам |
| `GET` | `/api/v1/android/servers/{id}/details` | сервер и его последняя метрика |
| `GET` | `/api/v1/android/servers/{id}/processes?limit=50` | процессы по SSH в реальном времени |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` | история в формате Android-клиента |
| `GET` | `/api/v1/android/servers/{id}/metrics/timeseries` | агрегированный временной ряд |

Processes endpoint выполняет отдельное SSH-подключение при каждом запросе. Список процессов в PostgreSQL не сохраняется.

## Собираемые метрики

| Метрика | Источник на удалённом сервере |
|---|---|
| общая загрузка CPU | два чтения `/proc/stat`, fallback на `vmstat` |
| RAM | `/proc/meminfo`, расчёт Linux working set |
| диск | использование корневого раздела через `df /` |
| RX/TX | default interface из `/proc/net/dev`, fallback на сумму non-loopback интерфейсов |
| uptime | `/proc/uptime` |
| процессы | `ps aux`, сортировка по CPU |

Если SSH-подключение collector не удалось, в историю записывается метрика с `is_available=false`.

## Конфигурация

| Переменная | Назначение |
|---|---|
| `POSTGRES_PASSWORD` | пароль пользователя PostgreSQL `kernvox` |
| `API_SECRET` | зарезервированный секрет приложения |
| `API_TOKEN` | bootstrap API-токен |
| `SERVER_ACTION_TOKEN` | отдельный ключ для серверных действий |
| `ENCRYPTION_KEY` | Fernet-ключ для SSH-секретов и host key |
| `REDIS_PASSWORD` | пароль Redis |
| `INTERNAL_API_KEY` | ключ внутренней записи метрик |
| `CORS_ORIGINS` | разрешённые origins через запятую |
| `COLLECTOR_INTERVAL` | период сбора метрик в секундах |
| `DOMAIN` | домен API или `localhost` |
| `EMAIL` | email для Let's Encrypt |

Не меняйте `ENCRYPTION_KEY` у существующей установки без миграции данных: ранее сохранённые SSH-секреты перестанут расшифровываться.

## HTTPS

Для выпуска или повторной настройки сертификата:

```bash
chmod +x scripts/ssl-setup.sh
./scripts/ssl-setup.sh
```

Скрипт проверяет домен и DNS, выполняет ACME HTTP-01 challenge, перезапускает Nginx и убеждается, что активна TLS-конфигурация. При наличии сертификата Nginx перенаправляет HTTP на HTTPS и включает HSTS.

Certbot проверяет продление каждые 12 часов. Nginx отслеживает изменение файлов сертификата и автоматически перечитывает конфигурацию.

## Управление и обновление

```bash
kernvoxhub
kernvoxhub status
kernvoxhub logs
kernvoxhub logs backend
kernvoxhub check-update
kernvoxhub update
```

Обновление без `git pull`, только пересборка и перезапуск:

```bash
kernvoxhub update --skip-git
```

Обновление с повторной проверкой SSL:

```bash
kernvoxhub update --with-ssl
```

Updater:

- требует чистое Git-дерево;
- выполняет только fast-forward update;
- сохраняет существующий `.env`;
- добавляет отсутствующий `SERVER_ACTION_TOKEN`;
- пересобирает контейнеры;
- ожидает health checks всех основных сервисов.

## Резервное копирование

Дамп PostgreSQL:

```bash
docker compose exec -T postgres \
  pg_dump -U kernvox -d kernvox > kernvox-backup.sql
```

Помимо базы данных храните защищённую резервную копию `.env`. Без исходного `ENCRYPTION_KEY` восстановить зашифрованные SSH-учётные данные невозможно.

## Разработка и тесты

Установка Python-зависимостей:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Запуск тестов из корня проекта:

```bash
pytest
pytest -v
pytest --cov=backend
```

Тесты находятся в `backend/tests` и покрывают:

- API серверов, метрик, Android-ответов и действий;
- аутентификацию и rate limit;
- Fernet-шифрование;
- API-токены и Redis;
- SSH host key;
- сбор и агрегацию метрик;
- reboot и sudoers;
- CLI;
- installer, updater, SSL и Nginx entrypoint.

Локальный запуск всего стека:

```bash
cp .env.example .env
# Замените все placeholder-значения в .env.
docker compose up -d --build
docker compose logs -f
```

## Структура проекта

```text
backend/
  api/             FastAPI middleware и routes
  cli/             backend CLI
  collector/       SSH-клиент, сборщик метрик и scheduler
  models/          SQLAlchemy-модели и инициализация БД
  schemas/         Pydantic-схемы
  services/        токены, Redis, временные ряды и server actions
  tests/           API, unit, CLI и script tests
  utils/           Fernet-шифрование
nginx/             HTTP/HTTPS templates и entrypoint
scripts/           installer helpers, SSL и системные launcher'ы
docker-compose.yml описание runtime-стека
setup.sh           первичная установка
update.sh          безопасное обновление
```

## Ограничения

- проект рассчитан на Linux-серверы и Linux production-host;
- SSH host key при первом подключении принимается по модели TOFU;
- процессы не сохраняются и доступны только при успешном SSH-подключении;
- агрегация временных рядов выполняется в приложении после чтения подходящих метрик из БД;
- встроенная интерактивная документация FastAPI отключена;
- удаление сервера не удаляет его историю физически;
- автоматической ротации `ENCRYPTION_KEY` и отзыва отдельных API-токенов через публичный API пока нет.
