#!/bin/bash

set -e

echo "========================================"
echo "  SSL Certificate Setup (Let's Encrypt)"
echo "========================================"
echo ""

if ! command -v docker &> /dev/null; then
    echo "❌ Docker не найден."
    exit 1
fi

COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
fi

if [ -z "$COMPOSE_CMD" ]; then
    echo "❌ Docker Compose не найден."
    exit 1
fi

if [ ! -f .env ]; then
    echo "❌ .env файл не найден. Запустите setup.sh сначала."
    exit 1
fi

source .env

if [ -z "$DOMAIN" ] || [ "$DOMAIN" == "localhost" ]; then
    echo "⚠️  SSL сертификаты Let's Encrypt работают только с публичными доменами."
    echo "   Для localhost используйте self-signed сертификаты."
    echo ""
    read -p "📍 Введите ваш домен: " DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo "❌ Домен не введён."
        exit 1
    fi
    sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env
fi

echo "📍 Домен: $DOMAIN"
echo "📧 Email: $EMAIL"
echo ""

mkdir -p certbot/www
mkdir -p certbot/conf

echo "🚀 Запуск Certbot для получения сертификата..."

$COMPOSE_CMD run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Сертификат успешно получен!"
    echo ""
    echo "📁 Сертификаты сохранены в:"
    echo "   /etc/letsencrypt/live/"
    echo ""
    echo "🔄 Перезапуск nginx..."
    $COMPOSE_CMD restart nginx
    echo ""
    echo "========================================"
    echo "  ✅ SSL настроен!"
    echo "========================================"
    echo ""
    echo "🔒 HTTPS доступен: https://$DOMAIN"
    echo ""
else
    echo "❌ Не удалось получить сертификат."
    echo "   Проверьте, что домен указывает на ваш сервер."
    exit 1
fi
