#!/bin/bash
# generate_videos.sh v12.1 — Master video generator
# Static image + master audio → MP4 (macOS optimized)
# v12.1: ループモードの高ビットレート入力を上限付き正規化に退避
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
LOOP_TARGET_WIDTH="1920"
LOOP_TARGET_HEIGHT="1080"
LOOP_TARGET_PIX_FMT="yuv420p"
LOOP_TARGET_FRAME_RATE="24/1"
LOOP_OUTPUT_FRAME_RATE="24"
LOOP_MAX_BITRATE="6000k"
LOOP_BUFSIZE="12000k"

# ─── Audio encoder 自動選択 (macOS は AudioToolbox 優先) ─
if ffmpeg -hide_banner -encoders 2>&1 | grep -q '^ A..... aac_at '; then
    AUDIO_ENCODER="aac_at"
else
    AUDIO_ENCODER="aac"
fi

# ─── 音声出力オプション (m4a/aac はストリームコピー、それ以外は再エンコード) ─
if [[ -n "$MASTER_AUDIO" ]]; then
    master_ext="${MASTER_AUDIO##*.}"
    case "$master_ext" in
        m4a|aac)
            AUDIO_OUT_OPTS=(-c:a copy)
            ;;
        *)
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

bitrate_to_bps() {
    local value="$1"
    local unit number

    if [[ -z "$value" || "$value" == "N/A" ]]; then
        echo ""
        return
    fi

    unit="$(echo "${value: -1}" | tr '[:upper:]' '[:lower:]')"
    case "$unit" in
        k)
            number="${value%?}"
            awk "BEGIN{printf \"%.0f\", $number * 1000}"
            ;;
        m)
            number="${value%?}"
            awk "BEGIN{printf \"%.0f\", $number * 1000000}"
            ;;
        *)
            awk "BEGIN{printf \"%.0f\", $value}"
            ;;
    esac
}

video_bitrate_bps() {
    local file="$1"
    local bitrate

    bitrate="$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null | head -1)"
    if [[ -z "$bitrate" || "$bitrate" == "N/A" ]]; then
        bitrate="$(ffprobe -v error \
            -show_entries format=bit_rate -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null | head -1)"
    fi
    bitrate_to_bps "$bitrate"
}

# ─── TTY 判定 (Issue #641) ───────────────────────────────
# 非 TTY 環境（CI / log redirect）では \r アニメを抑止し、行ごとの出力に
# フォールバックする。-t 1 は stdout が TTY のときだけ true を返す。
if [[ -t 1 ]]; then
    IS_TTY=1
else
    IS_TTY=0
fi

# ─── Main ────────────────────────────────────────────────
echo ""
echo "  generate_videos.sh v12.1 — ${COLLECTION_NAME}"
echo "  ──────────────────────────────────────────"
echo ""
if [[ -n "$LOOP_VIDEO" ]]; then
    echo "  Video BG : $(basename "$LOOP_VIDEO") (loop)"
else
    echo "  Thumbnail: $(basename "$THUMBNAIL")"
fi
echo "  Audio    : $(basename "$MASTER_AUDIO")"
echo "  Output   : $(basename "$MASTER_OUTPUT")"

duration="$(get_duration "$MASTER_AUDIO")"
echo "  Duration : $(format_duration "$duration")"
echo ""
start=$SECONDS
PROGRESS_FILE="$(mktemp)"
trap 'rm -f "$PROGRESS_FILE"' EXIT

# ─── Step 表示 (Issue #641) ──────────────────────────────
# Veo / ffmpeg 双方で「生成中 → 保存 → 後処理」のステップ感を共通化する。
# ffmpeg 経路は (1) 入力正規化 (loop モードのみ) → (2) マスター動画生成
# の 2 ステップ構成。静止画モードは (1) を skip。
if [[ -n "$LOOP_VIDEO" ]]; then
    FF_TOTAL_STEPS=2
else
    FF_TOTAL_STEPS=1
fi

