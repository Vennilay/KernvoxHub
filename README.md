# KernvoxHub

**KernvoxHub** — сервер для мониторинга Linux-серверов через SSH с REST API для Kernvox

---

## 📋 Описание

KernvoxHub собирает метрики с серверов по SSH, сохраняет историю в базу данных и предоставляет данные через API:

- **CPU** — загрузка процессора
- **RAM** — использование оперативной памяти
- **Disk** — использование дискового пространства
- **Network** — трафик
- **Processes** — список процессов с потреблением ресурсов
- **Uptime** — время работы системы

---

## 🏗 Архитектура

```
┌─────────────────┐         ┌─────────────────┐
│     Kernvox     │ ────── │   KernvoxHub    │
│                 │  HTTPS  │   (FastAPI)     │
└─────────────────┘         └────────┬────────┘
                              SSH     │
                            ┌─────────┴─────────┐
                            ↓                   ↓
                     ┌──────────┐        ┌──────────┐
                     │ Server 1 │        │ Server N │
                     └──────────┘        └──────────┘
```

### Компоненты

| Сервис | Описание |
|--------|----------|
| **Backend** | FastAPI REST API |
| **PostgreSQL + TimescaleDB** | Хранение метрик |
| **Redis** | Кэширование API токенов |
| **Collector** | Сбор метрик по расписанию (каждые 60 сек) |
| **Nginx** | Reverse proxy, SSL termination |

---

## 🚀 Быстрый старт

### Требования

- Docker 20+
- Docker Compose 2.0+
- Linux / macOS / Windows (WSL)

### Установка

#### 1. Клонирование репозитория

```bash
git clone https://github.com/Vennilay/KernvoxHub.git
cd KernvoxHub
```

#### 2. Настройка

Запустите скрипт автоматической настройки:

```bash
chmod +x setup.sh
./setup.sh
```

Скрипт:
- Проверит наличие Docker и Docker Compose
- Проверит доступность зависимостей для health checks installer'а
- Запросит домен и email для SSL
- Сгенерирует и сохранит секреты в `.env`
- Создаст `.env` файл
- Запустит все сервисы
- Сохранит путь установки и установит глобальную команду `kernvoxhub`

#### Обновление существующей инсталляции

Для обновления уже установленного KernvoxHub:

```bash
kernvoxhub
```

Команда:
- Найдет каталог уже установленного проекта без `cd` в папку с `.env`
- Покажет статус инсталляции и предложит обновление
- По команде `kernvoxhub update` сама подтянет изменения из Git и перезапустит проект
- Проверит существующую инсталляцию и корректность `.env`
- Безопасно подтянет изменения через `git pull --ff-only`
- Пересоберет и перезапустит сервисы через Docker Compose
- Дождется health checks backend, nginx и collector

Дополнительные варианты:

```bash
kernvoxhub help
kernvoxhub status
kernvoxhub update --ref main
kernvoxhub update --with-ssl
kernvoxhub logs backend
./update.sh --install-dir /opt/KernvoxHub --skip-git
```

#### 3. Проверка

```bash
docker-compose ps
```

Все сервисы должны быть в статусе `Up`.

---

## 📡 API Reference

### Аутентификация

Все запросы к API требуют заголовок `X-API-Key`:

```http
X-API-Key: ваш_api_токен
```

Bootstrap-токен генерируется при установке и хранится в `.env` как `API_TOKEN`.
Команда `generate-token` выпускает дополнительные случайные токены независимо от `API_SECRET`.

### Endpoints

#### Основные

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/v1/health` | Проверка работоспособности |
| `GET` | `/api/v1/servers` | Список серверов |
| `POST` | `/api/v1/servers` | Добавить сервер |
| `GET` | `/api/v1/servers/{id}` | Детали сервера |
| `PUT` | `/api/v1/servers/{id}` | Обновить сервер |
| `DELETE` | `/api/v1/servers/{id}` | Удалить сервер |

#### Android API

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/v1/android/dashboard` | Сводка по всем серверам |
| `GET` | `/api/v1/android/servers/{id}/details` | Полная информация о сервере |
| `GET` | `/api/v1/android/servers/{id}/processes` | Запущенные процессы |
| `GET` | `/api/v1/android/servers/{id}/metrics/history` | История метрик |

### Примеры использования

#### Health check

```bash
curl http://localhost/api/v1/health
```

**Ответ:**
```json
{"status": "ok", "version": "1.0.0"}
```

#### Добавить сервер

```bash
curl -X POST http://localhost/api/v1/servers \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ваш_api_ключ" \
  -d '{
    "name": "production-db-01",
    "host": "192.168.1.100",
    "port": 22,
    "username": "root",
    "password": "secret123"
  }'
```

#### Получить список серверов

```bash
curl http://localhost/api/v1/servers \
  -H "X-API-Key: ваш_api_ключ"
```

