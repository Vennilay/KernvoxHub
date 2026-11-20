<a id="top"></a>

<div align="center">

# KernvoxHub

**Backend-сервис и агент сбора метрик для централизованного мониторинга Linux-серверов по SSH**  
*Self-hosted backend & SSH telemetry collector for centralized Linux server monitoring*

<p>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL_16_+_TimescaleDB-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16 + TimescaleDB" />
  <img src="https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis 7" />
  <img src="https://img.shields.io/badge/Docker_Compose-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Compose" />
  <img src="https://img.shields.io/badge/Nginx_+_Certbot-009639?style=flat-square&logo=nginx&logoColor=white" alt="Nginx + Certbot" />
</p>

<p>
  <a href="#readme-ru"><strong>🇷🇺 Русская версия</strong></a>
  &nbsp;•&nbsp;
  <a href="#readme-en"><strong>🇬🇧 English version</strong></a>
  &nbsp;•&nbsp;
  <a href="https://github.com/Vennilay/Kernvox"><strong>📱 Kernvox (Android Client)</strong></a>
</p>

</div>

---

<a id="readme-ru"></a>
# 🇷🇺 KernvoxHub — серверный хаб мониторинга Linux

**KernvoxHub** — self-hosted backend для централизованного наблюдения за Linux-серверами через SSH без установки сторонних агентов на целевые машины. Сервис периодически собирает системные метрики, хранит историю в **PostgreSQL / TimescaleDB** и отдаёт защищённый REST API для Android-клиента [**Kernvox**](https://github.com/Vennilay/Kernvox) и других интеграций.

Вся инфраструктура разворачивается одним Docker Compose-стеком: API, изолированный сборщик метрик, база данных, Redis, Nginx и автоматическое продление TLS-сертификатов.

<p align="center">
  <a href="#ru-how-it-works">Как это работает</a> ·
  <a href="#ru-features">Возможности</a> ·
  <a href="#ru-quickstart">Быстрый старт</a> ·
  <a href="#ru-cli">Управление и CLI</a> ·
  <a href="#ru-security">Безопасность</a> ·
  <a href="#ru-api">REST API</a> ·
  <a href="#ru-config">Конфигурация и HTTPS</a> ·
  <a href="#ru-dev">Разработка</a> ·
  <a href="#ru-authors">Авторы</a> ·
  <a href="#readme-en">🇬🇧 English</a>
</p>

<a id="ru-how-it-works"></a>
## Как это работает

```text
   Android-клиент Kernvox / API-клиенты
                    │
                    │ HTTP(S) + X-API-Key / X-Action-Key
                    ▼
           ┌─────────────────┐        ┌─────────────────┐
           │      Nginx      │◄───────┤     Certbot     │
           │  reverse proxy  │        │  Let's Encrypt  │
           └────────┬────────┘        └─────────────────┘
                    │
                    ▼
           ┌─────────────────┐        ┌─────────────────┐
           │ FastAPI backend │◄──────►│     Redis 7     │
           │  REST API & CLI │        │ токены/rate-lim │
           └────────┬────────┘        └─────────────────┘
                    │
                    ▼
           ┌─────────────────┐
           │  PostgreSQL 16  │
           │  + TimescaleDB  │
           └────────▲────────┘
                    │ запись метрик
           ┌────────┴────────┐
           │    Collector    │  (APScheduler, изоляция от API)
           └────────┬────────┘
                    │ SSH (Paramiko + TOFU host key)
                    ▼
          Контролируемые Linux-серверы
```

| Сервис | Назначение |
| :--- | :--- |
| **`backend`** | FastAPI REST API, аутентификация, управление серверами, аудит и выполнение действий |
| **`collector`** | Отдельный процесс-планировщик, который опрашивает серверы по SSH; сбой сбора не мешает чтению сохранённых данных |
| **`postgres`** | Хранение серверов, временных рядов метрик (TimescaleDB hypertable) и журнала действий |
| **`redis`** | SHA-256 хэши дополнительных API-токенов, кэш валидации и защита от перебора (auth rate limit) |
| **`nginx`** | Reverse proxy, HTTP/HTTPS терминация, HSTS и security headers |
| **`certbot`** | Выпуск и автоматическое продление сертификатов Let's Encrypt каждые 12 часов |

Список активных серверов синхронизируется с планировщиком каждые `15–60` секунд, а период опроса задаётся переменной `COLLECTOR_INTERVAL`.

<a id="ru-features"></a>
## Возможности и собираемые метрики

- **Без установки агентов на серверы:** сбор идёт по SSH с использованием стандартных средств Linux (`/proc`, `ps`, `df`).
- **Временные ряды и агрегация:** хранение истории в TimescaleDB и выдача как сырых точек (`raw`), так и агрегаций (`1m`, `5m`, `15m`, `1h`, `6h`, `1d`) со средними, минимумами, максимумами и процентом доступности.
- **Процессы в реальном времени:** получение списка процессов по SSH по запросу без замусоривания базы данных.
- **Защищённая перезагрузка и аудит:** удалённый reboot через отдельный ключ `X-Action-Key`, ограниченный `/etc/sudoers.d/kernvoxhub-reboot` и журнал всех попыток.
- **Продуманная безопасность:** Fernet-шифрование SSH-секретов, проверка host key (TOFU), rate limiting в Redis и скрытые служебные маршруты (`404` на `/`, `/docs`, `/redoc`, `/openapi.json`).
- **Готовый жизненный цикл:** интерактивный установщик `setup.sh`, системные команды `kernvoxhub` / `kernvoxhub-update` и автонастройка HTTPS.

| Метрика | Источник на удалённом сервере |
| :--- | :--- |
| **CPU** | Два последовательных чтения `/proc/stat` (fallback на `vmstat`) |
| **RAM** | `/proc/meminfo` (расчёт Linux working set) |
| **Диск** | Занятость корневого раздела через `df /` |
| **Сеть (RX/TX)** | Интерфейс по умолчанию из `/proc/net/dev` (fallback — сумма non-loopback) |
| **Uptime** | `/proc/uptime` |
| **Процессы** | `ps aux`, сортировка по CPU (только в реальном времени) |

> Если SSH-подключение collector не удалось, в историю записывается точка с `is_available=false`, чтобы падение сервера отражалось в статистике доступности.

<a id="ru-quickstart"></a>
## Требования и быстрый старт

**Для хоста KernvoxHub:** Linux, Git, Docker Engine, Docker Compose v2 (или `docker-compose`), OpenSSL и домен с DNS-записью (если нужен HTTPS). Установщик умеет сам ставить Docker, Compose и зависимости на Debian/Ubuntu, RHEL/Fedora и Arch-подобных системах.

**Для мониторинга удалённых серверов:** Linux с `/proc`, `ps`, `df`, доступный SSH (по паролю или поддерживаемому Paramiko приватному ключу); `sudo`/root нужен только для функции перезагрузки.

### Установка

```bash
git clone [https://github.com/Vennilay/KernvoxHub.git](https://github.com/Vennilay/KernvoxHub.git)
cd KernvoxHub
chmod +x setup.sh
./setup.sh
```

Установщик проверит зависимости, запросит домен, email, CORS origins и интервал сбора, сгенерирует `.env` со всеми секретами (с правами `600`), соберёт и запустит стек, дождётся готовности всех сервисов, установит CLI-команды `kernvoxhub` и `kernvoxhub-update` в `/usr/local/bin` и при желании настроит Let's Encrypt.

### Проверка после запуска

```bash
kernvoxhub status
docker compose ps
curl [http://127.0.0.1/api/v1/health](http://127.0.0.1/api/v1/health)
```

> [!NOTE]
> `/api/v1/health` доступен без ключа только с loopback (`127.0.0.1`). Для внешнего запроса нужен заголовок `X-API-Key: <API_TOKEN>`. Маршруты `/`, `/docs`, `/redoc` и `/openapi.json` намеренно возвращают `404`.

<a id="ru-cli"></a>
## Секреты, добавление серверов и CLI

### Получение и выпуск токенов

```bash
# Bootstrap API-токен (чтение/управление)
sed -n 's/^API_TOKEN=//p' .env

# Ключ серверных действий (перезагрузка)
sed -n 's/^SERVER_ACTION_TOKEN=//p' .env

# Выпустить дополнительный API-токен (показывается один раз; в Redis хранится только SHA-256)
docker compose exec backend python -m cli.main generate-token
```

### Работа с серверами и обновлениями

```bash
kernvoxhub add-server --test-connection   # Интерактивное добавление + проверка SSH
kernvoxhub list-servers                   # Список активных серверов
kernvoxhub test-server <ID>               # Проверка подключения
kernvoxhub metrics <ID>                   # Последние метрики
kernvoxhub setup-reboot-sudo <ID>         # Настроить безопасный sudoers для перезагрузки
kernvoxhub reboot-server <ID> --yes       # Перезагрузить сервер

kernvoxhub logs [backend]                 # Просмотр логов
kernvoxhub check-update                   # Проверка обновлений
kernvoxhub update                         # Безопасное обновление (есть --skip-git и --with-ssl)
```

Дополнительные команды backend CLI: `docker compose exec backend python -m cli.main status | delete-server <ID> | metrics <ID> --limit 10`. Удаление сервера мягкое (`is_active=false`) — исторические данные в БД не стираются.

<a id="ru-security"></a>
## Безопасность

- **Шифрование секретов (Fernet):** SSH-пароли, приватные ключи и host keys шифруются ключом `ENCRYPTION_KEY` и никогда не возвращаются в ответах API.
- **Защита от MITM (SSH TOFU):** при первом подключении сохраняется host key сервера. Если ключ изменился — соединение прерывается, событие логируется как возможная MITM-атака, а при попытке перезагрузки пишется аудит со статусом `host_key_mismatch`. При смене `host` или `port` через API старый ключ сбрасывается.
- **Разделение прав доступа и rate limiting:** после **10** неудачных попыток авторизации за **60 секунд** IP блокируется в Redis на **5 минут** (при сбое Redis bootstrap-токен `API_TOKEN` продолжает работать).
- **Минимальные права для перезагрузки:** `kernvoxhub setup-reboot-sudo <ID>` создаёт `/etc/sudoers.d/kernvoxhub-reboot` (с проверкой `visudo`), разрешая только `shutdown -r now`, `systemctl reboot` и `reboot`. При отсутствии `SERVER_ACTION_TOKEN` эндпоинт перезагрузки работает в режиме *fail-closed* (`503`).

| Назначение | Заголовок | Переменная `.env` |
| :--- | :---: | :--- |
| Основной доступ к API | `X-API-Key` | `API_TOKEN` или дополнительный токен из Redis |
| Перезагрузка сервера | `X-Action-Key` | `SERVER_ACTION_TOKEN` |
| Внутренняя запись метрик (`POST /metrics`) | `X-Internal-Key` | `INTERNAL_API_KEY` |

<a id="ru-api"></a>
## REST API

### Серверы, метрики и действия

| Метод | Эндпоинт | Назначение |
| :---: | :--- | :--- |
| `GET` / `POST` | `/api/v1/servers` | Список активных серверов (`skip`, `limit`) / создание сервера |
| `GET` / `PUT` / `DELETE` | `/api/v1/servers/{id}` | Получение, частичное обновление или деактивация сервера |
| `GET` / `POST` | `/api/v1/servers/{id}/metrics` | Последние `1–10` измерений / внутренняя запись (`X-Internal-Key`) |
| `GET` | `/api/v1/servers/{id}/metrics/history` | История метрик (`from`, `to`, `limit`) |
| `GET` | `/api/v1/servers/{id}/metrics/timeseries` | Временные ряды (`interval`: `raw`/`1m`..`1d`, `order`, `from`, `to`, `limit` ≤ 2000) |
| `POST` | `/api/v1/servers/{id}/actions/reboot` | Перезагрузка сервера (`X-Action-Key`, ответ `202 Accepted`) |
| `GET` | `/api/v1/servers/{id}/actions?limit=50` | Журнал действий (до `200` записей) |

### Эндпоинты для Android-клиента Kernvox

| Метод | Эндпоинт | Назначение |
| :---: | :--- | :--- |
| `GET` | `/api/v1/android/dashboard` | Сводка по всем активным серверам |
| `GET` | `/api/v1/android/servers/{id}/details` | Карточка сервера и последняя метрика |
| `GET` | `/api/v1/android/servers/{id}/processes?limit=50` | Процессы по SSH в реальном времени (не сохраняются в БД) |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` | История метрик в формате Android-клиента |
| `GET` | `/api/v1/android/servers/{id}/metrics/timeseries` | Агрегированный временной ряд |

<a id="ru-config"></a>
## Конфигурация, HTTPS и бэкапы

| Переменная | Назначение |
| :--- | :--- |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | Пароли базы данных (`kernvox`) и Redis |
| `API_TOKEN`, `SERVER_ACTION_TOKEN`, `INTERNAL_API_KEY`, `API_SECRET` | Ключи доступа к API, действиям и внутренней записи метрик |
| `ENCRYPTION_KEY` | Fernet-ключ для SSH-секретов и host keys |
| `CORS_ORIGINS`, `COLLECTOR_INTERVAL` | Разрешённые origins (через запятую) и период опроса в секундах |
| `DOMAIN`, `EMAIL` | Домен API (или `localhost`) и email для Let's Encrypt |

> [!CAUTION]
> Не меняйте `ENCRYPTION_KEY` без миграции и всегда делайте бэкап `.env` вместе с базой данных — без исходного ключа расшифровать сохранённые SSH-учётные данные невозможно.

- **Настройка/перевыпуск HTTPS:** `chmod +x scripts/ssl-setup.sh && ./scripts/ssl-setup.sh` (проверка DNS, ACME HTTP-01, автоматический редирект на HTTPS + HSTS и отслеживание обновления сертификатов в Nginx).
- **Резервная копия PostgreSQL:**
  ```bash
  docker compose exec -T postgres pg_dump -U kernvox -d kernvox > kernvox-backup.sql
  ```

<a id="ru-dev"></a>
## Технологии, структура и тесты

**Стек:** Python 3.11 · FastAPI & Uvicorn · SQLAlchemy 2 · PostgreSQL 16 + TimescaleDB · Redis 7 · Paramiko · APScheduler · Pydantic 2 · Nginx · Certbot · Docker Compose.

```text
KernvoxHub/
├── backend/
│   ├── api/         # FastAPI middleware и маршруты
│   ├── cli/         # Внутренний backend CLI
│   ├── collector/   # SSH-клиент, сборщик метрик и планировщик
│   ├── models/      # SQLAlchemy-модели и инициализация БД
│   ├── schemas/     # Pydantic-схемы
│   ├── services/    # Токены, Redis, временные ряды и server actions
│   ├── utils/       # Fernet-шифрование
│   └── tests/       # Тесты API, Redis, SSH host key, collector, CLI и скриптов
├── nginx/           # HTTP/HTTPS шаблоны и entrypoint
├── scripts/         # Установщик, SSL и системные launcher-скрипты
├── docker-compose.yml
├── setup.sh
└── update.sh
```

```bash
# Локальный запуск тестов
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pytest -v --cov=backend
```

**Ограничения текущей версии:** ориентирован на Linux-хосты и Linux-серверы; SSH host key принимается по модели TOFU; список процессов не сохраняется в БД; агрегация временных рядов выполняется в приложении; встроенная документация FastAPI отключена; автоматическая ротация `ENCRYPTION_KEY` и отзыв отдельных API-токенов через публичный API пока не реализованы.

<a id="ru-authors"></a>
## Авторы и участники

<table>
  <tr>
    <td align="center" width="220">
      <a href="https://github.com/Vennilay">
        <img src="https://github.com/Vennilay.png?size=100" width="90" height="90" alt="Vennilay" /><br />
        <strong>Vennilay</strong>
      </a><br />
      <sub>Архитектура · FastAPI & Collector · Безопасность · Установщик & SSL · Тесты</sub>
    </td>
    <td align="center" width="220">
      <a href="https://github.com/BAALOC">
        <img src="https://github.com/BAALOC.png?size=100" width="90" height="90" alt="Makar Leonardov" /><br />
        <strong>Makar Leonardov</strong>
      </a><br />
      <sub>Документация · Поддержка интеграции с Android-клиентом</sub>
    </td>
  </tr>
</table>

<p>
  <a href="https://github.com/Vennilay/KernvoxHub/graphs/contributors">
    <img src="https://contrib.rocks/image?repo=Vennilay/KernvoxHub" alt="Contributors" />
  </a>
</p>

[⬆️ Наверх](#top) · [🇬🇧 Перейти к английской версии](#readme-en)

---

<a id="readme-en"></a>
# 🇬🇧 KernvoxHub — Linux Server Monitoring Backend

**KernvoxHub** is a self-hosted backend for centralized Linux server monitoring over SSH—no third-party agents required on target machines. It periodically collects system telemetry, stores historical data in **PostgreSQL / TimescaleDB**, and exposes a hardened REST API for the [**Kernvox**](https://github.com/Vennilay/Kernvox) Android client and custom integrations.

The entire service deploys as a single Docker Compose stack: API, isolated metric collector, database, Redis, Nginx, and automated TLS certificate renewal.

<p align="center">
  <a href="#en-how-it-works">How It Works</a> ·
  <a href="#en-features">Features</a> ·
  <a href="#en-quickstart">Quick Start</a> ·
  <a href="#en-cli">CLI & Operations</a> ·
  <a href="#en-security">Security</a> ·
  <a href="#en-api">REST API</a> ·
  <a href="#en-config">Config & HTTPS</a> ·
  <a href="#en-dev">Development</a> ·
  <a href="#en-authors">Authors</a> ·
  <a href="#readme-ru">🇷🇺 Русский</a>
</p>

<a id="en-how-it-works"></a>
## How It Works

```text
    Kernvox Android Client / API Clients
                    │
                    │ HTTP(S) + X-API-Key / X-Action-Key
                    ▼
           ┌─────────────────┐        ┌─────────────────┐
           │      Nginx      │◄───────┤     Certbot     │
           │  reverse proxy  │        │  Let's Encrypt  │
           └────────┬────────┘        └─────────────────┘
                    │
                    ▼
           ┌─────────────────┐        ┌─────────────────┐
           │ FastAPI backend │◄──────►│     Redis 7     │
           │  REST API & CLI │        │ tokens/rate-lim │
           └────────┬────────┘        └─────────────────┘
                    │
                    ▼
           ┌─────────────────┐
           │  PostgreSQL 16  │
           │  + TimescaleDB  │
           └────────▲────────┘
                    │ writes metrics
           ┌────────┴────────┐
           │    Collector    │  (APScheduler, isolated from API)
           └────────┬────────┘
                    │ SSH (Paramiko + TOFU host key)
                    ▼
            Monitored Linux Servers
```

| Service | Role |
| :--- | :--- |
| **`backend`** | FastAPI REST API, authentication, server management, audit logging, and actions |
| **`collector`** | Standalone SSH polling scheduler; collection failures never interrupt API reads |
| **`postgres`** | Stores servers, metric time series (TimescaleDB hypertable), and action history |
| **`redis`** | SHA-256 hashes of extra API tokens, validation cache, and IP auth rate limiting |
| **`nginx`** | Reverse proxy, HTTP/HTTPS termination, HSTS, and security headers |
| **`certbot`** | Issues and automatically renews Let's Encrypt certificates every 12 hours |

Active servers are synced with the scheduler every `15–60` seconds; polling frequency is controlled via `COLLECTOR_INTERVAL`.

<a id="en-features"></a>
## Features & Collected Metrics

- **Agentless SSH monitoring:** reads metrics directly via standard Linux tools (`/proc`, `ps`, `df`).
- **Time series & rollups:** stores history in TimescaleDB and serves `raw` or aggregated intervals (`1m`, `5m`, `15m`, `1h`, `6h`, `1d`) with avg/min/max values and availability ratio.
- **Live process list:** fetches active processes over SSH on demand without bloating PostgreSQL.
- **Protected reboots & auditing:** requires a separate `X-Action-Key`, scoped `/etc/sudoers.d/kernvoxhub-reboot`, and logs every attempt.
- **Security by default:** Fernet encryption for SSH secrets, TOFU host key verification, Redis-backed rate limiting, and disabled public docs (`404` on `/`, `/docs`, `/redoc`, `/openapi.json`).
- **Production tooling:** interactive `setup.sh` installer, system-wide `kernvoxhub` / `kernvoxhub-update` commands, and automated HTTPS setup.

| Metric | Remote Linux Source |
| :--- | :--- |
| **CPU** | Two sequential `/proc/stat` reads (fallback to `vmstat`) |
| **RAM** | `/proc/meminfo` (Linux working set calculation) |
| **Disk** | Root filesystem usage via `df /` |
| **Network (RX/TX)** | Default interface from `/proc/net/dev` (fallback: sum of non-loopback interfaces) |
| **Uptime** | `/proc/uptime` |
| **Processes** | `ps aux` sorted by CPU (real-time only) |

> When an SSH poll fails, the collector records a sample with `is_available=false` so downtime is accurately tracked.

<a id="en-quickstart"></a>
## Requirements & Quick Start

**KernvoxHub host:** Linux, Git, Docker Engine, Docker Compose v2 (or `docker-compose`), OpenSSL, and a domain with valid DNS records for HTTPS. The installer can automatically install missing Docker, Compose, and system packages on Debian/Ubuntu, RHEL/Fedora-based, and Arch-based distributions.

**Monitored servers:** Linux with `/proc`, `ps`, `df`, SSH connectivity (password or Paramiko-supported private key); `sudo`/root access is only required for remote reboots.

### Installation

```bash
git clone [https://github.com/Vennilay/KernvoxHub.git](https://github.com/Vennilay/KernvoxHub.git)
cd KernvoxHub
chmod +x setup.sh
./setup.sh
```

The installer checks prerequisites, prompts for domain, email, CORS origins, and polling interval, creates a `chmod 600` `.env` file with generated secrets, builds and starts the stack, waits for all services to pass health checks, installs `kernvoxhub` and `kernvoxhub-update` in `/usr/local/bin`, and optionally configures Let's Encrypt.

### Verify Deployment

```bash
kernvoxhub status
docker compose ps
curl [http://127.0.0.1/api/v1/health](http://127.0.0.1/api/v1/health)
```

> [!NOTE]
> `/api/v1/health` is unauthenticated on loopback (`127.0.0.1`) only. External requests require `X-API-Key: <API_TOKEN>`. `/`, `/docs`, `/redoc`, and `/openapi.json` intentionally return `404`.

<a id="en-cli"></a>
## Secrets, Server Management & CLI

### Retrieving & Issuing Tokens

```bash
# Bootstrap API token
sed -n 's/^API_TOKEN=//p' .env

# Separate server action token (reboots)
sed -n 's/^SERVER_ACTION_TOKEN=//p' .env

# Issue an additional API token (shown once; only its SHA-256 hash is stored in Redis)
docker compose exec backend python -m cli.main generate-token
```

### Managing Servers & Updates

```bash
kernvoxhub add-server --test-connection   # Interactive setup + SSH check
kernvoxhub list-servers                   # List active servers
kernvoxhub test-server <ID>               # Verify SSH connectivity
kernvoxhub metrics <ID>                   # Latest metrics
kernvoxhub setup-reboot-sudo <ID>         # Provision restricted sudoers for reboot
kernvoxhub reboot-server <ID> --yes       # Reboot server

kernvoxhub logs [backend]                 # Stream logs
kernvoxhub check-update                   # Check for updates
kernvoxhub update                         # Safe fast-forward update (--skip-git, --with-ssl)
```

Additional backend CLI commands: `docker compose exec backend python -m cli.main status | delete-server <ID> | metrics <ID> --limit 10`. Server deletion is soft (`is_active=false`), preserving historical telemetry in PostgreSQL.

<a id="en-security"></a>
## Security

- **Encrypted credentials (Fernet):** SSH passwords, private keys, and host keys are encrypted using `ENCRYPTION_KEY` and never exposed in API responses.
- **MITM protection (SSH TOFU):** host keys are pinned on first successful connection. A mismatch aborts SSH, logs a potential MITM event, and records a `host_key_mismatch` audit entry on reboot attempts. Updating `host` or `port` via API resets the pinned key.
- **Auth & rate limiting:** **10** failed authentication attempts within **60 seconds** trigger a **5-minute** IP ban in Redis (if Redis is unavailable, the bootstrap `API_TOKEN` remains functional).
- **Least-privilege reboots:** `kernvoxhub setup-reboot-sudo <ID>` writes `/etc/sudoers.d/kernvoxhub-reboot` (validated via `visudo`), allowing only `shutdown -r now`, `systemctl reboot`, and `reboot`. If `SERVER_ACTION_TOKEN` is unset, the reboot endpoint fails closed with `503`.

| Purpose | Header | `.env` Variable |
| :--- | :---: | :--- |
| Standard API access | `X-API-Key` | `API_TOKEN` or issued Redis token |
| Remote server reboot | `X-Action-Key` | `SERVER_ACTION_TOKEN` |
| Internal metric ingestion (`POST /metrics`) | `X-Internal-Key` | `INTERNAL_API_KEY` |

<a id="en-api"></a>
## REST API

### Servers, Metrics & Actions

| Method | Endpoint | Purpose |
| :---: | :--- | :--- |
| `GET` / `POST` | `/api/v1/servers` | List active servers (`skip`, `limit`) / create server |
| `GET` / `PUT` / `DELETE` | `/api/v1/servers/{id}` | Fetch, partially update, or deactivate a server |
| `GET` / `POST` | `/api/v1/servers/{id}/metrics` | Latest `1–10` samples / internal metric write (`X-Internal-Key`) |
| `GET` | `/api/v1/servers/{id}/metrics/history` | Metric history (`from`, `to`, `limit`) |
| `GET` | `/api/v1/servers/{id}/metrics/timeseries` | Raw or rolled-up series (`interval`: `raw`/`1m`..`1d`, `order`, `from`, `to`, `limit` ≤ 2000) |
| `POST` | `/api/v1/servers/{id}/actions/reboot` | Trigger server reboot (`X-Action-Key`, returns `202 Accepted`) |
| `GET` | `/api/v1/servers/{id}/actions?limit=50` | Action audit log (up to `200` entries) |

### Kernvox Android Client Endpoints

| Method | Endpoint | Purpose |
| :---: | :--- | :--- |
| `GET` | `/api/v1/android/dashboard` | Summary across all active servers |
| `GET` | `/api/v1/android/servers/{id}/details` | Server info with its latest metric |
| `GET` | `/api/v1/android/servers/{id}/processes?limit=50` | Real-time SSH process list (not persisted in DB) |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` | History formatted for the Android client |
| `GET` | `/api/v1/android/servers/{id}/metrics/timeseries` | Aggregated time series |

<a id="en-config"></a>
## Configuration, HTTPS & Backups

| Variable | Purpose |
| :--- | :--- |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | PostgreSQL (`kernvox` user) and Redis passwords |
| `API_TOKEN`, `SERVER_ACTION_TOKEN`, `INTERNAL_API_KEY`, `API_SECRET` | API auth, reboot action, and internal metric write keys |
| `ENCRYPTION_KEY` | Fernet key for SSH credentials and host keys |
| `CORS_ORIGINS`, `COLLECTOR_INTERVAL` | Comma-separated allowed origins and polling interval in seconds |
| `DOMAIN`, `EMAIL` | API domain (or `localhost`) and email for Let's Encrypt |

> [!CAUTION]
> Never rotate `ENCRYPTION_KEY` without data migration, and always back up `.env` securely alongside database dumps—encrypted SSH credentials cannot be recovered without the original key.

- **HTTPS setup / renewal:** `chmod +x scripts/ssl-setup.sh && ./scripts/ssl-setup.sh` (validates DNS, runs ACME HTTP-01 challenge, enables HTTPS redirect + HSTS, and watches certificate renewals in Nginx).
- **PostgreSQL backup:**
  ```bash
  docker compose exec -T postgres pg_dump -U kernvox -d kernvox > kernvox-backup.sql
  ```

<a id="en-dev"></a>
## Tech Stack, Layout & Tests

**Stack:** Python 3.11 · FastAPI & Uvicorn · SQLAlchemy 2 · PostgreSQL 16 + TimescaleDB · Redis 7 · Paramiko · APScheduler · Pydantic 2 · Nginx · Certbot · Docker Compose.

```text
KernvoxHub/
├── backend/
│   ├── api/         # FastAPI middleware and routes
│   ├── cli/         # Internal backend CLI
│   ├── collector/   # SSH client, metric collector, and scheduler
│   ├── models/      # SQLAlchemy models and DB initialization
│   ├── schemas/     # Pydantic schemas
│   ├── services/    # Tokens, Redis, time series, and server actions
│   ├── utils/       # Fernet encryption helpers
│   └── tests/       # API, Redis, SSH host key, collector, CLI, and script tests
├── nginx/           # HTTP/HTTPS templates and entrypoint
├── scripts/         # Installer helpers, SSL setup, and system launchers
├── docker-compose.yml
├── setup.sh
└── update.sh
```

```bash
# Run test suite locally
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pytest -v --cov=backend
```

**Current limitations:** targets Linux hosts and Linux servers; SSH host keys use TOFU on first connect; process lists are not persisted in PostgreSQL; time-series aggregation runs in application memory after fetching matching rows; built-in FastAPI docs are disabled; automated `ENCRYPTION_KEY` rotation and per-token revocation via public API are not yet implemented.

<a id="en-authors"></a>
## Authors & Contributors

<table>
  <tr>
    <td align="center" width="220">
      <a href="https://github.com/Vennilay">
        <img src="https://github.com/Vennilay.png?size=100" width="90" height="90" alt="Vennilay" /><br />
        <strong>Vennilay</strong>
      </a><br />
      <sub>Architecture · FastAPI & Collector · Security · Installer & SSL · Tests</sub>
    </td>
    <td align="center" width="220">
      <a href="https://github.com/BAALOC">
        <img src="https://github.com/BAALOC.png?size=100" width="90" height="90" alt="Makar Leonardov" /><br />
        <strong>Makar Leonardov</strong>
      </a><br />
      <sub>Documentation · Android Client Integration Support</sub>
    </td>
  </tr>
</table>

<p>
  <a href="https://github.com/Vennilay/KernvoxHub/graphs/contributors">
    <img src="https://contrib.rocks/image?repo=Vennilay/KernvoxHub" alt="Contributors" />
  </a>
</p>

[⬆️ Back to top](#top) · [🇷🇺 Switch to Russian](#readme-ru)
