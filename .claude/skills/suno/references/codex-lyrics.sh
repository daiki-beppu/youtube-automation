#!/usr/bin/env bash
# Usage: bash .claude/skills/suno/references/codex-lyrics.sh <prompt.md> <output.md>
set -euo pipefail

prompt_path=${1:?usage: codex-lyrics.sh <prompt.md> <output.md>}
out=${2:?output path required}

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI が PATH にありません" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq CLI が PATH にありません (codex --json の JSONL 解析に必要)" >&2
  exit 1
fi

if [ ! -f "$prompt_path" ]; then
  echo "ERROR: prompt file が存在しません: $prompt_path" >&2
  exit 1
fi

if login_status=$(codex login status 2>&1); then
  :
else
  rc=$?
  echo "ERROR: codex login status の実行に失敗しました (rc=${rc})" >&2
  if [ -n "$login_status" ]; then
    echo "$login_status" >&2
  fi
  exit 1
fi
if [[ "$login_status" != *"Logged in using ChatGPT"* ]]; then
  echo "ERROR: codex login status で Logged in using ChatGPT を確認してから再実行してください" >&2
  exit 1
fi

prompt_body=$(<"$prompt_path")
out_dir=$(dirname "$out")
full_prompt="${prompt_body}

Write the final lyrics to ${out}.
Use natural native English with observational diary detail, ABCB or other loose rhyme, and a short mantra-like chorus.
Avoid meaning-inverting words such as downfall unless the intended meaning is literal collapse.
Do not copy style references verbatim; use them only for rhythm, line length, point of view, and rhyme density.
After writing the lyrics file, reply with exactly ${out}."

rm -f "$out"

err_log=$(mktemp -t codex-lyrics.XXXXXX)
trap 'rm -f "$err_log"' EXIT

dump_codex_stderr() {
  if [ -s "$err_log" ]; then
    echo "--- codex stderr (tail) ---" >&2
    tail -n 30 "$err_log" >&2
  fi
}

if ! final_msg=$(codex exec --json --sandbox workspace-write --add-dir "$out_dir" --skip-git-repo-check \
  -- "$full_prompt" </dev/null 2>"$err_log" \
  | jq -r 'select(.type=="item.completed") | select(.item.type=="agent_message") | .item.text' \
  | tail -n 1); then
  echo "ERROR: codex exec / jq パイプラインが非0で終了しました" >&2
  dump_codex_stderr
  exit 1
fi

if [ "$final_msg" != "$out" ]; then
  echo "ERROR: agent_message の path が出力先 $out と一致しません" >&2
  if [ -n "$final_msg" ]; then
    echo "agent_message (最終): $final_msg" >&2
  else
    echo "agent_message (最終): <empty>" >&2
  fi
  dump_codex_stderr
  exit 1
fi

if [ ! -s "$out" ]; then
  echo "ERROR: 歌詞ファイルが生成されませんでした ($out が空か存在しません)" >&2
  echo "agent_message (最終): $final_msg" >&2
  dump_codex_stderr
  exit 1
fi

echo "saved: $out ($(stat -f%z "$out" 2>/dev/null || stat -c%s "$out") bytes)"