#### Dashboard (сводка)

```bash
curl http://localhost/api/v1/android/dashboard \
  -H "X-API-Key: ваш_api_ключ"
```

**Ответ:**
```json
{
  "total_servers": 2,
  "active_servers": 2,
  "available_servers": 1,
  "servers": [
    {
      "id": 1,
      "name": "production-db-01",
      "host": "192.168.1.100",
      "is_active": true,
      "is_available": true,
      "cpu_percent": 45.2,
      "ram_percent": 62.5,
      "disk_used_percent": 71.0,
      "last_update": "2026-03-28T10:00:00Z"
    }
  ],
  "timestamp": "2026-03-28T10:00:00Z"
}
```

---

## 🔧 CLI утилиты

KernvoxHub включает CLI для управления:

```bash
# Запуск из контейнера
docker-compose exec backend python -m cli.main --help
```

### Команды

| Команда | Описание |
|---------|----------|
| `generate-token` | Выпуск нового API токена |
| `status` | Статус системы |
| `list-servers` | Список серверов |
| `add-server` | Добавить сервер (интерактивно) |
| `delete-server <ID>` | Удалить сервер |
| `metrics <ID>` | Последние метрики сервера |

### Примеры

```bash
# Статус системы
docker-compose exec backend python -m cli.main status

# Добавить сервер
docker-compose exec backend python -m cli.main add-server

# Просмотр метрик
docker-compose exec backend python -m cli.main metrics 1 --limit 5
```

---

## 🔒 SSL / HTTPS

### Получение сертификата Let's Encrypt

Для production-окружения:

```bash
./scripts/ssl-setup.sh
```

**Требования:**
- Доменное имя, указывающее на ваш сервер
- Открытые порты 80 и 443

---

## 📊 Структура проекта

```
kernvox-hub/
├── backend/
│   ├── api/
│   │   ├── middleware/
│   │   │   └── auth.py          # API Key аутентификация
│   │   └── routes/
│   │       ├── servers.py       # CRUD серверов
│   │       ├── metrics.py       # Метрики
│   │       └── android.py       # Android API
│   ├── cli/
│   │   └── main.py              # CLI утилиты
│   ├── collector/
│   │   ├── ssh_client.py        # SSH подключение
│   │   ├── metrics_fetcher.py   # Сбор метрик
│   │   └── scheduler.py         # Планировщик
│   ├── models/
│   │   ├── database.py          # SQLAlchemy
│   │   ├── server.py            # Модель Server
│   │   └── metric.py            # Модель Metric
│   ├── schemas/
│   │   ├── server.py            # Pydantic схемы
│   │   ├── metric.py
│   │   └── android.py
│   ├── services/
│   │   ├── redis_client.py      # Redis
│   │   └── token_manager.py     # API токены
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api.py
│   │   ├── test_android.py
│   │   └── test_metrics_api.py
│   ├── config.py                # Настройки
│   ├── main.py                  # FastAPI приложение
│   ├── Dockerfile
│   └── requirements.txt
├── nginx/
│   ├── entrypoint.sh            # Рендер и reload nginx-конфига
│   ├── nginx.conf               # HTTP-шаблон nginx
│   └── nginx-https.conf         # HTTPS-шаблон nginx
├── scripts/
│   ├── init_db.sql              # TimescaleDB
│   ├── kernvoxhub               # Основная CLI-команда для оператора
│   ├── kernvoxhub-update        # Глобальный launcher обновления
│   ├── ssl-setup.sh             # Выпуск и проверка SSL
│   └── lib/                     # Общие shell-хелперы installer'а
├── docker-compose.yml
├── setup.sh
├── .env.example
└── README.md
```

---

## 🧪 Тестирование

```bash
# Запуск тестов
docker-compose exec backend pytest

# С покрытием
docker-compose exec backend pytest --cov=backend --cov-report=html
```

---

## 🔐 Безопасность

### Переменные окружения

Все секреты хранятся в `.env` (не добавляется в Git):

```bash
POSTGRES_PASSWORD=secure_random_string
API_SECRET=another_secure_random_string
API_TOKEN=kvx_random_api_token
COLLECTOR_INTERVAL=60
DOMAIN=your-domain.com
EMAIL=admin@example.com
```


## 🛠 Технологический стек

| Компонент | Технология |
|-----------|------------|
| **Язык** | Python 3.11+ |
| **Framework** | FastAPI |
| **База данных** | PostgreSQL 16 + TimescaleDB |
| **Кэш** | Redis 7 |
| **SSH** | Paramiko |
| **Планировщик** | APScheduler |
| **Web-сервер** | Nginx |
| **Контейнеры** | Docker, Docker Compose |

---

## 📝 Лицензия

Проект создан в рамках программы Samsung Academy.

---
