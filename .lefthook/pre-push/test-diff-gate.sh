#!/usr/bin/env bash
#
# src / extension lib 変更に対応するテスト差分の有無を通知する。
#
# 判定基準: origin/main からの分岐点（merge-base）と現在の HEAD の差分。
# このゲートは警告のみで push は止めない。意図的に省く場合は
# SKIP_TEST_DIFF=1 を指定すると skip した事実を出力に残す。

set -euo pipefail

if [ "${SKIP_TEST_DIFF:-}" = "1" ]; then
  echo "test-diff-gate: SKIP_TEST_DIFF=1 のためスキップします。" >&2
  exit 0
fi

BASE_REF="origin/main"
if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  echo "test-diff-gate: ${BASE_REF} が無いためスキップします（CI / review で確認してください）。" >&2
  exit 0
fi

if ! diff_base=$(git merge-base "${BASE_REF}" HEAD 2>/dev/null); then
  diff_base="${BASE_REF}"
fi

changed_files=$(git diff --name-only "${diff_base}" HEAD 2>/dev/null || true)
[ -z "${changed_files}" ] && exit 0

python_code_touched=0
python_tests_touched=0
extension_lib_touched=0
extension_tests_touched=0

while IFS= read -r f; do
  [ -z "$f" ] && continue
  # 各パターンを独立判定する（case/esac の排他マッチにしない）。
  # extensions/*/lib/*.test.ts のように lib 配下のテストファイルは
  # extension_lib_touched と extension_tests_touched の両方に該当し得る。
  case "$f" in
    src/youtube_automation/*)
      python_code_touched=1
      ;;
  esac
  case "$f" in
    tests/*)
      python_tests_touched=1
      ;;
  esac
  case "$f" in
    extensions/*/lib/*)
      extension_lib_touched=1
      ;;
  esac
  case "$f" in
    extensions/*.test.ts)
      extension_tests_touched=1
      ;;
  esac
done <<EOF
${changed_files}
EOF

warned=0
if [ "${python_code_touched}" = "1" ] && [ "${python_tests_touched}" = "0" ]; then
  warned=1
  echo "" >&2
  echo "test-diff-gate: WARNING: src/youtube_automation/ に差分がありますが tests/ の差分がありません。" >&2
  echo "  粗い検出です。テスト不要な変更なら SKIP_TEST_DIFF=1 git push で明示 skip してください。" >&2
fi

if [ "${extension_lib_touched}" = "1" ] && [ "${extension_tests_touched}" = "0" ]; then
  warned=1
  echo "" >&2
  echo "test-diff-gate: WARNING: extensions/*/lib/ に差分がありますが extensions 配下の *.test.ts 差分がありません。" >&2
  echo "  粗い検出です。テスト不要な変更なら SKIP_TEST_DIFF=1 git push で明示 skip してください。" >&2
fi

if [ "${warned}" = "1" ]; then
  echo "" >&2
fi

exit 0
