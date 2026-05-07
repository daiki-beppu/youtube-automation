#!/bin/bash
# generate_videos.sh v13.0 — Master video generator
# (Previous: generate_videos.sh v12.0 — ループモード stream copy + 正規化キャッシュ)
# Static image / Loop background + master audio → MP4
# v13: Intro 統合モード追加（`branding/intro.mp4` 自動検出時に pure concat 経路）
# v12: ループモードを正規化キャッシュ + stream copy 化（クオリティ完全保持で大幅高速化）
#
# Usage:
#   bash .claude/skills/videoup/references/generate_videos.sh <collection-path>
#   cd <collection-dir> && bash <repo-root>/.claude/skills/videoup/references/generate_videos.sh

# ─── Collection Path Resolution ──────────────────────────
COLLECTION_DIR="${1:-}"

if [[ -z "$COLLECTION_DIR" ]]; then
    if [[ -d "01-master" && -d "10-assets" ]]; then
        COLLECTION_DIR="$(pwd)"
    else
        echo "Usage: $0 <collection-path>"
        exit 1
    fi
fi

COLLECTION_DIR="$(cd "$COLLECTION_DIR" && pwd)"
MASTER_DIR="${COLLECTION_DIR}/01-master"
ASSETS_DIR="${COLLECTION_DIR}/10-assets"

# ─── Auto-detect Collection Name ─────────────────────────
dir_basename="$(basename "$COLLECTION_DIR")"
COLLECTION_NAME="$(echo "$dir_basename" \
    | sed -E 's/^[0-9]+-[a-z]+-//; s/-collection$//' \
    | awk -F'-' '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2); print}' OFS='-')"

# ─── Repo root resolution (for branding/intro.mp4 auto-detection) ─
REPO_ROOT=""
candidate="$COLLECTION_DIR"
while [[ "$candidate" != "/" && -n "$candidate" ]]; do
    if [[ -d "${candidate}/config/channel" || -d "${candidate}/branding" || -d "${candidate}/.git" ]]; then
        REPO_ROOT="$candidate"
        break
    fi
    candidate="$(dirname "$candidate")"
done
if [[ -z "$REPO_ROOT" ]]; then
    # collection の祖先方向で見つからなければ collection 直上をフォールバック扱い
    REPO_ROOT="$(dirname "$(dirname "$COLLECTION_DIR")")"
fi

# ─── Auto-detect Assets ─────────────────────────────────
LOOP_VIDEO=""
if [[ -f "${ASSETS_DIR}/loop.mp4" ]]; then
    LOOP_VIDEO="${ASSETS_DIR}/loop.mp4"
fi

THUMBNAIL=""
for candidate in "${ASSETS_DIR}/main.jpg" "${ASSETS_DIR}/main.png" "${ASSETS_DIR}/thumbnail.jpg" "${ASSETS_DIR}/thumbnail.png"; do
    if [[ -f "$candidate" ]]; then
        THUMBNAIL="$candidate"
        break
    fi
done

# DAW バウンスの実運用ケースに対応: wav 優先、なければ m4a / aac / mp3 / flac
MASTER_AUDIO=""
for ext in wav m4a aac mp3 flac; do
    candidate="${MASTER_DIR}/master-mix.${ext}"
    if [[ -f "$candidate" ]]; then
        MASTER_AUDIO="$candidate"
        break
    fi
done

MASTER_OUTPUT="${MASTER_DIR}/${COLLECTION_NAME}-Master.mp4"

# ─── Intro mode auto-detection ───────────────────────────
INTRO_VIDEO="${REPO_ROOT}/branding/intro.mp4"
INTRO_MODE=0
if [[ -f "$INTRO_VIDEO" ]]; then
    INTRO_MODE=1
fi

# ─── 音声出力オプション (m4a/aac はストリームコピー、それ以外は AAC 再エンコード) ─
# m4a/aac 系は encoder 検出 ffmpeg 呼び出し自体を省略する (-c:a copy で再エンコード不要)
if [[ -n "$MASTER_AUDIO" ]]; then
    master_ext="${MASTER_AUDIO##*.}"
    case "$master_ext" in
        m4a|aac)
            AUDIO_OUT_OPTS=(-c:a copy)
            ;;
        *)
            # AAC エンコーダ自動選択 (macOS は AudioToolbox 優先)
            if ffmpeg -hide_banner -encoders 2>&1 | grep -q '^ A..... aac_at '; then
                AUDIO_ENCODER="aac_at"
            else
                AUDIO_ENCODER="aac"
            fi
            AUDIO_OUT_OPTS=(-c:a "$AUDIO_ENCODER" -b:a 384k -ar 48000)
            ;;
    esac
fi

# ─── Prerequisites ───────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found"; exit 1
fi
if [[ -z "$THUMBNAIL" ]]; then
    echo "ERROR: No thumbnail found in ${ASSETS_DIR}/ (main.jpg/png or thumbnail.jpg/png)"; exit 1
