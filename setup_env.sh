#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

if command -v op &>/dev/null; then
  op inject -i "$REPO_ROOT/.env.tpl" -o "$REPO_ROOT/.env" -f
  echo "✓ .env generated from 1Password"
else
  if [ ! -f "$REPO_ROOT/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo "✓ .env copied from .env.example"
    echo "⚠ Edit .env and set your API keys"
  else
    echo "✓ .env already exists"
  fi
fi
