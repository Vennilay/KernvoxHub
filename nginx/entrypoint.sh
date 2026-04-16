#!/bin/sh
set -eu

DOMAIN="${DOMAIN:-localhost}"
TEMPLATE_DIR="${TEMPLATE_DIR:-/etc/kernvox-nginx}"
TARGET_CONF="${TARGET_CONF:-/etc/nginx/nginx.conf}"
CERT_ROOT="${CERT_ROOT:-/etc/letsencrypt/live}"
CERT_DIR="${CERT_ROOT}/${DOMAIN}"
NGINX_RENDER_ONLY="${NGINX_RENDER_ONLY:-0}"
NGINX_SKIP_WATCH="${NGINX_SKIP_WATCH:-0}"

server_name_for_nginx() {
    case "$DOMAIN" in
        ""|localhost|127.0.0.1)
            printf '%s' "_"
            ;;
        *)
            printf '%s' "$DOMAIN"
            ;;
    esac
}

active_template() {
    if [ "$DOMAIN" != "localhost" ] &&
       [ "$DOMAIN" != "127.0.0.1" ] &&
       [ -f "${CERT_DIR}/fullchain.pem" ] &&
       [ -f "${CERT_DIR}/privkey.pem" ]; then
        printf '%s' "${TEMPLATE_DIR}/nginx-https.conf"
    else
        printf '%s' "${TEMPLATE_DIR}/nginx.conf"
    fi
}

render_config() {
    template="$(active_template)"
    server_name="$(server_name_for_nginx)"

    sed \
        -e "s/__SERVER_NAME__/${server_name}/g" \
        -e "s/__CERT_DOMAIN__/${DOMAIN}/g" \
        "$template" > "$TARGET_CONF"
}

cert_state() {
    if [ -f "${CERT_DIR}/fullchain.pem" ] && [ -f "${CERT_DIR}/privkey.pem" ]; then
        cksum "${CERT_DIR}/fullchain.pem" "${CERT_DIR}/privkey.pem" 2>/dev/null | cksum
    else
        printf '%s\n' "no-cert"
    fi
}

watch_certificates() {
    previous_state="$(cert_state)"

    while true; do
        sleep 300
        current_state="$(cert_state)"

        if [ "$current_state" != "$previous_state" ]; then
            render_config
            nginx -s reload
            previous_state="$current_state"
        fi
    done
}

render_config

if [ "$NGINX_RENDER_ONLY" = "1" ]; then
    exit 0
fi

if [ "$NGINX_SKIP_WATCH" != "1" ]; then
    watch_certificates &
fi
exec nginx -g "daemon off;"
