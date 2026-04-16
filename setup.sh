#!/bin/bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
cd "$ROOT_DIR"

. "${ROOT_DIR}/scripts/lib/env.sh"
. "${ROOT_DIR}/scripts/lib/common.sh"
. "${ROOT_DIR}/scripts/lib/stack.sh"

setup_error_trap

generate_alnum_secret() {
    openssl rand -hex 16
}

generate_hex_secret() {
    openssl rand -hex 32
}

generate_api_token_value() {
    printf 'kvx_%s' "$(openssl rand -hex 32)"
}

generate_fernet_key() {
    if command_exists python3; then
        python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null && return 0
    fi

    if command_exists python; then
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null && return 0
    fi

    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
}

load_existing_env() {
    if [ -f "$ENV_FILE" ]; then
        load_env_file "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        success "Найден существующий .env"
        echo ""
    fi
}

collect_configuration() {
    local default_cors=""

    section "KernvoxHub Setup"
    echo ""

    while true; do
        DOMAIN="$(prompt_with_default "📍 Домен для API (например: api.example.com или localhost)" "${DOMAIN:-localhost}")"
        EMAIL="$(prompt_with_default "📧 Email для SSL уведомлений (например: admin@example.com)" "${EMAIL:-admin@example.com}")"

        if [ -z "$DOMAIN" ]; then
            warn "Домен не может быть пустым."
            continue
        fi

        if [ -z "$EMAIL" ]; then
            warn "Email не может быть пустым."
            continue
        fi

        if (validate_domain_and_email "$DOMAIN" "$EMAIL" "false"); then
            break
        fi

        warn "Исправьте DOMAIN и EMAIL и повторите ввод."
        echo ""
    done

    while true; do
        INTERVAL="$(prompt_with_default "⏱ Интервал опроса серверов (секунды)" "${COLLECTOR_INTERVAL:-60}")"

        if [[ "$INTERVAL" =~ ^[0-9]+$ ]] && [ "$INTERVAL" -gt 0 ]; then
            break
        fi

        warn "Интервал должен быть положительным целым числом."
    done

    if [ "$DOMAIN" = "localhost" ] || [ "$DOMAIN" = "127.0.0.1" ]; then
        default_cors="http://localhost,http://127.0.0.1,http://localhost:3000,http://127.0.0.1:3000"
    else
        default_cors="https://${DOMAIN}"
    fi
    CORS_ORIGINS="$(prompt_with_default "🌐 CORS origins (через запятую)" "${CORS_ORIGINS:-$default_cors}")"

    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        POSTGRES_PASSWORD="$(prompt_secret_with_default "🔑 Пароль для PostgreSQL")"
        POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(generate_alnum_secret)}"
    fi

    if [ -z "${API_SECRET:-}" ]; then
        API_SECRET="$(prompt_secret_with_default "🔑 API Secret")"
        API_SECRET="${API_SECRET:-$(generate_hex_secret)}"
    fi

    if [ -z "${API_TOKEN:-}" ]; then
        API_TOKEN="$(generate_api_token_value)"
    fi

    if [ -z "${ENCRYPTION_KEY:-}" ]; then
        ENCRYPTION_KEY="$(generate_fernet_key)"
    fi

    if [ -z "${REDIS_PASSWORD:-}" ]; then
        REDIS_PASSWORD="$(generate_alnum_secret)"
    fi

    if [ -z "${INTERNAL_API_KEY:-}" ]; then
        INTERNAL_API_KEY="$(generate_hex_secret)"
    fi

    SSL_ENABLE="n"
    if [ "$DOMAIN" != "localhost" ] && [ "$DOMAIN" != "127.0.0.1" ]; then
        if confirm "🔒 Получить или обновить SSL-сертификат Let's Encrypt после запуска?" "n"; then
            SSL_ENABLE="y"
        fi
    else
        warn "API будет запущен по HTTP."
    fi
}

