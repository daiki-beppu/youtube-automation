#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
op inject -i "$REPO_ROOT/.env.tpl" -o "$REPO_ROOT/.env" -f
echo "✓ .env generated from 1Password"
