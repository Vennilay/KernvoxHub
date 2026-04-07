#!/bin/bash

set -e

echo "========================================"
echo "  KernvoxHub Setup Script"
echo "========================================"
echo ""

# Проверка требований
echo "📋 Проверка требований..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker не найден. Установите Docker."
    exit 1
fi
echo "✅ Docker: $(docker --version)"

COMPOSE_CMD=""

# Проверяем docker compose (v2)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
# Проверяем docker-compose (v1)
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
fi

if [ -z "$COMPOSE_CMD" ]; then
    echo "❌ Docker Compose не найден. Установите Docker Compose."
    exit 1
fi

echo "✅ Docker Compose: $($COMPOSE_CMD version --short 2>/dev/null || $COMPOSE_CMD version | head -1)"

echo ""

# Запрос данных у пользователя
echo "⚙️  Настройка KernvoxHub"
echo ""

read -p "📍 Домен для API (например: api.example.com или localhost): " DOMAIN
DOMAIN=${DOMAIN:-localhost}

read -p "📧 Email для SSL уведомлений (например: admin@example.com): " EMAIL
EMAIL=${EMAIL:-admin@example.com}

read -p "🔒 Получить SSL сертификат Let's Encrypt? (y/n) [n]: " SSL_ENABLE
SSL_ENABLE=${SSL_ENABLE:-n}

if [ "$SSL_ENABLE" == "y" ] || [ "$SSL_ENABLE" == "Y" ]; then
    if [ "$DOMAIN" == "localhost" ] || [ "$DOMAIN" == "127.0.0.1" ]; then
        echo "⚠️  SSL сертификаты Let's Encrypt работают только с публичными доменами."
        echo "   Для локальной разработки используйте self-signed сертификаты."
        SSL_ENABLE="n"
    fi
fi

read -p "⏱ Интервал опроса серверов (секунды) [60]: " INTERVAL
INTERVAL=${INTERVAL:-60}

read -p "🔑 Пароль для PostgreSQL [автогенерация]: " POSTGRES_PASSWORD
if [ -z "$POSTGRES_PASSWORD" ]; then
    POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    echo "✅ Сгенерирован пароль PostgreSQL: $POSTGRES_PASSWORD"
fi

read -p "🔑 API Secret [автогенерация]: " API_SECRET
if [ -z "$API_SECRET" ]; then
    API_SECRET=$(openssl rand -hex 32)
    echo "✅ Сгенерирован API Secret: $API_SECRET"
fi

# Генерация ENCRYPTION_KEY (Fernet key)
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null)
if [ -z "$ENCRYPTION_KEY" ]; then
    # Fallback: генерируем через openssl + base64 (Fernet key = 32 random bytes, base64)
    ENCRYPTION_KEY=$(openssl rand -base64 32 | head -c 44)
    ENCRYPTION_KEY="${ENCRYPTION_KEY}="
    echo "⚠️  ENCRYPTION_KEY сгенерирован через openssl (убедитесь, что cryptography установлен)"
else
    echo "✅ Сгенерирован ENCRYPTION_KEY"
fi

echo ""

# Создание .env файла
echo "📝 Создание файла окружения..."

cat > .env << EOF
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
API_SECRET=$API_SECRET
ENCRYPTION_KEY=$ENCRYPTION_KEY
COLLECTOR_INTERVAL=$INTERVAL
DOMAIN=$DOMAIN
EMAIL=$EMAIL
EOF

echo "✅ .env файл создан"
echo ""

# Запуск Docker Compose
echo "🐳 Запуск сервисов..."

$COMPOSE_CMD up -d

echo ""
echo "⏳ Ожидание запуска сервисов (30 секунд)..."
sleep 30

# Проверка статуса
echo ""
echo "📊 Статус сервисов:"
$COMPOSE_CMD ps

echo ""
echo "========================================"
echo "  ✅ Установка завершена!"
echo "========================================"
echo ""
echo "📍 API доступен: http://${DOMAIN}"
echo "📚 Документация: http://${DOMAIN}/docs"
echo ""
echo "🔑 API Secret (сохраните!):"
echo "   $API_SECRET"
echo ""
echo "🔑 PostgreSQL пароль:"
echo "   $POSTGRES_PASSWORD"
echo ""
echo "🔐 ENCRYPTION_KEY (сохраните!):"
echo "   $ENCRYPTION_KEY"
echo ""
echo "Пример запроса к API:"
echo "  curl -H \"X-API-Key: kvx_${API_SECRET:0:16}...\" http://${DOMAIN}/api/v1/health"
echo ""

if [ "$SSL_ENABLE" == "y" ] || [ "$SSL_ENABLE" == "Y" ]; then
    echo "🔒 Настройка SSL сертификата..."
    echo ""
    ./scripts/ssl-setup.sh
    echo ""
    echo "🔒 HTTPS доступен: https://${DOMAIN}"
else
    echo "💡 Для настройки SSL выполните: ./scripts/ssl-setup.sh"
fi

echo ""
echo "Для остановки: $COMPOSE_CMD down"
echo "Для просмотра логов: $COMPOSE_CMD logs -f"
echo ""
