# KernvoxHub

Проект для мониторинга Linux-серверов через телефон. Делал для Samsung Academy, но вышло достаточно рабочим, чтобы использовать и для себя. Идея в том, что бэкенд подключается к серверам по SSH, читает метрики и отдаёт всё через REST API Android-клиенту Kernvox.

## Что умеет

Собирает CPU, RAM, диск, сеть, uptime и список процессов. Хранит всё в PostgreSQL/TimescaleDB, токены кэширует в Redis. SSH-ключи и пароли хранятся зашифрованными через Fernet — не в открытом виде. При первом подключении к серверу сохраняется его host key, и если при следующем подключении он поменяется — соединение не установится, это защита от MITM. Ещё можно перезагрузить сервер прямо из API или CLI, но для этого нужен отдельный токен.

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

Collector работает отдельным контейнером и раз в минуту опрашивает все активные серверы. Намеренно не смешивал его с бэкендом — если коллектор упадёт, API продолжит работать.

## Быстрый старт

Нужны Docker и Docker Compose. Если чего-то не хватает — installer может сам поставить на популярных Linux-дистрибутивах.

```bash
git clone https://github.com/Vennilay/KernvoxHub.git
cd KernvoxHub
chmod +x setup.sh
./setup.sh
```

`setup.sh` создаёт `.env` с уже сгенерированными секретами, поднимает контейнеры и прописывает команду `kernvoxhub` в систему. Проверить что всё живо:

```bash
docker compose ps
curl http://localhost/api/v1/health
```

## Добавление сервера

Проще всего через CLI:

```bash
kernvoxhub add-server --test-connection
```

Команда спросит имя, адрес, SSH-порт, пользователя и как подключаться — паролем или приватным ключом. С флагом `--test-connection` сразу проверит соединение и сохранит host key.

Для продакшна честно рекомендую отдельного пользователя и ключ вместо пароля. Для reboot достаточно разрешить только одну команду через sudoers:

```sudoers
kernvox ALL=(root) NOPASSWD: /sbin/shutdown -r now, /usr/sbin/shutdown -r now, /usr/bin/systemctl reboot, /sbin/reboot, /usr/sbin/reboot
```

Настроить это можно прямо из KernvoxHub, не нужно руками лезть на сервер:

```bash
kernvoxhub setup-reboot-sudo 1
```

Если sudo требует пароль — спросит один раз и всё. Если sudo на сервере уже настроен без пароля (`sudo -n` работает) — команда просто тихо пройдёт.

Другие команды которые пригодятся:

```bash
kernvoxhub list-servers
kernvoxhub test-server 1
kernvoxhub metrics 1
kernvoxhub reboot-server 1 --yes
```

## Перезагрузка через API

```bash
curl -X POST http://localhost/api/v1/servers/1/actions/reboot \
  -H "X-API-Key: <api_token>" \
  -H "X-Action-Key: <server_action_token>"
```

`X-Action-Key` — это значение `SERVER_ACTION_TOKEN` из `.env`. Если переменная не задана, endpoint просто откажет. Это намеренно: чтобы нельзя было случайно перезагрузить что-то при запуске без нормальной настройки.

Ответ когда команда принята:

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

Историю действий:

```bash
curl http://localhost/api/v1/servers/1/actions \
  -H "X-API-Key: <api_token>"
```

## API

Все endpoint'ы требуют `X-API-Key` в заголовке. Исключение — health check и документация (`/docs`, `/redoc`).

| Метод | Endpoint | Что делает |
|---|---|---|
| `GET` | `/api/v1/health` | Проверка живости |
| `GET` | `/api/v1/servers` | Список серверов |
| `POST` | `/api/v1/servers` | Добавить сервер |
| `GET` | `/api/v1/servers/{id}` | Карточка сервера |
| `PUT` | `/api/v1/servers/{id}` | Обновить сервер |
| `DELETE` | `/api/v1/servers/{id}` | Деактивировать |
| `GET` | `/api/v1/servers/{id}/metrics` | Последние метрики |
| `GET` | `/api/v1/servers/{id}/metrics/history` | История метрик |
| `GET` | `/api/v1/servers/{id}/metrics/timeseries` | Агрегированный ряд |
| `POST` | `/api/v1/servers/{id}/actions/reboot` | Перезагрузка |
| `GET` | `/api/v1/servers/{id}/actions` | Аудит действий |

Для Android-клиента отдельные endpoint'ы с другим форматом ответа:

| Метод | Endpoint |
|---|---|
| `GET` | `/api/v1/android/dashboard` |
| `GET` | `/api/v1/android/servers/{id}/details` |
| `GET` | `/api/v1/android/servers/{id}/processes` |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` |
| `GET` | `/api/v1/android/servers/{id}/metrics/timeseries` |

## Обновление

После установки `kernvoxhub` сам проверяет новую версию при запуске и предлагает обновиться. Можно и явно:

```bash
kernvoxhub check-update
kernvoxhub update
kernvoxhub status
kernvoxhub logs backend
```

Updater подтягивает новый код, пересобирает контейнеры и ждёт health check. Если в старом `.env` не хватает каких-то переменных — добавит сам. Если хочется просто пересобрать контейнеры без скачивания новой версии:

```bash
kernvoxhub update --skip-git
```

## Конфигурация

Главные переменные в `.env`:

| Переменная | Зачем |
|---|---|
| `POSTGRES_PASSWORD` | пароль PostgreSQL |
| `API_TOKEN` | bootstrap-токен для API |
| `SERVER_ACTION_TOKEN` | ключ для destructive actions |
| `ENCRYPTION_KEY` | Fernet-ключ для шифрования SSH-секретов |
| `REDIS_PASSWORD` | пароль Redis |
| `INTERNAL_API_KEY` | ключ для внутренних записывающих endpoint'ов |
| `CORS_ORIGINS` | разрешённые origin'ы |
| `COLLECTOR_INTERVAL` | интервал опроса серверов |
| `DOMAIN`, `EMAIL` | домен и email для SSL |

`.env`, приватные ключи, сертификаты и дампы базы — всё это не коммитить.

## Разработка

```bash
pytest -v
pytest backend/tests/test_api.py
docker compose up -d --build
docker compose logs -f backend
```

Тесты в `backend/tests/` разбиты по назначению: `api/` — API и middleware, `unit/` — сервисы/парсеры/шифрование/SSH, `cli/` — CLI-команды, `scripts/` — installer, updater и shell-обёртки. Если меняешь что-то в SSH, auth, шифровании, reboot или installer — добавляй регрессионный тест рядом с затронутым поведением.

## Безопасность

SSH host key сохраняется при первом успешном подключении и сверяется при каждом следующем. Пароли, приватные ключи и сам host key хранятся в базе зашифрованными. API закрыт `X-API-Key`, а destructive actions требуют ещё и `X-Action-Key`. Если `SERVER_ACTION_TOKEN` не настроен — endpoint откажет, это fail-closed поведение. При смене хоста или порта сервера сохранённый host key сбрасывается автоматически, чтобы не доверять старому ключу для нового адреса.