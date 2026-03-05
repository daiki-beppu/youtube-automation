#!/bin/bash
# archive_to_gdrive.sh - 公開済みコレクションのメディアファイルを Google Drive にアーカイブ
#
# Usage:
#   bash automation/archive_to_gdrive.sh [--dry-run] [--delete]
#
# Options:
#   --dry-run  対象ファイルの一覧表示のみ（コピーしない）
#   --delete   コピー＋検証後にローカルファイルを削除

set -euo pipefail

# --- 設定 ---
GDRIVE_MOUNT="$HOME/Library/CloudStorage"
GDRIVE_ACCOUNT=$(ls "$GDRIVE_MOUNT" 2>/dev/null | grep -m1 "^GoogleDrive-")
if [[ -z "$GDRIVE_ACCOUNT" ]]; then
    echo "ERROR: Google Drive がマウントされていません"
    exit 1
fi
GDRIVE_ROOT="$GDRIVE_MOUNT/$GDRIVE_ACCOUNT/マイドライブ/youtube-channels"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MEDIA_DIRS=("01-master" "02-Individual-music" "03-Individual-movie")

# --- フラグ解析 ---
DRY_RUN=false
DELETE_LOCAL=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --delete) DELETE_LOCAL=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# --- メイン処理 ---
total_size=0
archived_count=0

for channel_dir in "$REPO_ROOT"/channels/*/; do
    channel_name=$(basename "$channel_dir")
    live_dir="$channel_dir/collections/live"
    [[ -d "$live_dir" ]] || continue

    for collection_dir in "$live_dir"/*/; do
        [[ -d "$collection_dir" ]] || continue
        collection_name=$(basename "$collection_dir")

        for media_dir in "${MEDIA_DIRS[@]}"; do
            src="$collection_dir$media_dir"
            [[ -d "$src" ]] || continue

            # サイズ取得
            size=$(du -sh "$src" 2>/dev/null | cut -f1)
            dst="$GDRIVE_ROOT/$channel_name/collections/live/$collection_name/$media_dir"

            echo "[$channel_name] $collection_name/$media_dir ($size)"

            if $DRY_RUN; then
                echo "  → $dst (dry-run)"
                continue
            fi

            # コピー
            mkdir -p "$dst"
            echo "  Copying to Google Drive..."
            rsync -avh --progress "$src/" "$dst/"

            # 検証: ファイル数比較
            local_count=$(find "$src" -type f | wc -l | tr -d ' ')
            remote_count=$(find "$dst" -type f | wc -l | tr -d ' ')

            if [[ "$local_count" != "$remote_count" ]]; then
                echo "  ERROR: ファイル数不一致 (local=$local_count, remote=$remote_count)"
                echo "  スキップ: ローカル削除は行いません"
                continue
            fi

            echo "  OK: $local_count files copied"
            archived_count=$((archived_count + 1))

            # 削除
            if $DELETE_LOCAL; then
                echo "  Deleting local: $src"
                rm -rf "$src"
            fi
        done
    done
done

echo ""
if $DRY_RUN; then
    echo "=== Dry run 完了 ==="
else
    echo "=== アーカイブ完了 ($archived_count directories) ==="
    if ! $DELETE_LOCAL; then
        echo "ローカル削除するには --delete を付けて再実行してください"
    fi
fi
