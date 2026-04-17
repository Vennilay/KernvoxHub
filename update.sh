#!/bin/bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
INSTALL_DIR_OVERRIDE=""
UPDATE_REF=""
SKIP_GIT_UPDATE="n"
RUN_SSL_UPDATE="n"
cd "$ROOT_DIR"

. "${ROOT_DIR}/scripts/lib/env.sh"
. "${ROOT_DIR}/scripts/lib/common.sh"
. "${ROOT_DIR}/scripts/lib/stack.sh"

setup_error_trap

usage() {
    cat <<'EOF'
Usage: ./update.sh [options]

Options:
  --install-dir <path> Use an installed KernvoxHub directory from any current path.
  --ref <git-ref>   Switch to a branch/tag/commit before restart.
  --skip-git        Do not run git fetch/pull; only rebuild and restart services.
  --with-ssl        Run scripts/ssl-setup.sh after update.
  --help            Show this help.
EOF
}

load_existing_env() {
    [ -f "$ENV_FILE" ] || die ".env файл не найден. Сначала запустите setup.sh."
    load_env_file "$ENV_FILE"
    chmod 600 "$ENV_FILE" 2>/dev/null || warn "Не удалось обновить права доступа для ${ENV_FILE}; продолжаю с текущими правами."
}

print_runtime_info() {
    info "Docker: $(docker_run --version)"
    info "Docker Compose: $(compose_run version --short 2>/dev/null || compose_run version | head -n 1)"
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --install-dir)
                [ "$#" -ge 2 ] || die "Флаг --install-dir требует путь к каталогу инсталляции."
                INSTALL_DIR_OVERRIDE="$2"
                shift 2
                ;;
            --ref)
                [ "$#" -ge 2 ] || die "Флаг --ref требует значение."
                UPDATE_REF="$2"
                shift 2
                ;;
            --skip-git)
                SKIP_GIT_UPDATE="y"
                shift
                ;;
            --with-ssl)
                RUN_SSL_UPDATE="y"
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                die "Неизвестный аргумент: $1"
                ;;
        esac
    done
}

apply_installation_root_override() {
    [ -n "$INSTALL_DIR_OVERRIDE" ] || return 0

    ROOT_DIR="$(normalize_directory_path "$INSTALL_DIR_OVERRIDE")" || \
        die "Каталог инсталляции '${INSTALL_DIR_OVERRIDE}' не найден или недоступен."
    [ -f "${ROOT_DIR}/docker-compose.yml" ] || \
        die "В ${ROOT_DIR} не найден docker-compose.yml. Укажите каталог установленного KernvoxHub."
    [ -f "${ROOT_DIR}/update.sh" ] || \
        die "В ${ROOT_DIR} не найден update.sh. Укажите каталог установленного KernvoxHub."

    ENV_FILE="${ROOT_DIR}/.env"
    cd "$ROOT_DIR"
}

ensure_existing_installation() {
    existing_installation_detected || die "Существующая инсталляция KernvoxHub не найдена. Для первого запуска используйте ./setup.sh."
}

ensure_clean_git_worktree() {
    git diff --quiet --ignore-submodules -- || die "Рабочее дерево Git содержит незакоммиченные изменения. Зафиксируйте или уберите их перед обновлением."
    git diff --cached --quiet --ignore-submodules -- || die "В индексе Git есть незакоммиченные изменения. Зафиксируйте или уберите их перед обновлением."
}

checkout_update_ref() {
    [ -n "$UPDATE_REF" ] || return 0
    info "Переключаю репозиторий на ${UPDATE_REF}..."
    git checkout "$UPDATE_REF"
}

update_source_code() {
    [ "$SKIP_GIT_UPDATE" = "y" ] && return 0

    command_exists git || die "Git не найден. Установите Git или используйте ./update.sh --skip-git."
    ensure_clean_git_worktree

    info "Получаю последние изменения из origin..."
    git fetch --tags --prune origin
    checkout_update_ref

    if [ -n "$UPDATE_REF" ]; then
        if git symbolic-ref --quiet HEAD >/dev/null 2>&1; then
            info "Подтягиваю обновления для ветки $(git branch --show-current)..."
            git pull --ff-only origin "$(git branch --show-current)"
        else
            info "Репозиторий переведен на detached HEAD ${UPDATE_REF}; пропускаю git pull."
        fi
        return 0
    fi

    if git symbolic-ref --quiet HEAD >/dev/null 2>&1; then
        info "Подтягиваю обновления для текущей ветки $(git branch --show-current)..."
        git pull --ff-only
    else
        warn "Репозиторий находится в detached HEAD; git pull пропущен. Используйте --ref <branch> для переключения на ветку."
    fi
}

restart_stack() {
    info "Пересобираю и перезапускаю сервисы Docker Compose..."
    compose_run up -d --build --remove-orphans

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

maybe_update_ssl() {
    [ "$RUN_SSL_UPDATE" = "y" ] || return 0
    info "Запускаю обновление SSL-конфигурации..."
    "${ROOT_DIR}/scripts/ssl-setup.sh"
}

main() {
    local compose_cmd_string=""

    parse_args "$@"
    apply_installation_root_override

    section "KernvoxHub Update"
    echo ""

    ensure_host_dependencies
    print_runtime_info
    echo ""

    load_existing_env
    ensure_existing_installation
    ensure_existing_installation_secrets
    update_source_code
    echo ""
    restart_stack
    echo ""
    configure_update_command
    echo ""
    maybe_update_ssl

    compose_cmd_string="$(render_command "${COMPOSE_CMD[@]}")"

    echo "📊 Статус сервисов:"
    compose_run ps
    echo ""

    section "Обновление завершено"
    echo ""
    echo "📍 API: http://${DOMAIN:-localhost}"
    echo "📚 Документация: http://${DOMAIN:-localhost}/docs"
    if [ "$RUN_SSL_UPDATE" = "y" ]; then
        echo "🔒 HTTPS: https://${DOMAIN}"
    fi
    echo ""
    echo "Основная команда управления:"
    echo "  ${KERNVOX_MAIN_COMMAND_NAME}"
    echo ""
    echo "Следующее обновление:"
    echo "  ${KERNVOX_MAIN_COMMAND_NAME} update"
    echo ""
    echo "Текущий коммит:"
    echo "  $(git rev-parse --short HEAD 2>/dev/null || echo 'неизвестно')"
    echo ""
    echo "Для просмотра логов:"
    echo "  ${compose_cmd_string}logs -f"
    echo ""
}

main "$@"
