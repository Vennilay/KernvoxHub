#!/bin/bash

section() {
    echo "========================================"
    echo "  $1"
    echo "========================================"
}

info() {
    echo "ℹ️  $*"
}

success() {
    echo "✅ $*"
}

warn() {
    echo "⚠️  $*"
}

error() {
    echo "❌ $*" >&2
}

die() {
    error "$*"
    exit 1
}

handle_unexpected_error() {
    local line_number="$1"
    error "Скрипт завершился с ошибкой на строке ${line_number}. Проверьте сообщения выше."
}

setup_error_trap() {
    trap 'handle_unexpected_error "${LINENO}"' ERR
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

ensure_sudo() {
    if [ "${EUID}" -eq 0 ]; then
        return 0
    fi

    command_exists sudo || die "Для этого шага нужны права root или установленный sudo."
}

require_sudo_session() {
    local reason="$1"

    [ "$(uname -s)" = "Linux" ] || return 0

    if [ "${EUID}" -eq 0 ]; then
        return 0
    fi

    ensure_sudo
    info "${reason}"
    sudo -v || die "Не удалось подтвердить sudo-права. Запустите скрипт от пользователя с sudo-доступом."
}

run_privileged() {
    if [ "${EUID}" -eq 0 ]; then
        "$@"
    else
        ensure_sudo
        sudo "$@"
    fi
}

confirm() {
    local prompt_text="$1"
    local default_answer="${2:-y}"
    local answer=""
    local prompt_suffix="[Y/n]"

    if [ "$default_answer" = "n" ]; then
        prompt_suffix="[y/N]"
    fi

    while true; do
        read -r -p "${prompt_text} ${prompt_suffix}: " answer || answer="$default_answer"
        answer="${answer:-$default_answer}"

        case "$answer" in
            y|Y|yes|YES)
                return 0
                ;;
            n|N|no|NO)
                return 1
                ;;
            *)
                warn "Ответьте y или n."
                ;;
        esac
    done
}

prompt_with_default() {
    local prompt_text="$1"
    local default_value="$2"
    local input_value=""

    read -r -p "${prompt_text} [${default_value}]: " input_value || die "Ввод прерван пользователем."
    printf '%s' "${input_value:-$default_value}"
}

prompt_secret_with_default() {
    local prompt_text="$1"
    local input_value=""

    read -r -s -p "${prompt_text} [Enter для автогенерации]: " input_value || die "Ввод прерван пользователем."
    echo ""
    printf '%s' "$input_value"
}

render_command() {
    printf '%q ' "$@"
}

require_non_empty() {
    local value="$1"
    local message="$2"

    [ -n "$value" ] || die "$message"
}

require_positive_integer() {
    local value="$1"
    local field_name="$2"

    [[ "$value" =~ ^[0-9]+$ ]] || die "${field_name} должен быть положительным целым числом."
    [ "$value" -gt 0 ] || die "${field_name} должен быть больше нуля."
}

