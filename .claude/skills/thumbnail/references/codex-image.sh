#!/usr/bin/env bash
# Usage: bash .claude/skills/thumbnail/references/codex-image.sh <prompt> <output.png> [reference1.png reference2.png ...]
# ChatGPT サブスク認証の codex CLI で画像生成し、PNG を保存する。
set -euo pipefail

prompt=${1:?usage: codex-image.sh <prompt> <output.png> [refs...]}
out=${2:?output path required}
shift 2

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI が PATH にありません" >&2
  exit 1
fi

login_status=$(codex login status 2>&1)
if [[ "$login_status" != *"Logged in"* ]]; then
  echo "ERROR: codex login status で Logged in using ChatGPT を確認してから再実行してください" >&2
  exit 1
fi

image_args=()
for ref in "$@"; do
  image_args+=(--image "$ref")
done

codex exec --enable image_generation "${image_args[@]+"${image_args[@]}"}" -- "$prompt" \
  | awk '/^generated image / {print $4; exit}' \
  | base64 -d > "$out"

if [ ! -s "$out" ]; then
  echo "ERROR: 画像が生成されませんでした (stdout に generated image 行なし)" >&2
  exit 1
fi

header=$(head -c 8 "$out" | xxd -p)
if [ "${header:0:16}" != "89504e470d0a1a0a" ]; then
  echo "ERROR: 出力ファイルが PNG ヘッダで始まっていません: $out" >&2
  exit 1
fi

echo "saved: $out ($(stat -f%z "$out" 2>/dev/null || stat -c%s "$out") bytes)"
