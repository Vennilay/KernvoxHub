#!/bin/bash

load_env_file() {
    local file="$1"
    local line key value

    [ -f "$file" ] || return 0

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"

        case "$line" in
            ""|\#*)
                continue
                ;;
        esac

        key="${line%%=*}"
        value="${line#*=}"

        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"

        if ! [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            continue
        fi

        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
            value="${value#\"}"
            value="${value%\"}"
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
            value="${value#\'}"
            value="${value%\'}"
        fi

        printf -v "$key" '%s' "$value"
        export "$key"
    done < "$file"
}

upsert_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp_file

    tmp_file="$(mktemp)"

    if [ -f "$file" ]; then
        awk -v key="$key" -v value="$value" '
            BEGIN { updated = 0 }
            $0 ~ "^[[:space:]]*" key "=" {
                if (!updated) {
                    print key "=" value
                    updated = 1
                }
                next
            }
            { print }
            END {
                if (!updated) {
                    print key "=" value
                }
            }
        ' "$file" > "$tmp_file"
    else
        printf '%s=%s\n' "$key" "$value" > "$tmp_file"
    fi

    mv "$tmp_file" "$file"
    chmod 600 "$file"
}
