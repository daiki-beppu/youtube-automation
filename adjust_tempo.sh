#!/bin/bash
# adjust_tempo.sh v1.0 — Apply tempo adjustment to master audio
# Changes playback speed without altering pitch (FFmpeg atempo filter)
#
# Usage:
#   bash automation/adjust_tempo.sh <input.mp3> <tempo>
#   bash automation/adjust_tempo.sh 01-master/Collection-Master.mp3 0.8
#
# The tempo value is a multiplier:
#   0.8 = 20% slower (e.g. 100min → 125min)
#   1.2 = 20% faster (e.g. 100min → 83min)
#
# Output overwrites the input file (in-place).

INPUT="${1:-}"
TEMPO="${2:-}"

# ─── Validation ──────────────────────────────────────────
if [[ -z "$INPUT" || -z "$TEMPO" ]]; then
    echo "Usage: $0 <input.mp3> <tempo>"
    echo "  e.g.: $0 01-master/Collection-Master.mp3 0.8"
    exit 1
fi

if [[ ! -f "$INPUT" ]]; then
    echo "ERROR: File not found: $INPUT"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found"; exit 1
fi

# Validate tempo range (atempo supports 0.5 to 100.0)
if ! awk "BEGIN { exit ($TEMPO >= 0.5 && $TEMPO <= 2.0) ? 0 : 1 }"; then
    echo "ERROR: Tempo must be between 0.5 and 2.0 (got: $TEMPO)"
    exit 1
fi

# ─── Pre-check ───────────────────────────────────────────
if command -v afinfo &>/dev/null; then
    before_secs="$(afinfo "$INPUT" 2>/dev/null | awk '/estimated duration/{printf "%.0f", $(NF-1)}')"
else
    before_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$INPUT" 2>/dev/null | awk '{printf "%.0f", $1}')"
fi

before_fmt="$(printf "%dh %02dm %02ds" $((before_secs/3600)) $((before_secs%3600/60)) $((before_secs%60)))"
after_est=$(awk "BEGIN { printf \"%.0f\", $before_secs / $TEMPO }")
after_fmt="$(printf "%dh %02dm %02ds" $((after_est/3600)) $((after_est%3600/60)) $((after_est%60)))"

echo ""
echo "  adjust_tempo.sh v1.0"
echo "  ──────────────────────────────────────────"
echo ""
echo "  Input : $(basename "$INPUT")"
echo "  Tempo : ${TEMPO}x"
echo "  Before: ${before_fmt}"
echo "  After : ~${after_fmt} (estimated)"
echo ""

# ─── Process ─────────────────────────────────────────────
TMPFILE="${INPUT%.mp3}-tempo-tmp.mp3"
start=$SECONDS

ffmpeg -y -i "$INPUT" \
    -filter:a "atempo=${TEMPO}" \
    -c:a libmp3lame -b:a 192k -q:a 0 \
    "$TMPFILE" \
    -loglevel error &
ffmpeg_pid=$!

# ─── Spinner ─────────────────────────────────────────────
spinner=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
si=0

while kill -0 "$ffmpeg_pid" 2>/dev/null; do
    elapsed_now=$((SECONDS - start))
    elapsed_fmt="$(printf "%dm%02ds" $((elapsed_now/60)) $((elapsed_now%60)))"
    printf "\r  %s Adjusting tempo... (%s)  " \
        "${spinner[$si]}" "$elapsed_fmt"
    si=$(( (si + 1) % ${#spinner[@]} ))
    sleep 0.15
done

wait "$ffmpeg_pid"
exit_code=$?

elapsed=$((SECONDS - start))

if [[ $exit_code -ne 0 ]]; then
    printf "\r  ERROR: FFmpeg failed with exit code $exit_code\n"
    rm -f "$TMPFILE"
    exit $exit_code
fi

mv "$TMPFILE" "$INPUT"
printf "\r  ✓ Tempo adjusted (%dm%02ds)                         \n" \
    $((elapsed/60)) $((elapsed%60))

# ─── Report ──────────────────────────────────────────────
size="$(ls -lh "$INPUT" | awk '{print $5}')"
if command -v afinfo &>/dev/null; then
    dur_secs="$(afinfo "$INPUT" 2>/dev/null | awk '/estimated duration/{printf "%.0f", $(NF-1)}')"
else
    dur_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$INPUT" 2>/dev/null | awk '{printf "%.0f", $1}')"
fi

dur_fmt="$(printf "%dh %02dm %02ds" $((dur_secs/3600)) $((dur_secs%3600/60)) $((dur_secs%60)))"

echo ""
echo "  Done!"
echo ""
echo "    File    : $(basename "$INPUT")"
echo "    Size    : ${size}"
echo "    Duration: ${dur_fmt}"
echo "    Time    : $((elapsed/60))m $((elapsed%60))s"
echo ""
