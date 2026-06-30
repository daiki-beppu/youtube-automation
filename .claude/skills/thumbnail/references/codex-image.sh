#!/usr/bin/env bash
# Usage: bash .claude/skills/thumbnail/references/codex-image.sh <prompt> <output.png> reference.png [reference2.png ...]
# ChatGPT サブスク認証の codex CLI で画像生成し、PNG を保存する。
set -euo pipefail

prompt=${1:?usage: codex-image.sh <prompt> <output.png> reference.png [reference2.png ...]}
out=${2:?output path required}
shift 2

if [ "$#" -lt 1 ]; then
  echo "ERROR: codex-image.sh requires at least one reference image for thumbnail TTP generation" >&2
  echo "usage: codex-image.sh <prompt> <output.png> reference.png [reference2.png ...]" >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI が PATH にありません" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq CLI が PATH にありません (codex --json の JSONL 解析に必要)" >&2
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

image_args=()
ref_hashes=()
for ref in "$@"; do
  image_args+=(--image "$ref")
  # reference 画像との一致検証用に MD5 を控える。
  # macOS は `md5 -q`、Linux は `md5sum` を持つので両対応する。
  if command -v md5sum >/dev/null 2>&1; then
    ref_hashes+=("$(md5sum "$ref" | awk '{print $1}')")
  elif command -v md5 >/dev/null 2>&1; then
    ref_hashes+=("$(md5 -q "$ref")")
  fi
done

out_dir=$(dirname "$out")
# prompt 末尾の自動付与文は agent が image_generation tool を skip して
# reference 画像を cp するだけで終わる failure mode を抑止するため、
# 「新画像を生成」「reference を copy するな」を明示する。
full_prompt="${prompt}

Generate a new image with the image_generation tool. Do not copy any provided reference image; produce a freshly generated PNG. After generation, copy the produced PNG to ${out}. Then reply with exactly ${out}."

# Stale artifact 防止: codex 起動前に既存 $out を確実に消す。
# 残っていると agent が cp を skip しても -s "$out" / PNG ヘッダ検証が通って
# 偽陽性 success になる (ARCH-547-002)。
rm -f "$out"

err_log=$(mktemp -t codex-image.XXXXXX)
trap 'rm -f "$err_log"' EXIT

# 3 つの error 分岐に同一 4 行ブロックがコピペされていた DRY 違反を解消するための helper。
# `$err_log` はスクリプト全体で 1 つしか存在しないため引数化せずクロージャ的に参照する。
dump_codex_stderr() {
  if [ -s "$err_log" ]; then
    echo "--- codex stderr (tail) ---" >&2
    tail -n 30 "$err_log" >&2
  fi
}

if ! final_msg=$(codex exec --json --sandbox workspace-write --add-dir "$out_dir" --skip-git-repo-check \
  "${image_args[@]+"${image_args[@]}"}" -- "$full_prompt" </dev/null 2>"$err_log" \
  | jq -r 'select(.type=="item.completed") | select(.item.type=="agent_message") | .item.text' \
  | tail -n 1); then
  echo "ERROR: codex exec / jq パイプラインが非0で終了しました" >&2
  echo "ヒント: codex CLI / jq の実行失敗、または出力 JSONL のパース失敗が考えられます。prompt を短縮して再試行することも検討してください" >&2
  dump_codex_stderr
  exit 1
fi

# JSON プロトコル契約検証: prompt 末尾の "reply with exactly <out>" 指示通り、
# agent が wrapper 指定の $out を最終 agent_message に echo したことを確認する。
# 別 path を返す / 空 / 別ファイルへ流れる failure mode を阻止する (ARCH-547-002)。
if [ "$final_msg" != "$out" ]; then
  echo "ERROR: agent_message の path が出力先 $out と一致しません" >&2
  if [ -n "$final_msg" ]; then
    echo "agent_message (最終): $final_msg" >&2
  else
    echo "agent_message (最終): <empty>" >&2
  fi
  echo "ヒント: prompt が長いと agent が image_generation tool を skip して path だけ返す failure mode があります。プロンプトを短縮して再試行してください" >&2
  dump_codex_stderr
  exit 1
fi

if [ ! -s "$out" ]; then
  echo "ERROR: 画像が生成されませんでした ($out が空か存在しません)" >&2
  echo "ヒント: prompt が長いと agent が image_generation tool を skip して path だけ返す failure mode があります。プロンプトを短縮して再試行してください" >&2
  # この経路に到達した時点で final_msg == $out（直前の契約検証を通過）かつ $out は非空 (out=${2:?...})。
  # 「念のため」の `[ -n "$final_msg" ]` ガードは論理的に常に真で防御として意味がないため省く。
  echo "agent_message (最終): $final_msg" >&2
  dump_codex_stderr
  exit 1
fi

header=$(head -c 8 "$out" | xxd -p)
if [ "${header:0:16}" != "89504e470d0a1a0a" ]; then
  echo "ERROR: 出力ファイルが PNG ヘッダで始まっていません: $out" >&2
  exit 1
fi

# Reference cp failure mode 検出: agent が image_generation tool を skip して
# reference 画像をそのまま $out に cp するだけで終わるケースを潰す。
# wrapper の他の検証 (agent_message path 一致 / 非空 / PNG ヘッダ) は通過してしまうので
# ここでバイト列ハッシュの一致を最終ゲートに使う。
if [ "${#ref_hashes[@]}" -gt 0 ]; then
  if command -v md5sum >/dev/null 2>&1; then
    out_hash=$(md5sum "$out" | awk '{print $1}')
  else
    out_hash=$(md5 -q "$out")
  fi
  for h in "${ref_hashes[@]}"; do
    if [ "$h" = "$out_hash" ]; then
      echo "ERROR: 出力ファイルが reference 画像と完全一致しています (agent が image_generation tool を skip した可能性)" >&2
      echo "ヒント: prompt で reference からの変更点を明示するか、参照画像の役割を「色味の参考」程度に弱めて再試行してください" >&2
      exit 1
    fi
  done
fi

echo "saved: $out ($(stat -f%z "$out" 2>/dev/null || stat -c%s "$out") bytes)"
