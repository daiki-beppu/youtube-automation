#!/bin/bash
# generate_videos.sh v10.0 — Master video generator
# Static image + master audio → MP4 (macOS optimized)
#
# Usage:
#   bash automation/generate_videos.sh <collection-path>
#   cd <collection-dir> && bash ../../automation/generate_videos.sh

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
THUMBNAIL=""
for candidate in "${ASSETS_DIR}/main.png" "${ASSETS_DIR}/thumbnail.png"; do
    if [[ -f "$candidate" ]]; then
        THUMBNAIL="$candidate"
        break
    fi
done

MASTER_AUDIO=""
if [[ -f "${MASTER_DIR}/master-mix.wav" ]]; then
    MASTER_AUDIO="${MASTER_DIR}/master-mix.wav"
else
    for f in "${MASTER_DIR}"/*-Master.mp3 "${MASTER_DIR}"/master.mp3; do
        if [[ -f "$f" ]]; then
            MASTER_AUDIO="$f"
            break
        fi
    done
fi

MASTER_OUTPUT="${MASTER_DIR}/${COLLECTION_NAME}-Master.mp4"

# ─── Prerequisites ───────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found"; exit 1
fi
if [[ -z "$THUMBNAIL" ]]; then
    echo "ERROR: No thumbnail found in ${ASSETS_DIR}/ (main.png or thumbnail.png)"; exit 1
fi
if [[ -z "$MASTER_AUDIO" ]]; then
    echo "ERROR: No master audio found in ${MASTER_DIR}/"; exit 1
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

# ─── Main ────────────────────────────────────────────────
echo ""
echo "  generate_videos.sh v10.0 — ${COLLECTION_NAME}"
echo "  ──────────────────────────────────────────"
echo ""
echo "  Thumbnail: $(basename "$THUMBNAIL")"
echo "  Audio    : $(basename "$MASTER_AUDIO")"
echo "  Output   : $(basename "$MASTER_OUTPUT")"

duration="$(get_duration "$MASTER_AUDIO")"
echo "  Duration : $(format_duration "$duration")"
echo ""
start=$SECONDS
PROGRESS_FILE="$(mktemp)"
trap 'rm -f "$PROGRESS_FILE"' EXIT

# ─── FFmpeg (background) ─────────────────────────────────
ffmpeg -y -framerate 1 -loop 1 -i "$THUMBNAIL" -i "$MASTER_AUDIO" \
    -c:v libx264 -tune stillimage -preset ultrafast -crf 40 -pix_fmt yuv420p \
    -x264opts keyint=1:min-keyint=1 \
    -r 1 \
    -c:a aac -b:a 192k -ar 48000 \
    -t "$duration" \
    -movflags +faststart \
    -shortest \
    -loglevel error \
    -progress "$PROGRESS_FILE" \
    "$MASTER_OUTPUT" &
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

# Final bar
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
