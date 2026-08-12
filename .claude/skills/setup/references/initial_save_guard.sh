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
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    git restore --staged -- "${staged_secret_paths[@]}"
  else
    git rm --cached -r --ignore-unmatch -- "${staged_secret_paths[@]}" >/dev/null
  fi
  {
    echo "secret-like file staged; unstaged before commit:"
    printf '  %s\n' "${staged_secret_paths[@]}"
    echo "Review .gitignore before retrying."
  } >&2
  exit 1
fi