# ─── FFmpeg (background) ─────────────────────────────────
if [[ -n "$LOOP_VIDEO" ]]; then
    # ループ動画背景モード: loop.mp4 を無限ループで背景に使用
    # 戦略: ソースを 1 度だけ yuv420p / 1920x1080 に正規化キャッシュし、
    # 以降のマスター動画生成は -c:v copy で stream copy する（音声のみエンコード）
    loop_specs="$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=width,height,pix_fmt,r_frame_rate -of csv=p=0 "$LOOP_VIDEO" 2>/dev/null)"
    # csv=p=0 出力は "width,height,pix_fmt,r_frame_rate" の順
    loop_w="$(echo "$loop_specs" | cut -d, -f1)"
    loop_h="$(echo "$loop_specs" | cut -d, -f2)"
    loop_pix="$(echo "$loop_specs" | cut -d, -f3)"
    loop_fps="$(echo "$loop_specs" | cut -d, -f4)"
    loop_bitrate_bps="$(video_bitrate_bps "$LOOP_VIDEO")"
    max_bitrate_bps="$(bitrate_to_bps "$LOOP_MAX_BITRATE")"

    if [[ "$loop_w" == "$LOOP_TARGET_WIDTH" && "$loop_h" == "$LOOP_TARGET_HEIGHT" && "$loop_pix" == "$LOOP_TARGET_PIX_FMT" && "$loop_fps" == "$LOOP_TARGET_FRAME_RATE" \
          && ( -z "$loop_bitrate_bps" || "$loop_bitrate_bps" -le "$max_bitrate_bps" ) ]]; then
        # 既に正規化済み: そのまま使う
        LOOP_SOURCE="$LOOP_VIDEO"
    else
        # 正規化キャッシュを使用
        LOOP_SOURCE="${ASSETS_DIR}/loop_normalized.mp4"
        normalized_bitrate_bps=""
        if [[ -f "$LOOP_SOURCE" ]]; then
            normalized_bitrate_bps="$(video_bitrate_bps "$LOOP_SOURCE")"
        fi
        if [[ ! -f "$LOOP_SOURCE" || "$LOOP_VIDEO" -nt "$LOOP_SOURCE" || ( -n "$normalized_bitrate_bps" && "$normalized_bitrate_bps" -gt "$max_bitrate_bps" ) ]]; then
            echo "  [Step 1/${FF_TOTAL_STEPS}] Normalizing loop source (1 回だけ実行) → loop_normalized.mp4"
            if [[ -n "$loop_bitrate_bps" && "$loop_bitrate_bps" -gt "$max_bitrate_bps" ]]; then
                echo "  Loop bitrate exceeds ${LOOP_MAX_BITRATE}; re-encoding with maxrate guard"
            fi
            ffmpeg -y -i "$LOOP_VIDEO" \
                -c:v libx264 -preset slow -crf 22 -maxrate "$LOOP_MAX_BITRATE" -bufsize "$LOOP_BUFSIZE" -profile:v high -pix_fmt yuv420p \
                -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
                -r "$LOOP_OUTPUT_FRAME_RATE" \
                -an -movflags +faststart \
                -loglevel error \
                "$LOOP_SOURCE"
            if [[ $? -ne 0 || ! -f "$LOOP_SOURCE" ]]; then
                echo "  ERROR: loop_normalized.mp4 の生成に失敗"
                exit 1
            fi
        fi
    fi

    echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (stream copy)"
    # Stream copy 経路: ビデオは完全無損失（ビット単位コピー）、音声は AUDIO_OUT_OPTS に従う
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
    echo "  [Step 1/1] Generating master video (still image)"
    # 静止画背景モード（従来）
    # I-frame を 5 分間隔（1fps なので 300 フレーム）に間引き、変化のないフレームを P-frame で
    # 圧縮することで master.mp4 を大幅に小型化する（#579）。keyint=1 全 I-frame 化は容量が膨らむため廃止。
    ffmpeg -y -framerate 1 -loop 1 -i "$THUMBNAIL" -i "$MASTER_AUDIO" \
        -c:v libx264 -tune stillimage -preset medium -crf 28 -pix_fmt yuv420p \
        -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
        -g 300 \
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
last_logged_pct=-1  # 非 TTY 用、最後に行出力した進捗率

while kill -0 "$ffmpeg_pid" 2>/dev/null; do
    out_time_us=$(grep -o 'out_time_us=[0-9]*' "$PROGRESS_FILE" 2>/dev/null | tail -1 | cut -d= -f2)
    elapsed_now=$((SECONDS - start))
    elapsed_fmt="$(printf "%dm%02ds" $((elapsed_now/60)) $((elapsed_now%60)))"

    if [[ -n "$out_time_us" && "$total_us" -gt 0 ]]; then
        pct=$((out_time_us * 100 / total_us))
        [[ $pct -gt 100 ]] && pct=100
        eta_sec=0
        if [[ $pct -gt 0 ]]; then
            eta_sec=$(( elapsed_now * (100 - pct) / pct ))
        fi
        eta_fmt="$(printf "%dm%02ds" $((eta_sec/60)) $((eta_sec%60)))"
        if [[ $IS_TTY -eq 1 ]]; then
            filled=$((pct * BAR_WIDTH / 100))
            empty=$((BAR_WIDTH - filled))
            bar="$(printf '%0.s█' $(seq 1 $filled 2>/dev/null))$(printf '%0.s░' $(seq 1 $empty 2>/dev/null))"
            printf "\r  %s Generating... %s %3d%% (%s, ETA %s)  " "${spinner[$si]}" "$bar" "$pct" "$elapsed_fmt" "$eta_fmt"
        else
            # 非 TTY: 10% 刻みで 1 行ずつログ出力
            bucket=$(( pct / 10 ))
            if [[ $bucket -ne $last_logged_pct ]]; then
                printf "  Generating... %3d%% (%s, ETA %s)\n" "$pct" "$elapsed_fmt" "$eta_fmt"
                last_logged_pct=$bucket
            fi
        fi
    else
        if [[ $IS_TTY -eq 1 ]]; then
            printf "\r  %s Generating... (%s)  " "${spinner[$si]}" "$elapsed_fmt"
        fi
    fi

    si=$(( (si + 1) % ${#spinner[@]} ))
    sleep 0.15
done

wait "$ffmpeg_pid"
exit_code=$?
elapsed=$((SECONDS - start))

# Final bar
if [[ $IS_TTY -eq 1 ]]; then
    printf "\r  ✓ Generated    %s 100%% (%dm%02ds)    \n" \
        "$(printf '%0.s█' $(seq 1 $BAR_WIDTH))" $((elapsed/60)) $((elapsed%60))
else
    printf "  ✓ Generated 100%% (%dm%02ds)\n" $((elapsed/60)) $((elapsed%60))
fi

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
