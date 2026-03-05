#!/bin/bash
# generate_master.sh v2.0 — Crossfade master audio generator
# Combines individual MP3s with 3-second crossfade into a single master MP3
#
# Usage:
#   bash automation/generate_master.sh <collection-path>
#   cd <collection-dir> && bash ../../automation/generate_master.sh

# ─── Collection Path Resolution ──────────────────────────
COLLECTION_DIR="${1:-}"

if [[ -z "$COLLECTION_DIR" ]]; then
    if [[ -d "01-master" && -d "02-Individual-music" ]]; then
        COLLECTION_DIR="$(pwd)"
    else
        echo "Usage: $0 <collection-path>"
        exit 1
    fi
fi

COLLECTION_DIR="$(cd "$COLLECTION_DIR" && pwd)"
MASTER_DIR="${COLLECTION_DIR}/01-master"
MUSIC_DIR="${COLLECTION_DIR}/02-Individual-music"

# ─── Auto-detect Collection Name ─────────────────────────
dir_basename="$(basename "$COLLECTION_DIR")"
COLLECTION_NAME="$(echo "$dir_basename" \
    | sed -E 's/^[0-9]+-[a-z]+-//; s/-collection$//' \
    | awk -F'-' '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2); print}' OFS='-')"
OUTPUT="${MASTER_DIR}/${COLLECTION_NAME}-Master.mp3"

# ─── Prerequisites ───────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found"; exit 1
fi

if [[ ! -d "$MUSIC_DIR" ]]; then
    echo "ERROR: Missing directory: $MUSIC_DIR"; exit 1
fi

mkdir -p "$MASTER_DIR"

# ─── Collect Files ───────────────────────────────────────
FILES=()
while IFS= read -r f; do
    FILES+=("$f")
done < <(find "$MUSIC_DIR" -name "*.mp3" -type f | sort)

N=${#FILES[@]}

if [[ $N -eq 0 ]]; then
    echo "ERROR: No MP3 files found in $MUSIC_DIR"; exit 1
fi

echo ""
echo "  generate_master.sh v2.0 — ${COLLECTION_NAME}"
echo "  ──────────────────────────────────────────"
echo ""
echo "  Input : ${N} MP3 files"
echo "  Output: $(basename "$OUTPUT")"
echo "  Crossfade: 3s (triangle curve)"
echo ""

# ─── Single file: just copy ──────────────────────────────
if [[ $N -eq 1 ]]; then
    cp "${FILES[0]}" "$OUTPUT"
    echo "  Single file — copied directly."
    echo ""
    exit 0
fi

# ─── Build FFmpeg Command ────────────────────────────────
INPUTS=""
for f in "${FILES[@]}"; do
    INPUTS="$INPUTS -i \"$f\""
done

FILTER=""
if [[ $N -eq 2 ]]; then
    FILTER="[0:a][1:a]acrossfade=d=3:c1=tri:c2=tri[aout]"
else
    FILTER="[0:a][1:a]acrossfade=d=3:c1=tri:c2=tri[cf1]"
    for ((i=2; i<N-1; i++)); do
        prev=$((i-1))
        FILTER="${FILTER};[cf${prev}][${i}:a]acrossfade=d=3:c1=tri:c2=tri[cf${i}]"
    done
    last=$((N-1))
    prev=$((N-2))
    FILTER="${FILTER};[cf${prev}][${last}:a]acrossfade=d=3:c1=tri:c2=tri[aout]"
fi

start=$SECONDS

# ─── FFmpeg (background) ─────────────────────────────────
eval ffmpeg -y $INPUTS \
    -filter_complex "\"${FILTER}\"" \
    -map '"[aout]"' -c:a libmp3lame -b:a 192k -q:a 0 \
    "\"${OUTPUT}\"" \
    -loglevel error &
ffmpeg_pid=$!

# ─── Spinner ──────────────────────────────────────────────
spinner=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
si=0

while kill -0 "$ffmpeg_pid" 2>/dev/null; do
    elapsed_now=$((SECONDS - start))
    elapsed_fmt="$(printf "%dm%02ds" $((elapsed_now/60)) $((elapsed_now%60)))"
    printf "\r  %s Generating... (%s) [%d files, %d crossfades]  " \
        "${spinner[$si]}" "$elapsed_fmt" "$N" "$((N-1))"
    si=$(( (si + 1) % ${#spinner[@]} ))
    sleep 0.15
done

wait "$ffmpeg_pid"
exit_code=$?

elapsed=$((SECONDS - start))
printf "\r  ✓ Generated    (%dm%02ds) [%d files, %d crossfades]      \n" \
    $((elapsed/60)) $((elapsed%60)) "$N" "$((N-1))"

if [[ $exit_code -ne 0 ]]; then
    echo "  ERROR: FFmpeg failed with exit code $exit_code"
    exit $exit_code
fi

# ─── Report ──────────────────────────────────────────────
size="$(ls -lh "$OUTPUT" | awk '{print $5}')"
if command -v afinfo &>/dev/null; then
    dur_secs="$(afinfo "$OUTPUT" 2>/dev/null | awk '/estimated duration/{printf "%.0f", $(NF-1)}')"
else
    dur_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUTPUT" 2>/dev/null | awk '{printf "%.0f", $1}')"
fi

dur_fmt="$(printf "%dh %02dm %02ds" $((dur_secs/3600)) $((dur_secs%3600/60)) $((dur_secs%60)))"

echo ""
echo "  Master audio complete!"
echo ""
echo "    File    : $(basename "$OUTPUT")"
echo "    Size    : ${size}"
echo "    Duration: ${dur_fmt}"
echo "    Time    : $((elapsed/60))m $((elapsed%60))s"
echo ""