fi
if [[ -z "$MASTER_AUDIO" ]]; then
    echo "ERROR: master-mix.{wav,m4a,aac,mp3,flac} not found in ${MASTER_DIR}/"; exit 1
fi
if ! ffprobe -v error "$MASTER_AUDIO" &>/dev/null; then
    echo "ERROR: Corrupted file: $MASTER_AUDIO"; exit 1
fi

# Intro 統合モードは loop モード必須 (静止画 + intro は別仕様)
if [[ $INTRO_MODE -eq 1 && -z "$LOOP_VIDEO" ]]; then
    echo "ERROR: 静止画モードでは intro 統合非対応 (Intro 統合モードは 10-assets/loop.mp4 が必要)"
    exit 1
fi

# ─── Duration (macOS: afinfo, fallback: ffprobe) ─────────
get_duration() {
    local file="$1"
    if command -v afinfo &>/dev/null; then
        afinfo "$file" 2>/dev/null | awk '/estimated duration/{printf "%.2f", $(NF-1)}'
    else
        ffprobe -v error -show_entries format=duration -of csv=p=0 "$file" 2>/dev/null
    fi
}

format_duration() {
    local secs="${1%.*}"
    printf "%dh %02dm %02ds" $((secs/3600)) $((secs%3600/60)) $((secs%60))
}

# ─── Main ────────────────────────────────────────────────
echo ""
if [[ $INTRO_MODE -eq 1 ]]; then
    echo "  generate_videos.sh v13.0 — ${COLLECTION_NAME} (Intro 統合モード)"
else
    echo "  generate_videos.sh v13.0 — ${COLLECTION_NAME}"
fi
echo "  ──────────────────────────────────────────"
echo ""
if [[ -n "$LOOP_VIDEO" ]]; then
    echo "  Video BG : $(basename "$LOOP_VIDEO") (loop)"
else
    echo "  Thumbnail: $(basename "$THUMBNAIL")"
fi
if [[ $INTRO_MODE -eq 1 ]]; then
    echo "  Intro    : $(basename "$INTRO_VIDEO") (concat 先頭)"
fi
echo "  Audio    : $(basename "$MASTER_AUDIO")"
echo "  Output   : $(basename "$MASTER_OUTPUT")"

duration="$(get_duration "$MASTER_AUDIO")"
echo "  Duration : $(format_duration "$duration")"
echo ""
start=$SECONDS
PROGRESS_FILE="$(mktemp)"

# 一時中間成果物 (Intro 統合モード用) は trap でまとめて掃除
TS="$$"
INTRO_TMP="/tmp/intro_video_only_${COLLECTION_NAME}_${TS}.mp4"
BODY_TMP="/tmp/body_video_${COLLECTION_NAME}_${TS}.mp4"
CONCAT_LIST="/tmp/concat_${COLLECTION_NAME}_${TS}.txt"
trap 'rm -f "$PROGRESS_FILE" "$INTRO_TMP" "$BODY_TMP" "$CONCAT_LIST"' EXIT

# ─── Loop 正規化キャッシュ (loop モードのみ) ─────────────
if [[ -n "$LOOP_VIDEO" ]]; then
    loop_specs="$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=width,height,pix_fmt -of csv=p=0 "$LOOP_VIDEO" 2>/dev/null)"
    loop_w="$(echo "$loop_specs" | cut -d, -f1)"
    loop_h="$(echo "$loop_specs" | cut -d, -f2)"
    loop_pix="$(echo "$loop_specs" | cut -d, -f3)"

    if [[ "$loop_w" == "1920" && "$loop_h" == "1080" && "$loop_pix" == "yuv420p" ]]; then
        LOOP_SOURCE="$LOOP_VIDEO"
    else
        LOOP_SOURCE="${ASSETS_DIR}/loop_normalized.mp4"
        if [[ ! -f "$LOOP_SOURCE" || "$LOOP_VIDEO" -nt "$LOOP_SOURCE" ]]; then
            echo "  Normalizing loop source (1 回だけ実行) → loop_normalized.mp4"
            # -r 24 で intro.mp4 と fps を揃える (concat demuxer + stream copy 互換の前提)
            ffmpeg -y -i "$LOOP_VIDEO" \
                -c:v libx264 -preset slow -crf 18 -profile:v high -pix_fmt yuv420p \
                -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
                -r 24 \
                -an -movflags +faststart \
                -loglevel error \
                "$LOOP_SOURCE"
            if [[ $? -ne 0 || ! -f "$LOOP_SOURCE" ]]; then
                echo "  ERROR: loop_normalized.mp4 の生成に失敗"
                exit 1
            fi
        fi
    fi
fi

