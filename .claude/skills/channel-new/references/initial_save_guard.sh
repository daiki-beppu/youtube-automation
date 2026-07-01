#!/usr/bin/env bash
set -euo pipefail

staged_secret_paths=()

while IFS= read -r path; do
  case "$path" in
    .env | */.env | auth/client_secrets.json | */auth/client_secrets.json | auth/token*.json | */auth/token*.json)
      staged_secret_paths+=("$path")
      ;;
  esac
done < <(git diff --cached --name-only)

if ((${#staged_secret_paths[@]} > 0)); then
  {
    echo "secret-like file staged; unstage before commit:"
    printf '  %s\n' "${staged_secret_paths[@]}"
    echo "Run: git restore --staged -- <path>"
  } >&2
  exit 1
fi
