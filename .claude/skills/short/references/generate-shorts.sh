#!/usr/bin/env bash
# content_model.type に従って collection / release のショート動画を生成
#
# 素材の優先順位:
#   1. 10-assets/short-loop.mp4 … Veo 3.1 ループ動画（テキスト焼き込み済み）
#   2. 10-assets/short.png      … 9:16 静止画 + zoompan (Ken Burns)
#   3. 10-assets/loop.mp4 + main.png … 16:9 ループ + drawtext でテキスト重畳
#
# 引数:
#   $1 collection_path または release_path
#   -s <秒> / -t <秒> は release 型のみ（開始位置 / 切り出し長さ）
#
# 必須 env:
#   SHORT_STARTS     チャプター開始秒のスペース区切り（例: "30 3960 6420"）
#   SHORT_LABELS     チャプターラベルのスペース区切り（例: "chapter1 chapter3 chapter5"）
#
# 任意 env:
#   SHORT_DURATION          既定 20 秒
#   SHORT_FADE_IN           既定 1.0 秒
#   SHORT_FADE_OUT          既定 1.5 秒
#   SHORT_CHANNEL_NAME      loop-mp4 モードで必須
#   SHORT_COLLECTION_NAME   loop-mp4 モードで必須
#   SHORT_FONT              drawtext フォント（既定: Palatino.ttc）
set -euo pipefail

TARGET_DIR="${1:?usage: $(basename "$0") <collection_path|release_path> [-s start_sec] [-t duration_sec]}"
CONTENT_MODEL="$(uv run python -c 'from youtube_automation.configuration import load_config; print(load_config().youtube.content_model.type)')"

