#!/usr/bin/env bash
# lint 実行時間ベンチマーク（ESLint / Oxlint 共用）
#
# 使い方:
#   ./lint-bench.sh <suno-helper|distrokid-helper> [runs]
#
# helper の node_modules/.bin にある linter（oxlint 優先、無ければ eslint）を
# package.json の lint script と同一の対象・設定で直接実行して計測する。
# pnpm 起動オーバーヘッドを除外するため linter バイナリを直接叩く。
# warm cache 前提: 計測前に 1 回 warmup 実行を捨てる。
# 出力: 各 run の wall-clock（/usr/bin/time -p の real）と中央値。
#
# ESLint 側を計測する場合は、移行前コミットの構成を復元してから実行する:
#   git show 554e9808^:extensions/<helper>/package.json    > <helper>/package.json
#   git show 554e9808^:extensions/<helper>/pnpm-lock.yaml  > <helper>/pnpm-lock.yaml
#   git show 554e9808^:extensions/<helper>/eslint.config.js > <helper>/eslint.config.js
#   (cd <helper> && ni --frozen)
set -euo pipefail
cd "$(dirname "$0")"

helper="${1:?usage: lint-bench.sh <suno-helper|distrokid-helper> [runs]}"
runs="${2:-10}"
bin_dir="${helper}/node_modules/.bin"

targets=("$helper")
[[ "$helper" == "suno-helper" ]] && targets+=("shared")

if [[ -x "${bin_dir}/oxlint" ]]; then
  linter="oxlint"
  cmd=("${bin_dir}/oxlint" -c oxlint.config.ts "${targets[@]}")
elif [[ -x "${bin_dir}/eslint" ]]; then
  linter="eslint"
  cmd=("${bin_dir}/eslint" -c "${helper}/eslint.config.js" "${targets[@]}")
else
  echo "error: ${bin_dir} に oxlint も eslint も見つからない（ni --frozen 済みか確認）" >&2
  exit 1
fi

echo "linter: ${linter} ($("${bin_dir}/${linter}" --version 2>/dev/null | head -1))"
echo "targets: ${targets[*]}"
echo "runs: ${runs} (+1 warmup)"

# warmup（lint エラーがあっても計測は続行する）
"${cmd[@]}" > /dev/null 2>&1 || true

times=()
for i in $(seq "$runs"); do
  # lint の診断出力(stdout)は捨て、time の出力(stderr)だけを拾う
  t=$({ /usr/bin/time -p "${cmd[@]}" > /dev/null || true; } 2>&1 | awk '/^real/{print $2}')
  times+=("$t")
  echo "run ${i}: ${t}s"
done

median=$(printf '%s\n' "${times[@]}" | sort -n | awk '{a[NR]=$1} END {if (NR%2) print a[(NR+1)/2]; else printf "%.3f", (a[NR/2]+a[NR/2+1])/2}')
echo "median (${linter}, ${helper}): ${median}s"
