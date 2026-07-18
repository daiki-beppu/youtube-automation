#!/usr/bin/env bash
# tsc --noEmit 実行時間ベンチマーク（TypeScript 5.9.3 / 7.0.2 共用）
#
# 使い方:
#   ./compile-bench.sh <suno-helper|distrokid-helper> [runs]
#
# helper の node_modules/.bin にある tsc を helper の tsconfig.json で直接実行して
# 計測する。pnpm 起動オーバーヘッドを除外するため tsc バイナリを直接叩く。
# `wxt prepare`（.wxt/ の型生成）は計測前に 1 回だけ実行し、型検査レーンのみを測る。
# warm cache 前提: 計測前に 1 回 warmup 実行を捨てる。
# 出力: 各 run の wall-clock（/usr/bin/time -p の real）と中央値。
#
# TypeScript 5.9.3 側を計測する場合は、移行前コミットの構成を復元してから実行する:
#   git show 33250036^:extensions/<helper>/package.json   > <helper>/package.json
#   git show 33250036^:extensions/<helper>/pnpm-lock.yaml > <helper>/pnpm-lock.yaml
#   (cd <helper> && ni --frozen)
set -euo pipefail
cd "$(dirname "$0")"

helper="${1:?usage: compile-bench.sh <suno-helper|distrokid-helper> [runs]}"
runs="${2:-10}"
bin_dir="${helper}/node_modules/.bin"

if [[ ! -x "${bin_dir}/tsc" ]]; then
  echo "error: ${bin_dir}/tsc が見つからない（ni --frozen 済みか確認）" >&2
  exit 1
fi

echo "tsc: $(cd "$helper" && ./node_modules/.bin/tsc --version)"
echo "helper: ${helper}"
echo "runs: ${runs} (+1 warmup)"

# .wxt/ の型を生成しておく（計測対象は型検査のみ）
(cd "$helper" && ./node_modules/.bin/wxt prepare > /dev/null 2>&1)

# warmup（型エラーがあっても計測は続行する）
(cd "$helper" && ./node_modules/.bin/tsc --noEmit > /dev/null 2>&1) || true

times=()
for i in $(seq "$runs"); do
  # tsc の診断出力(stdout)は捨て、time の出力(stderr)だけを拾う
  t=$({ /usr/bin/time -p bash -c "cd '$helper' && ./node_modules/.bin/tsc --noEmit > /dev/null" || true; } 2>&1 | awk '/^real/{print $2}')
  times+=("$t")
  echo "run ${i}: ${t}s"
done

median=$(printf '%s\n' "${times[@]}" | sort -n | awk '{a[NR]=$1} END {if (NR%2) print a[(NR+1)/2]; else printf "%.3f", (a[NR/2]+a[NR/2+1])/2}')
echo "median (tsc, ${helper}): ${median}s"
