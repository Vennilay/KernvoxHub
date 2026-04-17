#!/bin/bash

PROTECTED_ENV_KEYS=(
    POSTGRES_PASSWORD
    API_SECRET
    API_TOKEN
    ENCRYPTION_KEY
    REDIS_PASSWORD
    INTERNAL_API_KEY
)

KERNVOX_MAIN_COMMAND_NAME="kernvoxhub"
KERNVOX_UPDATE_LAUNCHER_NAME="kernvoxhub-update"

ensure_host_dependencies() {
    local family=""
    install_docker_if_missing

    if [ "$(uname -s)" = "Linux" ]; then
        family="$(detect_linux_family)" || die "Не удалось определить Linux-дистрибутив для установки OpenSSL."
        install_openssl_if_missing "$family"
        install_http_probe_client_if_missing "$family"
        install_compose_if_missing "$family"
    fi

    command_exists openssl || die "OpenSSL не найден. Установите OpenSSL и повторите запуск."
    command_exists curl || command_exists wget || command_exists python3 || command_exists python || \
        die "Не найден curl, wget или Python. Один из этих инструментов нужен для health checks installer'а."
    ensure_docker_group_membership
    init_docker_commands
}

normalize_directory_path() {
    local dir="$1"

    [ -n "$dir" ] || return 1
    (
        cd "$dir" 2>/dev/null && pwd -P
    )
}

installation_state_file_path() {
    if [ -n "${KERNVOX_STATE_FILE:-}" ]; then
        printf '%s' "$KERNVOX_STATE_FILE"
        return 0
    fi

    [ -n "${HOME:-}" ] || return 1
    printf '%s/%s/install-dir' "${XDG_CONFIG_HOME:-${HOME}/.config}" "kernvoxhub"
}

remember_installation_root() {
    local install_root="$1"
    local normalized_root=""
    local state_file=""
    local state_dir=""

    normalized_root="$(normalize_directory_path "$install_root")" || {
        warn "Не удалось нормализовать путь инсталляции '${install_root}'."
        return 1
    }

    state_file="$(installation_state_file_path)" || {
        warn "Не удалось определить путь для сохранения данных инсталляции."
        return 1
    }
    state_dir="$(dirname "$state_file")"

    mkdir -p "$state_dir" || {
        warn "Не удалось создать каталог ${state_dir} для данных инсталляции."
        return 1
    }

    printf '%s\n' "$normalized_root" > "$state_file" || {
        warn "Не удалось сохранить путь инсталляции в ${state_file}."
        return 1
    }

    chmod 600 "$state_file" 2>/dev/null || true
    success "Путь инсталляции сохранён в ${state_file}."
}

install_launcher() {
    local launcher_name="$1"
    local launcher_source="${ROOT_DIR}/scripts/${launcher_name}"
    local launcher_target="/usr/local/bin/${launcher_name}"

    if [ ! -f "$launcher_source" ]; then
        warn "Файл launcher'а ${launcher_source} не найден; команда ${launcher_name} не установлена."
        return 1
    fi

    if [ -f "$launcher_target" ] && cmp -s "$launcher_source" "$launcher_target"; then
        success "Команда ${launcher_name} уже установлена в ${launcher_target}."
        return 0
    fi

    run_privileged install -m 755 "$launcher_source" "$launcher_target" || {
        warn "Не удалось установить команду ${launcher_name}."
        return 1
    }

    success "Команда ${launcher_name} установлена в ${launcher_target}."
}

configure_update_command() {
    remember_installation_root "$ROOT_DIR" || true
    install_launcher "$KERNVOX_MAIN_COMMAND_NAME" || true
    install_launcher "$KERNVOX_UPDATE_LAUNCHER_NAME" || true
}

default_compose_project_name() {
    local project_name=""
    project_name="$(basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]+//g')"
    printf '%s' "${COMPOSE_PROJECT_NAME:-$project_name}"
}

existing_installation_detected() {
    local project_name=""
    local resource=""
    local -a container_names=(
        kernvox-backend
        kernvox-postgres
        kernvox-redis
        kernvox-nginx
        kernvox-collector
    )
    local -a volume_names=()

    project_name="$(default_compose_project_name)"
    volume_names=(
        "${project_name}_postgres_data"
        "${project_name}_redis_data"
        "${project_name}_certbot_data"
    )

    for resource in "${container_names[@]}"; do
        if docker_run container inspect "$resource" >/dev/null 2>&1; then
            return 0
        fi
    done

    for resource in "${volume_names[@]}"; do
        if docker_run volume inspect "$resource" >/dev/null 2>&1; then
            return 0
        fi
    done

    return 1
}

ensure_existing_installation_secrets() {
    local key=""
    local missing_keys=()

    for key in "${PROTECTED_ENV_KEYS[@]}"; do
        if [ -z "${!key:-}" ]; then
            missing_keys+=("$key")
        fi
    done

    [ "${#missing_keys[@]}" -eq 0 ] && return 0

    if existing_installation_detected; then
        die "Найдена существующая инсталляция, но в ${ENV_FILE} отсутствуют критичные значения: ${missing_keys[*]}. Восстановите прежний .env и повторите запуск, иначе installer сгенерирует новые секреты и сломает доступ к текущим данным."
    fi
}
