#!/bin/bash
# Reproducible local benchmark for overlay encoder selection (#2372).
set -eu

DURATION="${VIDEOUP_BENCH_DURATION:-60}"
RUNS="${VIDEOUP_BENCH_RUNS:-3}"
OUTPUT_DIR="${VIDEOUP_BENCH_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/videoup-overlay-bench.XXXXXX")}"
mkdir -p "$OUTPUT_DIR"

FILTER='[1:a]asplit=2[avis_in][aout];[avis_in]showfreqs=mode=bar:s=1280x180:rate=24:fscale=log:win_size=2048:win_func=hann:colors=white,format=rgba,colorchannelmixer=aa=0.85[avis];[0:v]format=yuv420p[bg];[bg][avis]overlay=(W-w)/2:H-h-40:format=auto,format=yuv420p[vout]'
RESULTS="$OUTPUT_DIR/results.tsv"
printf 'mode\trun\treal_seconds\tsize_bytes\tcodec\n' > "$RESULTS"

ffmpeg -y -f lavfi -i "sine=frequency=220:sample_rate=48000:duration=${DURATION}" \
    -c:a pcm_s16le -loglevel error "$OUTPUT_DIR/audio.wav"

encoder_available() {
    ffmpeg -hide_banner -encoders 2>&1 | grep -q "^ V..... $1 "
}

run_direct() {
    local mode="$1" run="$2"
    local output="$OUTPUT_DIR/${mode}-${run}.mp4" time_file="$OUTPUT_DIR/${mode}-${run}.time"
    shift 2
    /usr/bin/time -p -o "$time_file" ffmpeg -y \
        -f lavfi -i "color=c=0x20252f:s=1920x1080:r=24:d=${DURATION}" \
        -i "$OUTPUT_DIR/audio.wav" \
        -filter_complex "$FILTER" -map '[vout]' -map '[aout]' \
        "$@" -r 24 -c:a aac -b:a 192k -t "$DURATION" \
        -movflags +faststart -loglevel error "$output"
    local elapsed size codec
    elapsed="$(awk '/^real /{print $2}' "$time_file")"
    size="$(wc -c < "$output" | tr -d ' ')"
    codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$output")"
    printf '%s\t%s\t%s\t%s\t%s\n' "$mode" "$run" "$elapsed" "$size" "$codec" >> "$RESULTS"
}

run_twostage() {
    local run="$1"
    local output="$OUTPUT_DIR/twostage-${run}.mp4" time_file="$OUTPUT_DIR/twostage-${run}.time"
    local base_elapsed=0
    if [[ ! -f "$OUTPUT_DIR/base.mp4" ]]; then
        /usr/bin/time -p -o "$OUTPUT_DIR/base.time" ffmpeg -y \
            -f lavfi -i "color=c=0x20252f:s=1920x1080:r=24:d=${DURATION}" \
            -c:v libx264 -preset ultrafast -crf 20 -pix_fmt yuv420p -r 24 -an \
            -loglevel error "$OUTPUT_DIR/base.mp4"
        base_elapsed="$(awk '/^real /{print $2}' "$OUTPUT_DIR/base.time")"
    fi
    /usr/bin/time -p -o "$time_file" ffmpeg -y -i "$OUTPUT_DIR/base.mp4" \
        -i "$OUTPUT_DIR/audio.wav" \
        -filter_complex "$FILTER" -map '[vout]' -map '[aout]' \
        -c:v libx264 -preset medium -crf 20 -maxrate 4M -bufsize 8M \
        -profile:v high -pix_fmt yuv420p -r 24 -c:a aac -b:a 192k -t "$DURATION" \
        -movflags +faststart -loglevel error "$output"
    local final_elapsed elapsed size codec
    final_elapsed="$(awk '/^real /{print $2}' "$time_file")"
    elapsed="$(awk -v base="$base_elapsed" -v final="$final_elapsed" 'BEGIN{printf "%.2f", base + final}')"
    size="$(wc -c < "$output" | tr -d ' ')"
    codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$output")"
    printf 'twostage\t%s\t%s\t%s\t%s\n' "$run" "$elapsed" "$size" "$codec" >> "$RESULTS"
}

run=1
while [[ "$run" -le "$RUNS" ]]; do
    run_direct baseline "$run" -c:v libx264 -preset medium -crf 20 -maxrate 4M -bufsize 8M -profile:v high -pix_fmt yuv420p
    run_direct software-veryfast "$run" -c:v libx264 -preset veryfast -crf 20 -maxrate 4M -bufsize 8M -profile:v high -pix_fmt yuv420p
    if encoder_available h264_videotoolbox; then
        run_direct h264_videotoolbox "$run" -c:v h264_videotoolbox -b:v 4M -maxrate 4M -bufsize 8M -profile:v high -pix_fmt yuv420p
        run_direct h264_videotoolbox-speed "$run" -c:v h264_videotoolbox -b:v 4M -maxrate 4M -bufsize 8M -profile:v high -pix_fmt yuv420p -realtime true -prio_speed 1
    fi
    if encoder_available h264_nvenc; then
        run_direct h264_nvenc "$run" -c:v h264_nvenc -preset p5 -cq 20 -b:v 0 -maxrate 4M -bufsize 8M -profile:v high -pix_fmt yuv420p
    fi
    run_twostage "$run"
    run=$((run + 1))
done

printf '\nresults: %s\n' "$RESULTS"
cat "$RESULTS"

printf '\nquality against baseline run 2 (SSIM):\n'
for candidate in "$OUTPUT_DIR"/*-2.mp4; do
    [[ "$candidate" == "$OUTPUT_DIR/baseline-2.mp4" ]] && continue
    metric="$(ffmpeg -i "$candidate" -i "$OUTPUT_DIR/baseline-2.mp4" -lavfi ssim -f null - 2>&1 | awk -F'All:' '/SSIM/{split($2,a," "); print a[1]}' | tail -1)"
    printf '%s\t%s\n' "$(basename "$candidate" .mp4)" "${metric:-unavailable}"
done
