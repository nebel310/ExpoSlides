#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
environment_file="${repository_root}/services/content-service/.env"

printf 'Вставь токен Hugging Face и нажми Enter: '
IFS= read -r -s llm_api_key
printf '\n'

if [[ -z "${llm_api_key}" ]]; then
    printf 'Ключ пустой, файл не изменён.\n' >&2
    exit 1
fi

temporary_file="$(mktemp "${environment_file}.tmp.XXXXXX")"
trap 'rm -f "${temporary_file}"' EXIT

if [[ -f "${environment_file}" ]]; then
    grep -v '^LLM_API_KEY=' "${environment_file}" > "${temporary_file}" || true
fi

printf 'LLM_API_KEY=%s\n' "${llm_api_key}" >> "${temporary_file}"
chmod 600 "${temporary_file}"
mv "${temporary_file}" "${environment_file}"
trap - EXIT

printf 'Ключ сохранён в %s\n' "${environment_file}"
printf 'При смене провайдера также обнови LLM_BASE_URL и все LLM_*MODEL по README.md.\n'
