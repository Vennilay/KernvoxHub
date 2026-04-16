#!/bin/bash

PROTECTED_ENV_KEYS=(
    POSTGRES_PASSWORD
    API_SECRET
    API_TOKEN
    ENCRYPTION_KEY
    REDIS_PASSWORD
    INTERNAL_API_KEY
)

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
        die "Найдена существующая установка, но в ${ENV_FILE} отсутствуют критичные значения: ${missing_keys[*]}. Восстановите прежний .env и повторите запуск, иначе установщик сгенерирует новые секреты и сломает доступ к текущим данным."
    fi
}
