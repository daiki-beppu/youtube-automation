#!/usr/bin/env bash
#
# CHANGELOG ゲート（lefthook pre-push から実行される）
#
# CI（.github/workflows/ci.yml の `changelog` ジョブ）と同じ判定をローカル再現し、
# 実コードを変更したのに CHANGELOG.md を更新していない push を止める。
#
# 判定基準: origin/main からの分岐点（merge-base）と現在の HEAD の差分。
#
# ゲート対象パス（いずれかが変更されたら CHANGELOG.md 更新が必須）:
#   - src/youtube_automation/
#   - .claude/skills/
#   - .claude/CLAUDE.template.md
#   - pyproject.toml
#
# tests/ や docs/ など上記以外のみの変更はゲート対象外（CI も自動 skip）。
#
# 意図的に省く: SKIP_CHANGELOG=1 git push

set -euo pipefail

if [ "${SKIP_CHANGELOG:-}" = "1" ]; then
  echo "changelog-gate: SKIP_CHANGELOG=1 のためスキップします。" >&2
  exit 0
fi

BASE_REF="origin/main"
if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  echo "changelog-gate: ${BASE_REF} が無いためスキップします（CI で判定されます）。" >&2
  exit 0
fi

# origin/main からの分岐点を基準に、現在の HEAD までの変更を見る。
if ! diff_base=$(git merge-base "${BASE_REF}" HEAD 2>/dev/null); then
  diff_base="${BASE_REF}"
fi

changed_files=$(git diff --name-only "${diff_base}" HEAD 2>/dev/null || true)
[ -z "${changed_files}" ] && exit 0

GATED_PATHS=(
  "src/youtube_automation/"
  ".claude/skills/"
  ".claude/CLAUDE.template.md"
  "pyproject.toml"
)
CHANGELOG_PATH="CHANGELOG.md"

code_touched=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  for p in "${GATED_PATHS[@]}"; do
    case "$f" in
      "$p"*)
        code_touched=1
        break
        ;;
    esac
  done
  [ "$code_touched" = "1" ] && break
done <<EOF
${changed_files}
EOF

[ "${code_touched}" = "0" ] && exit 0

changelog_touched=0
while IFS= read -r f; do
  if [ "$f" = "${CHANGELOG_PATH}" ]; then
    changelog_touched=1
    break
  fi
done <<EOF
${changed_files}
EOF

if [ "${changelog_touched}" = "0" ]; then
  echo "" >&2
  echo "changelog-gate: ❌ CHANGELOG ゲート違反" >&2
  echo "  実コード（src/youtube_automation/ / .claude/skills/ / .claude/CLAUDE.template.md / pyproject.toml）を" >&2
  echo "  変更していますが ${CHANGELOG_PATH} が更新されていません。" >&2
  echo "  基準: ${diff_base}" >&2
  echo "" >&2
  echo "  対処:" >&2
  echo "    - ${CHANGELOG_PATH} の [Unreleased] に変更点を追記する" >&2
  echo "    - もしくは CHANGELOG 不要な変更なら: SKIP_CHANGELOG=1 git push" >&2
  echo "" >&2
  exit 1
fi

exit 0