is_ipv4_address() {
    [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

validate_email_syntax() {
    local email="$1"

    [[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ ]]
}

validate_domain_syntax() {
    local domain="$1"
    local label=""
    local total_length="${#domain}"

    [ "$total_length" -ge 1 ] && [ "$total_length" -le 253 ] || return 1
    [[ "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || return 1
    [[ "$domain" == *.* ]] || return 1
    [[ "$domain" != .* ]] || return 1
    [[ "$domain" != *. ]] || return 1
    [[ "$domain" != *..* ]] || return 1

    IFS='.' read -r -a domain_labels <<< "$domain"
    for label in "${domain_labels[@]}"; do
        [ -n "$label" ] || return 1
        [ "${#label}" -le 63 ] || return 1
        [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
    done
}

resolve_domain_ips() {
    local domain="$1"

    if command_exists getent; then
        getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u
    elif command_exists host; then
        host "$domain" 2>/dev/null | awk '/has address/ {print $4} /has IPv6 address/ {print $5}' | sort -u
    elif command_exists dig; then
        dig +short A "$domain" 2>/dev/null
        dig +short AAAA "$domain" 2>/dev/null
    elif command_exists python3; then
        python3 - <<PY
import socket
for item in sorted({entry[4][0] for entry in socket.getaddrinfo("${domain}", None)}):
    print(item)
PY
    fi
}

detect_local_ips() {
    if command_exists hostname; then
        hostname -I 2>/dev/null | tr ' ' '\n' | sed '/^$/d'
    fi

    if command_exists ip; then
        ip -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
    elif command_exists ifconfig; then
        ifconfig 2>/dev/null | awk '/inet / {print $2}'
    fi
}

detect_public_ipv4() {
    local endpoint=""

    for endpoint in \
        "https://api.ipify.org" \
        "https://ifconfig.me/ip" \
        "https://ipinfo.io/ip"
    do
        if command_exists curl; then
            curl --silent --show-error --fail --max-time 5 "$endpoint" 2>/dev/null | tr -d '\r' && return 0
        elif command_exists wget; then
            wget -q -O - "$endpoint" 2>/dev/null | tr -d '\r' && return 0
        elif command_exists python3; then
            python3 - <<PY 2>/dev/null && return 0
from urllib.request import urlopen
print(urlopen("${endpoint}", timeout=5).read().decode().strip())
PY
        fi
    done

    return 1
}

domain_points_to_host() {
    local domain="$1"
    local resolved_ips="$2"
    local current_public_ip="${3:-}"
    local local_ips=""
    local candidate=""

    if [ -n "$current_public_ip" ]; then
        while IFS= read -r candidate; do
            [ -n "$candidate" ] || continue
            [ "$candidate" = "$current_public_ip" ] && return 0
        done <<< "$resolved_ips"
    fi

    local_ips="$(detect_local_ips | sort -u || true)"
    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        if printf '%s\n' "$local_ips" | grep -Fxq "$candidate"; then
            return 0
        fi
    done <<< "$resolved_ips"

    return 1
}

validate_domain_and_email() {
    local domain="$1"
    local email="$2"
    local require_public_domain="${3:-false}"
    local resolved_ips=""
    local public_ip=""

    validate_email_syntax "$email" || die "Email '${email}' имеет некорректный формат."

    if [ "$domain" = "localhost" ] || [ "$domain" = "127.0.0.1" ]; then
        [ "$require_public_domain" = "true" ] && die "Для этой операции нужен публичный домен, а не localhost."
        return 0
    fi

    validate_domain_syntax "$domain" || die "Домен '${domain}' имеет некорректный формат."
    ! is_ipv4_address "$domain" || die "Укажите доменное имя вместо IPv4-адреса."

    resolved_ips="$(resolve_domain_ips "$domain" | sed '/^$/d' | sort -u || true)"
    [ -n "$resolved_ips" ] || die "Домен '${domain}' не резолвится в DNS. Проверьте запись A/AAAA."

    success "DNS для ${domain}: $(printf '%s' "$resolved_ips" | paste -sd ', ' -)"

    public_ip="$(detect_public_ipv4 | tr -d '\n' || true)"
    if [ -n "$public_ip" ] && ! is_ipv4_address "$public_ip"; then
        public_ip=""
    fi

    if domain_points_to_host "$domain" "$resolved_ips" "$public_ip"; then
        success "Домен ${domain} указывает на текущий хост."
        return 0
    fi

    if [ -n "$public_ip" ]; then
        warn "Домен ${domain} не указывает на текущий публичный IP ${public_ip}."
    else
        warn "Не удалось подтвердить, что домен ${domain} указывает на текущий хост."
    fi

    if [ "$require_public_domain" = "true" ]; then
        confirm "Продолжить несмотря на несовпадение DNS-привязки?" "n" || \
            die "Исправьте DNS-запись домена и повторите запуск."
    else
        confirm "Продолжить несмотря на предупреждение по DNS?" "y" || \
            die "Исправьте DNS-запись домена и повторите запуск."
    fi
}

detect_linux_family() {
    local family=""

    [ -f /etc/os-release ] || return 1
    . /etc/os-release

    family="${ID:-}"
    case " ${ID_LIKE:-} " in
        *" debian "*)
            family="debian"
            ;;
        *" rhel "*|*" fedora "*)
            family="rhel"
            ;;
        *" arch "*)
            family="arch"
            ;;
    esac

    case "${ID:-}" in
        ubuntu|debian)
            family="debian"
            ;;
        fedora|rhel|centos|rocky|almalinux|amzn)
            family="rhel"
            ;;
        arch|manjaro)
            family="arch"
            ;;
    esac

    [ -n "$family" ] || return 1
    printf '%s' "$family"
}

