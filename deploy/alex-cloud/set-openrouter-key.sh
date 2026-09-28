#!/usr/bin/env bash

set +ax
set -euo pipefail
umask 077
unset llm_api_key

if (( $# > 1 )); then
    printf 'Использование: bash set-openrouter-key.sh [путь-к-content.env]\n' >&2
    exit 1
fi

environment_file="${1:-/home/alex/exposlides/shared/content.env}"
if [[ -L "${environment_file}" || ( -e "${environment_file}" && ! -f "${environment_file}" ) ]]; then
    printf 'Нужен обычный файл настроек, а не ссылка или каталог.\n' >&2
    exit 1
fi

if ! { exec 3<> /dev/tty; } 2>/dev/null; then
    printf 'Нужен интерактивный терминал. Подключитесь к серверу через ssh -t.\n' >&2
    exit 1
fi

printf 'Вставьте ключ OpenRouter и нажмите Enter: ' >&3
if ! IFS= read -r -s llm_api_key <&3; then
    printf '\nВвод отменён, файл не изменён.\n' >&3
    exit 1
fi
printf '\n' >&3
exec 3>&-

if [[ -z "${llm_api_key}" ]]; then
    printf 'Ключ пустой, файл не изменён.\n' >&2
    exit 1
fi
if [[ ! "${llm_api_key}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    printf 'Ключ содержит недопустимые символы. Вставьте только ключ без кавычек и пробелов.\n' >&2
    exit 1
fi

temporary_file="$(mktemp "${environment_file}.tmp.XXXXXX")"
trap 'rm -f "${temporary_file}"' EXIT

if [[ -f "${environment_file}" ]]; then
    awk '!/^[[:space:]]*(export[[:space:]]+)?(LLM_API_KEY|LLM_BASE_URL|LLM_MODEL|LLM_FAST_MODEL|LLM_FAST_REPAIR_MODEL|LLM_SCOPE|GIGACHAT_CA_BUNDLE_FILE)[[:space:]]*=/' \
        "${environment_file}" > "${temporary_file}"
fi

printf 'LLM_API_KEY=%s\n' "${llm_api_key}" >> "${temporary_file}"
unset llm_api_key
cat >> "${temporary_file}" <<'SETTINGS'
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen3.8-27b:free
LLM_FAST_MODEL=qwen/qwen3.8-27b:free
LLM_FAST_REPAIR_MODEL=qwen/qwen3.8-27b:free
SETTINGS
chmod 600 "${temporary_file}"
mv -f "${temporary_file}" "${environment_file}"
trap - EXIT

if ! sudo systemctl restart exposlides; then
    printf 'Настройки сохранены, но перезапуск ExpoSlides завершился ошибкой.\n' >&2
    exit 1
fi
if ! sudo systemctl is-active --quiet exposlides; then
    printf 'Настройки сохранены, но служба ExpoSlides не активна.\n' >&2
    exit 1
fi

printf 'Ключ сохранён, ExpoSlides перезапущен и активен. Генерацию можно запускать на сайте.\n'