# ─── FFmpeg 本処理 ───────────────────────────────────────
if [[ $INTRO_MODE -eq 1 ]]; then
    # ─── Intro 統合モード v13 (3 段ビルド + concat demuxer) ──
    # Step 1: intro_video_only.mp4 (intro.mp4 を audio 抜き stream copy)
    ffmpeg -y -i "$INTRO_VIDEO" -an -c:v copy \
        -movflags +faststart \
        -loglevel error \
        "$INTRO_TMP"
    rc=$?
    if [[ $rc -ne 0 || ! -f "$INTRO_TMP" ]]; then
        echo "  ERROR: intro_video_only.mp4 の生成に失敗 (exit ${rc})"
        exit ${rc:-1}
    fi

    # Step 2: body_video.mp4 (loop を duration - 30s 分ループ、stream copy)
    body_dur=$(awk "BEGIN{printf \"%.2f\", ${duration} - 30}")
    ffmpeg -y -stream_loop -1 -i "$LOOP_SOURCE" \
        -an -c:v copy \
        -t "$body_dur" \
        -movflags +faststart \
        -loglevel error \
        "$BODY_TMP"
    rc=$?
    if [[ $rc -ne 0 || ! -f "$BODY_TMP" ]]; then
        echo "  ERROR: body_video.mp4 の生成に失敗 (exit ${rc})"
        exit ${rc:-1}
    fi

    # Step 3: concat demuxer で intro + body を結合し、master.mp3 を audio として map
    printf "file '%s'\nfile '%s'\n" "$INTRO_TMP" "$BODY_TMP" > "$CONCAT_LIST"
    ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" -i "$MASTER_AUDIO" \
        -map 0:v:0 -map 1:a:0 \
        -c:v copy \
        "${AUDIO_OUT_OPTS[@]}" \
        -t "$duration" \
        -movflags +faststart \
        -shortest \
        -loglevel error \
        -progress "$PROGRESS_FILE" \
        "$MASTER_OUTPUT" &
elif [[ -n "$LOOP_VIDEO" ]]; then
    # ─── 通常 loop モード (intro 無し / 既存挙動) ─
    ffmpeg -y -stream_loop -1 -i "$LOOP_SOURCE" -i "$MASTER_AUDIO" \
        -map 0:v:0 -map 1:a:0 \
        -c:v copy \
        "${AUDIO_OUT_OPTS[@]}" \
        -t "$duration" \
        -movflags +faststart \
        -shortest \
        -loglevel error \
        -progress "$PROGRESS_FILE" \
        "$MASTER_OUTPUT" &
else
    # ─── 静止画背景モード (従来) ─
    ffmpeg -y -framerate 1 -loop 1 -i "$THUMBNAIL" -i "$MASTER_AUDIO" \
        -c:v libx264 -tune stillimage -preset ultrafast -crf 23 -pix_fmt yuv420p \
        -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
        -x264opts keyint=1:min-keyint=1 \
        -r 1 \
        "${AUDIO_OUT_OPTS[@]}" \
        -t "$duration" \
        -movflags +faststart \
        -shortest \
        -loglevel error \
        -progress "$PROGRESS_FILE" \
        "$MASTER_OUTPUT" &
fi
ffmpeg_pid=$!

# ─── Progress Bar ─────────────────────────────────────────
total_us=$(awk "BEGIN{printf \"%.0f\", $duration * 1000000}")
spinner=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
si=0
BAR_WIDTH=30

while kill -0 "$ffmpeg_pid" 2>/dev/null; do
    out_time_us=$(grep -o 'out_time_us=[0-9]*' "$PROGRESS_FILE" 2>/dev/null | tail -1 | cut -d= -f2)
    elapsed_now=$((SECONDS - start))
    elapsed_fmt="$(printf "%dm%02ds" $((elapsed_now/60)) $((elapsed_now%60)))"

    if [[ -n "$out_time_us" && "$total_us" -gt 0 ]]; then
        pct=$((out_time_us * 100 / total_us))
        [[ $pct -gt 100 ]] && pct=100
        filled=$((pct * BAR_WIDTH / 100))
        empty=$((BAR_WIDTH - filled))
        bar="$(printf '%0.s█' $(seq 1 $filled 2>/dev/null))$(printf '%0.s░' $(seq 1 $empty 2>/dev/null))"
        printf "\r  %s Generating... %s %3d%% (%s)  " "${spinner[$si]}" "$bar" "$pct" "$elapsed_fmt"
    else
        printf "\r  %s Generating... (%s)  " "${spinner[$si]}" "$elapsed_fmt"
    fi

    si=$(( (si + 1) % ${#spinner[@]} ))
    sleep 0.15
done

wait "$ffmpeg_pid"
exit_code=$?
elapsed=$((SECONDS - start))

printf "\r  ✓ Generated    %s 100%% (%dm%02ds)    \n" \
    "$(printf '%0.s█' $(seq 1 $BAR_WIDTH))" $((elapsed/60)) $((elapsed%60))

if [[ $exit_code -ne 0 ]]; then
    echo "  ERROR: FFmpeg failed with exit code $exit_code"
    exit $exit_code
fi

size="$(ls -lh "$MASTER_OUTPUT" | awk '{print $5}')"

echo ""
echo "  Video generation complete!"
echo ""
echo "    File    : $(basename "$MASTER_OUTPUT")"
echo "    Size    : ${size}"
echo "    Duration: $(format_duration "$duration")"
echo "    Time    : $((elapsed/60))m $((elapsed%60))s"
echo ""