install_packages() {
    local family="$1"
    shift

    [ "$#" -gt 0 ] || return 0

    case "$family" in
        debian)
            run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
            ;;
        rhel)
            if command_exists dnf; then
                run_privileged dnf install -y "$@"
            elif command_exists yum; then
                run_privileged yum install -y "$@"
            else
                die "Не найден dnf или yum для установки пакетов."
            fi
            ;;
        arch)
            run_privileged pacman -Sy --noconfirm "$@"
            ;;
        *)
            die "Неподдерживаемый менеджер пакетов: ${family}"
            ;;
    esac
}

enable_docker_service() {
    if command_exists systemctl; then
        run_privileged systemctl enable --now docker
    elif command_exists service; then
        run_privileged service docker start
    else
        die "Не удалось автоматически запустить Docker daemon. Запустите сервис Docker вручную."
    fi
}

install_openssl_if_missing() {
    local family="$1"

    if command_exists openssl; then
        return 0
    fi

    info "OpenSSL не найден. Устанавливаю зависимость..."
    if [ "$family" = "debian" ]; then
        run_privileged apt-get update
    fi
    install_packages "$family" openssl
}

install_http_probe_client_if_missing() {
    local family="$1"

    if command_exists curl || command_exists wget || command_exists python3 || command_exists python; then
        return 0
    fi

    info "Не найден curl/wget/python. Устанавливаю curl для health checks..."
    if [ "$family" = "debian" ]; then
        run_privileged apt-get update
    fi
    install_packages "$family" curl
}

install_docker_on_linux() {
    local family="$1"

    info "Устанавливаю Docker и Docker Compose..."

    case "$family" in
        debian)
            run_privileged apt-get update
            install_packages "$family" ca-certificates curl gnupg
            install_packages "$family" docker.io
            install_packages "$family" docker-compose-v2 || \
                install_packages "$family" docker-compose-plugin || \
                install_packages "$family" docker-compose
            ;;
        rhel)
            install_packages "$family" docker || install_packages "$family" moby-engine
            install_packages "$family" docker-compose-plugin || install_packages "$family" docker-compose
            ;;
        arch)
            install_packages "$family" docker docker-compose
            ;;
        *)
            die "Автоустановка Docker поддерживается только на Debian/Ubuntu, RHEL/Fedora и Arch."
            ;;
    esac

    enable_docker_service
    success "Docker установлен."
}

install_docker_if_missing() {
    local family=""

    if command_exists docker; then
        return 0
    fi

    case "$(uname -s)" in
        Linux)
            family="$(detect_linux_family)" || die "Не удалось определить Linux-дистрибутив для установки Docker."
            if confirm "Docker не найден. Установить автоматически?" "y"; then
                install_docker_on_linux "$family"
            else
                die "Docker обязателен для запуска KernvoxHub."
            fi
            ;;
        Darwin)
            die "Docker не найден. На macOS установите Docker Desktop вручную и повторите запуск."
            ;;
        *)
            die "Docker не найден. Установите Docker вручную и повторите запуск."
            ;;
    esac
}

