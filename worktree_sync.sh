#!/usr/bin/env bash
# worktree_sync.sh — ワークツリーのコレクション成果物をメインリポジトリにコピー
#
# Usage:
#   cd collections/planning/xxx-collection/
#   bash /path/to/worktree_sync.sh [--dry-run]
#
# コピー対象:
#   01-master/master.wav       → main の 01-master/
#   01-master/*.wav (master除く) → main の 02-Individual-music/
#   01-master/*.mp4             → main の 01-master/
#   10-assets/main.png         → main の 10-assets/
# クリーンアップ:
#   01-master/preview/         → 削除

set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# --- ワークツリー検出 ---
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"

if [[ "$GIT_COMMON_DIR" == ".git" || "$GIT_COMMON_DIR" == "$WORKTREE_ROOT/.git" ]]; then
    echo "メインリポジトリで実行中です。コピーは不要です。"
    exit 0
fi

# --- メインリポジトリのルートを算出 ---
MAIN_REPO="$(cd "$GIT_COMMON_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "${GIT_COMMON_DIR%/.git}")"
REL_PATH="${PWD#"$WORKTREE_ROOT"/}"
MAIN_COLLECTION="$MAIN_REPO/$REL_PATH"

echo "=== worktree_sync ==="
echo "  Worktree:  $PWD"
echo "  Main dest: $MAIN_COLLECTION"
echo ""

# --- コピー関数 ---
sync_files() {
    local src_pattern="$1"
    local dest_dir="$2"
    local label="$3"

    # glob 展開（マッチなしでも安全に）
    local files=()
    for f in $src_pattern; do
        [[ -f "$f" ]] && files+=("$f")
    done

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "  SKIP: $label (ファイルなし)"
        return
    fi

    if $DRY_RUN; then
        echo "  DRY-RUN: $label → $dest_dir/"
        for f in "${files[@]}"; do
            echo "    $(basename "$f") ($(du -h "$f" | cut -f1))"
        done
    else
        mkdir -p "$dest_dir"
        for f in "${files[@]}"; do
            cp "$f" "$dest_dir/"
            echo "  COPY: $(basename "$f") ($(du -h "$f" | cut -f1)) → $dest_dir/"
        done
    fi
}

# --- コピー実行 ---
sync_files "01-master/master.wav" "$MAIN_COLLECTION/01-master" "master.wav"
# master.wav 以外の WAV を個別楽曲としてコピー（seg_*.wav またはリネーム後の NN_Name.wav）
sync_files_exclude() {
    local src_dir="$1"
    local exclude="$2"
    local dest_dir="$3"
    local label="$4"

    local files=()
    for f in "$src_dir"/*.wav; do
        [[ -f "$f" ]] && [[ "$(basename "$f")" != "$exclude" ]] && files+=("$f")
    done

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "  SKIP: $label (ファイルなし)"
        return
    fi

    if $DRY_RUN; then
        echo "  DRY-RUN: $label → $dest_dir/ (${#files[@]} files)"
        for f in "${files[@]}"; do
            echo "    $(basename "$f") ($(du -h "$f" | cut -f1))"
        done
    else
        mkdir -p "$dest_dir"
        for f in "${files[@]}"; do
            cp "$f" "$dest_dir/"
            echo "  COPY: $(basename "$f") ($(du -h "$f" | cut -f1)) → $dest_dir/"
        done
    fi
}
sync_files_exclude "01-master" "master.wav" "$MAIN_COLLECTION/02-Individual-music" "individual tracks"
sync_files "01-master/*.mp4" "$MAIN_COLLECTION/01-master" "master video"
sync_files "10-assets/main.png" "$MAIN_COLLECTION/10-assets" "main.png"

# --- preview クリーンアップ ---
if [[ -d "01-master/preview" ]]; then
    if $DRY_RUN; then
        echo "  DRY-RUN: 01-master/preview/ を削除"
    else
        rm -rf "01-master/preview"
        echo "  CLEAN: 01-master/preview/ を削除"
    fi
fi

echo ""
echo "Done."