write_env_file() {
    info "Обновляю файл окружения..."

    upsert_env_value "$ENV_FILE" "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD"
    upsert_env_value "$ENV_FILE" "API_SECRET" "$API_SECRET"
    upsert_env_value "$ENV_FILE" "API_TOKEN" "$API_TOKEN"
    upsert_env_value "$ENV_FILE" "ENCRYPTION_KEY" "$ENCRYPTION_KEY"
    upsert_env_value "$ENV_FILE" "REDIS_PASSWORD" "$REDIS_PASSWORD"
    upsert_env_value "$ENV_FILE" "INTERNAL_API_KEY" "$INTERNAL_API_KEY"
    upsert_env_value "$ENV_FILE" "CORS_ORIGINS" "$CORS_ORIGINS"
    upsert_env_value "$ENV_FILE" "COLLECTOR_INTERVAL" "$INTERVAL"
    upsert_env_value "$ENV_FILE" "DOMAIN" "$DOMAIN"
    upsert_env_value "$ENV_FILE" "EMAIL" "$EMAIL"

    chmod 600 "$ENV_FILE"
    success ".env обновлён и защищён правами 600."
}

start_stack() {
    info "Создаю рабочие директории certbot..."
    mkdir -p "${ROOT_DIR}/certbot/www" "${ROOT_DIR}/certbot/conf"
    chmod 755 "${ROOT_DIR}/certbot" "${ROOT_DIR}/certbot/www" "${ROOT_DIR}/certbot/conf" 2>/dev/null || true

    info "Запускаю сервисы Docker Compose..."
    compose_run up -d --build

    info "Ожидаю готовность PostgreSQL..."
    wait_for_service_ready postgres 180 || die "PostgreSQL не перешёл в состояние ready."
    success "PostgreSQL готов."

    info "Ожидаю готовность Redis..."
    wait_for_service_ready redis 120 || die "Redis не перешёл в состояние ready."
    success "Redis готов."

    info "Ожидаю готовность backend..."
    wait_for_service_ready backend 180 || die "Backend не перешёл в состояние ready."
    success "Backend готов."

    info "Ожидаю готовность nginx..."
    wait_for_service_ready nginx 120 || die "Nginx не перешёл в состояние ready."
    success "Nginx готов."

    info "Проверяю локальный health endpoint API..."
    wait_for_http_endpoint "http://127.0.0.1/api/v1/health" 120 || die "API не ответил на локальный health check."
    success "API отвечает на health check."

    info "Проверяю состояние collector..."
    wait_for_service_ready collector 120 || die "Collector не запустился."
    success "Collector запущен."
}

print_runtime_info() {
    info "Docker: $(docker_run --version)"
    info "Docker Compose: $(compose_run version --short 2>/dev/null || compose_run version | head -n 1)"
}

main() {
    local compose_cmd_string=""

    section "KernvoxHub Installer"
    echo ""

    ensure_host_dependencies
    print_runtime_info
    echo ""

    load_existing_env
    ensure_existing_installation_secrets
    collect_configuration
    compose_cmd_string="$(render_command "${COMPOSE_CMD[@]}")"
    echo ""
    write_env_file
    echo ""
    start_stack
    echo ""

    if [ "$SSL_ENABLE" = "y" ]; then
        info "Запускаю настройку SSL..."
        "${ROOT_DIR}/scripts/ssl-setup.sh"
        echo ""
    fi

    echo "📊 Статус сервисов:"
    compose_run ps
    echo ""

    section "Установка завершена"
    echo ""
    echo "📍 API: http://${DOMAIN}"
    echo "📚 Документация: http://${DOMAIN}/docs"
    if [ "$SSL_ENABLE" = "y" ]; then
        echo "🔒 HTTPS: https://${DOMAIN}"
    fi
    echo ""
    echo "Выпустить новый API-токен:"
    echo "  ${compose_cmd_string}exec backend python -m cli.main generate-token"
    echo ""
    echo "Добавить сервер интерактивно:"
    echo "  ${compose_cmd_string}exec backend python -m cli.main add-server"
    echo ""
    echo "Посмотреть список серверов:"
    echo "  ${compose_cmd_string}exec backend python -m cli.main list-servers"
    echo ""
    echo "Для остановки:"
    echo "  ${compose_cmd_string}down"
    echo ""
    echo "Для просмотра логов:"
    echo "  ${compose_cmd_string}logs -f"
    echo ""
}

main "$@"
