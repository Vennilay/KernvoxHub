#!/bin/bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
cd "$ROOT_DIR"

. "${ROOT_DIR}/scripts/lib/env.sh"
. "${ROOT_DIR}/scripts/lib/common.sh"

setup_error_trap

collect_ssl_configuration() {
    if [ ! -f "$ENV_FILE" ]; then
        die ".env файл не найден. Сначала запустите setup.sh."
    fi

    load_env_file "$ENV_FILE"

    while true; do
        if [ -z "${DOMAIN:-}" ] || [ "$DOMAIN" = "localhost" ] || [ "$DOMAIN" = "127.0.0.1" ]; then
            warn "Let's Encrypt не работает для localhost и loopback-адресов."
        fi

        DOMAIN="$(prompt_with_default "📍 Введите публичный домен для сертификата" "${DOMAIN:-}")"
        EMAIL="$(prompt_with_default "📧 Email для SSL уведомлений" "${EMAIL:-admin@example.com}")"

        if (validate_domain_and_email "$DOMAIN" "$EMAIL" "true"); then
            break
        fi

        warn "Исправьте DOMAIN и EMAIL и повторите ввод."
        echo ""
    done

    upsert_env_value "$ENV_FILE" "DOMAIN" "$DOMAIN"
    upsert_env_value "$ENV_FILE" "EMAIL" "$EMAIL"
}

ensure_ssl_runtime() {
    local family=""

    require_sudo_session "SSL setup проверяет Docker daemon и может перезапускать системный Docker. Может потребоваться sudo-пароль."
    install_docker_if_missing

    if [ "$(uname -s)" = "Linux" ]; then
        family="$(detect_linux_family)" || die "Не удалось определить Linux-дистрибутив для подготовки Docker Compose."
        install_compose_if_missing "$family"
    fi

    init_docker_commands
}

verify_tls_deployment() {
    local cert_dir="/etc/letsencrypt/live/${DOMAIN}"
    local nginx_config=""

    info "Проверяю, что сертификат доступен внутри nginx..."
    compose_run exec -T nginx test -f "${cert_dir}/fullchain.pem" || \
        die "Nginx не видит ${cert_dir}/fullchain.pem после выпуска сертификата."
    compose_run exec -T nginx test -f "${cert_dir}/privkey.pem" || \
        die "Nginx не видит ${cert_dir}/privkey.pem после выпуска сертификата."

    info "Проверяю, что nginx загрузил TLS-конфигурацию..."
    nginx_config="$(compose_run exec -T nginx nginx -T 2>/dev/null)" || \
        die "Не удалось получить активную конфигурацию nginx после перезапуска."

    printf '%s\n' "$nginx_config" | grep -Fq "listen 443 ssl;" || \
        die "После настройки SSL nginx не слушает 443/TLS."
    printf '%s\n' "$nginx_config" | grep -Fq "ssl_certificate ${cert_dir}/fullchain.pem;" || \
        die "Активная конфигурация nginx не использует выпущенный сертификат ${DOMAIN}."
}

request_certificate() {
    mkdir -p "${ROOT_DIR}/certbot/www" "${ROOT_DIR}/certbot/conf"

    info "Запускаю backend и nginx для ACME challenge..."
    compose_run up -d backend nginx
    wait_for_service_ready backend 180 || die "Backend не готов к выпуску сертификата."
    wait_for_service_ready nginx 120 || die "Nginx не готов к выпуску сертификата."

    info "Запрашиваю сертификат Let's Encrypt для ${DOMAIN}..."
    compose_run run --rm certbot certonly \
        --non-interactive \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        --keep-until-expiring \
        --preferred-challenges http \
        -d "$DOMAIN"

    info "Перезапускаю nginx для применения TLS-конфигурации..."
    compose_run restart nginx
    wait_for_service_ready nginx 120 || die "Nginx не поднялся после включения TLS."
    verify_tls_deployment
}

main() {
    section "SSL Certificate Setup"
    echo ""

    ensure_ssl_runtime
    collect_ssl_configuration

    echo "📍 Домен: $DOMAIN"
    echo "📧 Email: $EMAIL"
    echo ""

    request_certificate

    echo ""
    section "SSL настроен"
    echo ""
    echo "🔒 HTTPS доступен: https://${DOMAIN}"
    echo "📁 Сертификаты находятся в /etc/letsencrypt/live/${DOMAIN}"
    echo ""
}

main "$@"
