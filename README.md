# KernvoxHub

KernvoxHub - центральный сервер для мониторинга Linux-серверов и простых операторских действий через SSH. Он собирает метрики, хранит историю и отдаёт данные REST API для Kernvox/Android-клиента.

## Что умеет

- собирать CPU, RAM, disk, network, uptime и список процессов;
- хранить метрики в PostgreSQL/TimescaleDB;
- кэшировать API-токены в Redis;
- подключаться к подчинённым серверам по SSH с проверкой host key;
- хранить SSH-пароли, приватные ключи и host key в зашифрованном виде;
- перезагружать сервер через защищённый action endpoint или CLI;
- обновляться одной командой через `kernvoxhub update`.

## Архитектура

```
Kernvox / Android
      |
      | HTTPS + X-API-Key
      v
Nginx -> FastAPI backend -> PostgreSQL + Redis
             |
             | SSH
             v
       Linux servers
```

Collector работает отдельным контейнером и по расписанию опрашивает все активные серверы. Backend обслуживает API, CLI-команды внутри контейнера и live-действия вроде просмотра процессов или reboot.

## Быстрый старт

Требования: Linux/macOS/WSL, Docker, Docker Compose. Installer может помочь установить недостающие зависимости на популярных Linux-дистрибутивах.

```bash
git clone https://github.com/Vennilay/KernvoxHub.git
cd KernvoxHub
chmod +x setup.sh
./setup.sh
```

`setup.sh` создаст `.env`, сгенерирует секреты, запустит сервисы и установит системную команду `kernvoxhub`.

Проверка:

```bash
docker compose ps
curl http://localhost/api/v1/health
```

## Добавление сервера

Самый простой путь - интерактивная команда:

```bash
kernvoxhub add-server --test-connection
```

CLI спросит имя, адрес, SSH-порт, пользователя и способ входа: пароль или приватный ключ. При `--test-connection` KernvoxHub сразу подключится к серверу и сохранит SSH host key.

Рекомендованный вариант для production:

1. Создайте отдельного пользователя на подчинённом сервере.
2. Используйте SSH key auth вместо пароля.
3. Для перезагрузки разрешите только нужную команду через sudoers, например `/sbin/shutdown -r now`, без полного root-доступа.

Полезные команды:

```bash
kernvoxhub list-servers
kernvoxhub test-server 1
kernvoxhub metrics 1
kernvoxhub reboot-server 1 --yes
```

## Перезагрузка сервера

Через API:

```bash
curl -X POST http://localhost/api/v1/servers/1/actions/reboot \
  -H "X-API-Key: <api_token>" \
  -H "X-Action-Key: <server_action_token>"
```

`X-Action-Key` берётся из `.env` переменной `SERVER_ACTION_TOKEN`. Если переменная не задана, endpoint работает только по обычному `X-API-Key`, но для production лучше держать отдельный action-token.

Ответ при принятой команде:

```json
{
  "id": 1,
  "server_id": 1,
  "server_name": "production-db-01",
  "action": "reboot",
  "status": "accepted",
  "message": "Reboot command accepted by server",
  "created_at": "2026-05-09T12:00:00Z"
}
```

История действий:

```bash
curl http://localhost/api/v1/servers/1/actions \
  -H "X-API-Key: <api_token>"
```

## API

Все непубличные endpoints требуют:

```http
X-API-Key: <api_token>
```

Основные endpoints:

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/servers` | Список серверов |
| `POST` | `/api/v1/servers` | Добавить сервер |
| `GET` | `/api/v1/servers/{id}` | Карточка сервера |
| `PUT` | `/api/v1/servers/{id}` | Обновить сервер |
| `DELETE` | `/api/v1/servers/{id}` | Деактивировать сервер |
| `GET` | `/api/v1/servers/{id}/metrics` | Последние метрики |
| `GET` | `/api/v1/servers/{id}/metrics/history` | История метрик |
| `GET` | `/api/v1/servers/{id}/metrics/timeseries` | Агрегированная серия |
| `POST` | `/api/v1/servers/{id}/actions/reboot` | Перезагрузка сервера |
| `GET` | `/api/v1/servers/{id}/actions` | Аудит действий |

Android endpoints:

| Метод | Endpoint |
|---|---|
| `GET` | `/api/v1/android/dashboard` |
| `GET` | `/api/v1/android/servers/{id}/details` |
| `GET` | `/api/v1/android/servers/{id}/processes` |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` |
| `GET` | `/api/v1/android/servers/{id}/metrics/timeseries` |

## Обновление

После установки `kernvoxhub` сам проверяет наличие новой версии и предлагает обновиться:

```bash
kernvoxhub
```

Можно проверить и запустить обновление явно:

```bash
kernvoxhub check-update
kernvoxhub update
kernvoxhub status
kernvoxhub logs backend
```

Обычный сценарий не требует выбирать ветки или коммиты. Updater проверяет опубликованную версию, обновляет файлы проекта, пересобирает контейнеры и ждёт health checks. Если в старом `.env` нет новых runtime-секретов, например `SERVER_ACTION_TOKEN`, updater добавит их сам.

Для обслуживания без скачивания новой версии есть технический режим:

```bash
kernvoxhub update --skip-git
```

## Конфигурация

Главные переменные `.env`:

| Переменная | Для чего нужна |
|---|---|
| `POSTGRES_PASSWORD` | пароль PostgreSQL |
| `API_TOKEN` | bootstrap API-токен |
| `SERVER_ACTION_TOKEN` | отдельный ключ для destructive actions |
| `ENCRYPTION_KEY` | Fernet-ключ для шифрования SSH-секретов |
| `REDIS_PASSWORD` | пароль Redis |
| `INTERNAL_API_KEY` | ключ для внутренних записывающих endpoints |
| `CORS_ORIGINS` | разрешённые origins |
| `COLLECTOR_INTERVAL` | интервал опроса серверов |
| `DOMAIN`, `EMAIL` | домен и email для SSL |

Не коммитьте `.env`, приватные ключи, сертификаты и дампы базы.

## Разработка

```bash
pytest -v
pytest backend/tests/test_api.py
docker compose up -d --build
docker compose logs -f backend
```

Тесты лежат в `backend/tests/`. При изменениях в SSH, auth, encryption, reboot или installer/update добавляйте регрессионные тесты рядом с затронутым поведением.

## Безопасность

- SSH host key сохраняется при первом успешном подключении и затем проверяется при каждом новом подключении.
- Пароли, приватные SSH-ключи и host key хранятся в базе зашифрованными через Fernet.
- API закрыт `X-API-Key`, а destructive actions дополнительно закрываются `X-Action-Key`.
- Для reboot используйте отдельного SSH-пользователя и минимальные sudoers-права.
- При смене host/port у сервера сохранённый host key сбрасывается, чтобы не доверять старому ключу для нового адреса.