ensure_docker_group_membership() {
    local target_user="${SUDO_USER:-$USER}"

    [ "$(uname -s)" = "Linux" ] || return 0
    [ -n "$target_user" ] || return 0
    [ "$target_user" = "root" ] && return 0

    if id -nG "$target_user" 2>/dev/null | tr ' ' '\n' | grep -qx "docker"; then
        return 0
    fi

    if command_exists getent; then
        getent group docker >/dev/null 2>&1 || return 0
    elif ! grep -q '^docker:' /etc/group 2>/dev/null; then
        return 0
    fi

    info "Добавляю пользователя ${target_user} в группу docker..."
    run_privileged usermod -aG docker "$target_user" || warn "Не удалось добавить пользователя ${target_user} в группу docker."
    warn "Для прямого доступа к Docker без sudo может потребоваться новый вход в сессию."
}

install_compose_if_missing() {
    local family="$1"

    if command_exists docker && docker compose version >/dev/null 2>&1; then
        return 0
    fi

    if command_exists docker-compose; then
        return 0
    fi

    info "Docker Compose не найден. Устанавливаю Compose..."

    case "$family" in
        debian)
            run_privileged apt-get update
            install_packages "$family" docker-compose-v2 || \
                install_packages "$family" docker-compose-plugin || \
                install_packages "$family" docker-compose
            ;;
        rhel)
            install_packages "$family" docker-compose-plugin || install_packages "$family" docker-compose
            ;;
        arch)
            install_packages "$family" docker-compose
            ;;
        *)
            die "Автоустановка Docker Compose не поддерживается на этой платформе."
            ;;
    esac
}

init_docker_commands() {
    DOCKER_CMD=(docker)
    COMPOSE_CMD=()

    if ! docker info >/dev/null 2>&1; then
        enable_docker_service || true
    fi

    if docker info >/dev/null 2>&1; then
        DOCKER_CMD=(docker)
    elif command_exists sudo && sudo docker info >/dev/null 2>&1; then
        DOCKER_CMD=(sudo docker)
    else
        die "Docker установлен, но нет доступа к Docker daemon. Проверьте сервис Docker и права на docker socket."
    fi

    if "${DOCKER_CMD[@]}" compose version >/dev/null 2>&1; then
        COMPOSE_CMD=("${DOCKER_CMD[@]}" compose)
    elif command_exists sudo && sudo docker-compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(sudo docker-compose)
    elif command_exists docker-compose && docker-compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
    else
        die "Docker Compose не найден. Установите compose plugin или docker-compose."
    fi
}

docker_run() {
    "${DOCKER_CMD[@]}" "$@"
}

compose_run() {
    "${COMPOSE_CMD[@]}" "$@"
}

wait_for_service_ready() {
    local service_name="$1"
    local timeout_seconds="${2:-180}"
    local container_id=""
    local status=""
    local health_mode=""
    local elapsed=0

    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        container_id="$(compose_run ps -q "$service_name" 2>/dev/null | tail -n 1)"

        if [ -n "$container_id" ]; then
            health_mode="$(docker_run inspect --format '{{if .State.Health}}health{{else}}state{{end}}' "$container_id" 2>/dev/null || true)"

            if [ "$health_mode" = "health" ]; then
                status="$(docker_run inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
                if [ "$status" = "healthy" ]; then
                    return 0
                fi
                if [ "$status" = "unhealthy" ]; then
                    return 1
                fi
            else
                status="$(docker_run inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
                if [ "$status" = "running" ]; then
                    return 0
                fi
            fi
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

http_probe() {
    local url="$1"

    if command_exists curl; then
        curl --silent --show-error --fail --max-time 5 "$url" >/dev/null
    elif command_exists wget; then
        wget -q -O /dev/null "$url"
    elif command_exists python3; then
        python3 - <<PY >/dev/null 2>&1
import sys
from urllib.request import urlopen

with urlopen("${url}", timeout=5) as response:
    if response.status >= 400:
        sys.exit(1)
PY
    else
        return 1
    fi
}

wait_for_http_endpoint() {
    local url="$1"
    local timeout_seconds="${2:-120}"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        if http_probe "$url"; then
            return 0
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}