if [[ "$CONTENT_MODEL" == "release" ]]; then
  shift || true
  START="30"
  DUR="40"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -s) START="$2"; shift 2 ;;
      -t) DUR="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  RELEASE_LANGUAGES="$(uv run python -c '
import re
from youtube_automation.configuration import load_config
languages = load_config().shorts.release.languages
if not languages or any(not isinstance(lang, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", lang) for lang in languages):
    raise SystemExit("shorts.release.languages must contain nonempty language identifiers")
print(" ".join(languages))
')"
  read -ra LANGUAGES <<< "$RELEASE_LANGUAGES"
  MOTIF="$(basename "$TARGET_DIR" | sed 's/^[0-9]*-//')"
  for LANG in "${LANGUAGES[@]}"; do
    SRC="${TARGET_DIR}/video/${MOTIF}-${LANG}.mp4"
    if [[ ! -s "$SRC" ]]; then
      echo "incomplete: configured release source missing or empty: ${SRC}" >&2
      exit 1
    fi
  done
  for LANG in "${LANGUAGES[@]}"; do
    SRC="${TARGET_DIR}/video/${MOTIF}-${LANG}.mp4"
    OUT="${TARGET_DIR}/video/short-${LANG}.mp4"
    if ffmpeg -y -i "$SRC" \
      -ss "$START" -t "$DUR" \
      -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30" \
      -c:v libx264 -preset "${SHORT_PRESET:-slow}" -crf "${SHORT_CRF:-18}" -pix_fmt yuv420p \
      -c:a aac -b:a "${SHORT_AUDIO_BITRATE:-192k}" \
      "$OUT"; then
      if [[ ! -s "$OUT" ]]; then
        echo "incomplete: release output missing or empty: ${OUT}" >&2
        exit 1
      fi
    else
      rc=$?
      echo "incomplete: release generation failed for ${LANG} (exit=${rc})" >&2
      exit "$rc"
    fi
    echo "✓ $OUT"
  done
  exit 0
fi

if [[ "$CONTENT_MODEL" != "collection" ]]; then
  echo "unsupported content_model.type: $CONTENT_MODEL" >&2
  exit 2
fi

COLLECTION_DIR="$TARGET_DIR"

SHORT_LOOP="${COLLECTION_DIR}/10-assets/short-loop.mp4"
SHORT_PNG="${COLLECTION_DIR}/10-assets/short.png"
LOOP_MP4="${COLLECTION_DIR}/10-assets/loop.mp4"
MASTER_AUDIO="$(ls "${COLLECTION_DIR}"/01-master/*Master*.mp3 2>/dev/null | head -1 || true)"
OUTDIR="${COLLECTION_DIR}/01-master/shorts"
mkdir -p "$OUTDIR"

: "${SHORT_STARTS:?SHORT_STARTS env required (space-separated chapter start seconds)}"
: "${SHORT_LABELS:?SHORT_LABELS env required (space-separated chapter labels)}"
DURATION="${SHORT_DURATION:-20}"
FADE_IN="${SHORT_FADE_IN:-1.0}"
FADE_OUT="${SHORT_FADE_OUT:-1.5}"
FADE_OUT_START="$(awk -v d="$DURATION" -v f="$FADE_OUT" 'BEGIN{printf "%.1f", d-f}')"
CHANNEL_NAME="${SHORT_CHANNEL_NAME:-}"
COLLECTION_NAME="${SHORT_COLLECTION_NAME:-}"
FONT="${SHORT_FONT:-/System/Library/Fonts/Palatino.ttc}"

read -ra STARTS <<< "$SHORT_STARTS"
read -ra LABELS <<< "$SHORT_LABELS"

if [[ ${#STARTS[@]} -ne ${#LABELS[@]} ]]; then
  echo "❌ SHORT_STARTS と SHORT_LABELS の要素数が一致しません" >&2
  exit 1
fi

if [[ -f "$SHORT_LOOP" ]]; then
  MODE="short-loop"
elif [[ -f "$SHORT_PNG" ]]; then
  MODE="short-png"
elif [[ -f "$LOOP_MP4" ]]; then
  MODE="loop-mp4"
else
  echo "❌ 10-assets/ に short-loop.mp4 / short.png / loop.mp4 のいずれも見つかりません" >&2
  exit 1
fi

if [[ -z "$MASTER_AUDIO" ]]; then
  echo "❌ 01-master/*Master*.mp3 が見つかりません" >&2
  exit 1
fi

if [[ "$MODE" == "loop-mp4" && ( -z "$CHANNEL_NAME" || -z "$COLLECTION_NAME" ) ]]; then
  echo "❌ loop-mp4 モードは SHORT_CHANNEL_NAME / SHORT_COLLECTION_NAME env が必要です" >&2
  exit 1
fi

echo "Mode:  $MODE"
echo "Audio: $MASTER_AUDIO"
echo "Out:   $OUTDIR"

pids=()
for i in "${!STARTS[@]}"; do
  START="${STARTS[$i]}"
  LABEL="${LABELS[$i]}"
  NUM="$(printf '%02d' $((i+1)))"
  OUTPUT="${OUTDIR}/short-${NUM}-${LABEL}.mp4"

  case "$MODE" in
    short-loop)
      ffmpeg -y \
        -stream_loop -1 -i "$SHORT_LOOP" \
        -ss "$START" -i "$MASTER_AUDIO" \
        -t "$DURATION" \
        -vf "scale=1080:1920,fps=30,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
        -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
        -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
        -c:a aac -b:a 192k -ar 48000 \
        -shortest -movflags +faststart \
        "$OUTPUT" 2>/dev/null &
      ;;
    short-png)
      ffmpeg -y \
        -i "$SHORT_PNG" \
        -ss "$START" -i "$MASTER_AUDIO" \
        -t "$DURATION" \
        -vf "zoompan=z='min(zoom+0.0008,1.25)':d=600:fps=30:s=1080x1920:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',vignette=PI/4,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
        -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
        -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
        -c:a aac -b:a 192k -ar 48000 \
        -shortest -movflags +faststart \
        "$OUTPUT" 2>/dev/null &
      ;;
    loop-mp4)
      ffmpeg -y \
        -stream_loop -1 -i "$LOOP_MP4" \
        -ss "$START" -i "$MASTER_AUDIO" \
        -t "$DURATION" \
        -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT},drawtext=text='${CHANNEL_NAME}':fontfile=${FONT}:fontsize=32:fontcolor=white@0.85:borderw=2:bordercolor=black@0.4:x=(w-text_w)/2:y=h*0.12:enable='between(t,0.5,5)',drawtext=text='${COLLECTION_NAME}':fontfile=${FONT}:fontsize=44:fontcolor=white@0.95:borderw=3:bordercolor=black@0.5:x=(w-text_w)/2:y=h*0.18:enable='between(t,0.8,5)'" \
        -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
        -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
        -c:a aac -b:a 192k -ar 48000 \
        -shortest -movflags +faststart \
        "$OUTPUT" 2>/dev/null &
      ;;
  esac
  pids+=("$!")
  echo "Started #${NUM}: ${LABEL} (start=${START}s)"
done

echo "Waiting for all jobs..."
job_status=0
for pid in "${pids[@]}"; do
  if wait "$pid"; then
    :
  else
    rc=$?
    echo "ffmpeg job failed (pid=$pid, exit=$rc)" >&2
    if [[ "$job_status" -eq 0 ]]; then
      job_status="$rc"
    fi
  fi
done
if [[ "$job_status" -ne 0 ]]; then
  exit "$job_status"
fi
echo "Done."
ls -lh "$OUTDIR"/*.mp4
