#!/bin/bash
# generate_videos.sh v13 — Master video generator
# Static image + master audio → MP4 (macOS optimized)
# v12.1: ループモードの高ビットレート入力を上限付き正規化に退避
# v12.2: 短尺 master を音声側 stream_loop で動画尺に伸ばす opt-in 経路を追加 (#545)
# v12.3: master-mix.* に加えて lyria/masterup 出力の master.* も検出 (#507)
# v12.4: 映像エフェクト (光の粒子 / ボケ / グラデーション流れ) のオプション追加 (#648)
# v13:   config-driven overlay 合成 (audio_visualizer + subscribe_popup, #511)
#        - `overlays.enabled: true` のときのみ x264 再エンコード経路で
#          `filter_complex` を構築し visualizer + popup を合成
#        - jq 無し / `overlays.enabled: false` / `overlays` 欠落時は
#          既存 stream copy 経路 (v12.1) を完全に維持する
#        - COLLECTION_NAME 抽出 regex を `^[0-9]+-[a-z]+-` →
#          `^[0-9]+-[a-z0-9]+-` に修正 (数字を含む slug を許容)
#
# Usage:
#   bash .claude/skills/videoup/references/generate_videos.sh <collection-path>
#   cd <collection-dir> && bash <repo-root>/.claude/skills/videoup/references/generate_videos.sh
#
# Opt-in env vars (#545):
#   VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN
#     動画側ターゲット尺 (分)。設定時は音声入力にも -stream_loop -1 を適用し
#     -t で動画長を強制する。チャンネル側で config/skills/videoup.yaml に
#     audio.target_video_duration_min を置いても同等 (env が優先)。
#     master 尺 ≥ target のときは従来動作 (master 尺が支配)。
#
# Environment variables (#648):
#   VIDEOUP_EFFECT            none | particles | bokeh | gradient   (default: none)
#       none      : エフェクトなし（ループ動画は stream copy、静止画は従来の libx264 経路）
#       particles : 光の粒子（淡い白点が画面をゆっくり流れる）
#       bokeh     : ボケ（柔らかな円形グラデーションがゆらぐ）
#       gradient  : グラデーション流れ（半透明のカラーグラデーションが上下にうごく）
#   VIDEOUP_EFFECT_INTENSITY  subtle | medium | strong               (default: subtle)
#       透明度・密度をコントロール。基本は subtle 推奨（BGM 視聴の邪魔をしない）
#
# エフェクト有効時、ループ動画背景モードは stream copy ではなく libx264 再エンコードに切り替わる。
# 詳細は .claude/skills/videoup/SKILL.md を参照。
#
# Env (#511):
#   OVERLAYS_CONFIG  config/channel/youtube.json への絶対パス (省略時は
#                    CHANNEL_DIR or COLLECTION_DIR から自動探索)
#   CHANNEL_DIR      チャンネルリポジトリのルート (Python loader と同じ規約)

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
# 旧: `^[0-9]+-[a-z]+-` だと `20260101-r2d2-foo` のような数字混じり slug が
# 後ろの `-collection` 除去だけで残ってしまうため、`[a-z0-9]+` に緩めて
# 「日付-スラッグ-」プレフィックスを正しく剥がす (#511)。
dir_basename="$(basename "$COLLECTION_DIR")"
COLLECTION_NAME="$(echo "$dir_basename" \
    | sed -E 's/^[0-9]+-[a-z0-9]+-//; s/-collection$//' \
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

# 検出順:
#   1. `master-mix.{wav,m4a,aac,mp3,flac}` — DAW バウンス・手動配置 (優先)
#   2. `master.{wav,m4a,aac,mp3,flac}` — `/lyria` / `/masterup` (`yt-generate-master`) の自動生成出力 (#507)
# 拡張子は wav 優先、なければ m4a / aac / mp3 / flac の順
MASTER_AUDIO=""
for basename in master-mix master; do
    for ext in wav m4a aac mp3 flac; do
        candidate="${MASTER_DIR}/${basename}.${ext}"
        if [[ -f "$candidate" ]]; then
            MASTER_AUDIO="$candidate"
            break 2
        fi
    done
done

MASTER_OUTPUT="${MASTER_DIR}/${COLLECTION_NAME}-Master.mp4"
LOOP_TARGET_WIDTH="1920"
LOOP_TARGET_HEIGHT="1080"
LOOP_TARGET_PIX_FMT="yuv420p"
LOOP_TARGET_FRAME_RATE="24/1"
LOOP_OUTPUT_FRAME_RATE="24"
LOOP_MAX_BITRATE="6000k"
LOOP_BUFSIZE="12000k"

# ─── Video Effects (#648) ────────────────────────────────
# VIDEOUP_EFFECT / VIDEOUP_EFFECT_INTENSITY を読み取り、ffmpeg filtergraph を構築する
EFFECT="${VIDEOUP_EFFECT:-none}"
EFFECT_INTENSITY="${VIDEOUP_EFFECT_INTENSITY:-subtle}"

# 値検証
case "$EFFECT" in
    none|particles|bokeh|gradient) ;;
    *)
        echo "ERROR: Unknown VIDEOUP_EFFECT='$EFFECT' (allowed: none, particles, bokeh, gradient)"
        exit 1
        ;;
esac
case "$EFFECT_INTENSITY" in
    subtle|medium|strong) ;;
    *)
        echo "ERROR: Unknown VIDEOUP_EFFECT_INTENSITY='$EFFECT_INTENSITY' (allowed: subtle, medium, strong)"
        exit 1
        ;;
esac

# intensity → 透明度 (低いほど目立たない)
# particles: 粒の密度・明度に効く / bokeh: 円のコントラストに効く / gradient: alpha に効く
case "$EFFECT_INTENSITY" in
    subtle) EFFECT_ALPHA="0.10" ;;
    medium) EFFECT_ALPHA="0.20" ;;
    strong) EFFECT_ALPHA="0.35" ;;
esac

# 1920x1080 / 24fps を前提とした filtergraph を組み立てる
# 第 1 引数 = 入力ビデオストリームのラベル（例: "0:v" や "scaled"）
# 出力は [vout] 固定
build_effect_filter() {
    local input_label="$1"
    case "$EFFECT" in
        none)
            echo ""
            ;;
        particles)
            # 光の粒子: ランダムドットを生成 → 上下に slow scroll → 元映像へオーバーレイ
            echo "[${input_label}]format=yuv420p,setsar=1[bg];\
color=c=black:s=1920x2160:r=24:d=1,format=yuv420p,\
noise=alls=80:allf=t+u,\
geq=lum='if(gt(lum(X,Y),230),255,0)':a='if(gt(lum(X,Y),230),${EFFECT_ALPHA}*255,0)',\
loop=loop=-1:size=1:start=0,\
crop=1920:1080:0:'mod(t*30,1080)'[fx];\
[bg][fx]overlay=0:0:format=auto,format=yuv420p[vout]"
            ;;
        bokeh)
            # ボケ: 色付きドットを巨大スケール + gblur で円形ぼかし → ゆっくり揺れる動き
            # noise alls は 0-100 範囲制約があるため上限内に収める
            echo "[${input_label}]format=yuv420p,setsar=1[bg];\
color=c=0xffe8b0:s=240x135:r=24:d=1,format=yuv420p,\
noise=alls=100:allf=t+u,\
geq=lum='if(gt(lum(X,Y),240),255,0)':a='if(gt(lum(X,Y),240),${EFFECT_ALPHA}*255,0)',\
loop=loop=-1:size=1:start=0,\
scale=1920:1080:flags=lanczos,\
gblur=sigma=18[fx];\
[bg][fx]overlay='40*sin(t/3)':'30*cos(t/4)':format=auto,format=yuv420p[vout]"
            ;;
        gradient)
            # グラデーション流れ: カラーグラデーションを上下にゆっくり流す
            echo "[${input_label}]format=yuv420p,setsar=1[bg];\
gradients=s=1920x2160:c0=0x1a3a8a:c1=0xff8a3a:r=24:duration=120:type=linear,\
crop=1920:1080:0:'mod(t*15,1080)',\
format=yuva420p,\
geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='${EFFECT_ALPHA}*255'[fx];\
[bg][fx]overlay=0:0:format=auto,format=yuv420p[vout]"
            ;;
    esac
}

EFFECT_FILTER_LOOP="$(build_effect_filter "0:v")"
EFFECT_FILTER_STATIC="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[scaled];$(build_effect_filter "scaled")"

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

# ─── Overlays config (#511) ─────────────────────────────
# overlays.enabled = true かつ jq があるときだけ filter_complex 経路に分岐。
# どれか 1 つでも欠ければ既存 stream copy 経路へフォールバックする。
OVERLAYS_ENABLED=0
OVERLAYS_CONFIG_PATH=""

resolve_overlays_config() {
    if [[ -n "${OVERLAYS_CONFIG:-}" && -f "$OVERLAYS_CONFIG" ]]; then
        echo "$OVERLAYS_CONFIG"
        return
    fi
    local candidates=()
    if [[ -n "${CHANNEL_DIR:-}" ]]; then
        candidates+=("${CHANNEL_DIR}/config/channel/youtube.json")
    fi
    # COLLECTION_DIR から祖先を辿って config/channel/youtube.json を探す
    local dir="$COLLECTION_DIR"
    while [[ "$dir" != "/" && -n "$dir" ]]; do
        candidates+=("${dir}/config/channel/youtube.json")
        dir="$(dirname "$dir")"
    done
    for c in "${candidates[@]}"; do
        if [[ -f "$c" ]]; then
            echo "$c"
            return
        fi
    done
}

if command -v jq &>/dev/null; then
    OVERLAYS_CONFIG_PATH="$(resolve_overlays_config)"
    if [[ -n "$OVERLAYS_CONFIG_PATH" ]]; then
        ov_enabled="$(jq -r '(.overlays.enabled // false) | tostring' "$OVERLAYS_CONFIG_PATH" 2>/dev/null)"
        if [[ "$ov_enabled" == "true" ]]; then
            OVERLAYS_ENABLED=1
        fi
    fi
fi

ov_get() {
    # $1: jq path expression (without leading dot)
    # $2: fallback value
    local expr="$1"
    local fallback="$2"
    local v
    v="$(jq -r "(${expr}) // empty" "$OVERLAYS_CONFIG_PATH" 2>/dev/null)"
    if [[ -z "$v" || "$v" == "null" ]]; then
        echo "$fallback"
    else
        echo "$v"
    fi
}

# ─── Prerequisites ───────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found"; exit 1
fi
if [[ -z "$THUMBNAIL" ]]; then
    echo "ERROR: No thumbnail found in ${ASSETS_DIR}/ (main.jpg/png or thumbnail.jpg/png)"; exit 1
fi
if [[ -z "$MASTER_AUDIO" ]]; then
    echo "ERROR: master-mix.{wav,m4a,aac,mp3,flac} または master.{wav,m4a,aac,mp3,flac} not found in ${MASTER_DIR}/"; exit 1
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
echo "  generate_videos.sh v13 — ${COLLECTION_NAME}"
echo "  ──────────────────────────────────────────"
echo ""
if [[ -n "$LOOP_VIDEO" ]]; then
    echo "  Video BG : $(basename "$LOOP_VIDEO") (loop)"
else
    echo "  Thumbnail: $(basename "$THUMBNAIL")"
fi
echo "  Audio    : $(basename "$MASTER_AUDIO")"
echo "  Output   : $(basename "$MASTER_OUTPUT")"
if [[ "$EFFECT" != "none" ]]; then
    echo "  Effect   : $EFFECT (intensity=$EFFECT_INTENSITY, alpha=$EFFECT_ALPHA)"
fi
if [[ "$OVERLAYS_ENABLED" -eq 1 ]]; then
    echo "  Overlays : enabled ($(basename "$OVERLAYS_CONFIG_PATH"))"
fi

duration="$(get_duration "$MASTER_AUDIO")"

# ─── target_video_duration_min 解決 (#545) ──────────────
# env > channel override (config/skills/videoup.yaml) > 未設定
# 未設定なら従来動作 (音声尺 = 動画尺)。設定時は音声側にも -stream_loop -1 を
# 適用し -t target_video_duration_sec で動画長を強制する。
# master 尺 ≥ target のときは現状動作維持 (master 尺が支配)。
read_skill_config_target_video_duration_min() {
    # channel root を COLLECTION_DIR から最大 5 階層上まで探索
    # （`config/skills/videoup.yaml` を持つディレクトリを channel root とみなす）
    local dir="$COLLECTION_DIR"
    local override=""
    for _ in 1 2 3 4 5; do
        if [[ -f "$dir/config/skills/videoup.yaml" ]]; then
            override="$dir/config/skills/videoup.yaml"
            break
        fi
        local parent
        parent="$(dirname "$dir")"
        if [[ "$parent" == "$dir" ]]; then
            break
        fi
        dir="$parent"
    done
    if [[ -z "$override" || ! -f "$override" ]]; then
        return 0
    fi
    # flat 抽出: audio: ブロック配下の `target_video_duration_min:` 行を拾う。
    # コメント行は除外。値はクォート無し数値前提 (`60` / `120` / `90.0` 等)。
    awk '
        /^[[:space:]]*#/ { next }
        /^audio:[[:space:]]*$/ { in_audio = 1; next }
        /^[^[:space:]#]/ { in_audio = 0 }
        in_audio && /target_video_duration_min:[[:space:]]*[0-9]+(\.[0-9]+)?/ {
            sub(/.*target_video_duration_min:[[:space:]]*/, "")
            sub(/[[:space:]]*(#.*)?$/, "")
            print
            exit
        }
    ' "$override"
}

TARGET_VIDEO_DURATION_MIN="${VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN:-}"
if [[ -z "$TARGET_VIDEO_DURATION_MIN" ]]; then
    TARGET_VIDEO_DURATION_MIN="$(read_skill_config_target_video_duration_min)"
fi

AUDIO_INPUT_OPTS=()
video_duration="$duration"
if [[ -n "$TARGET_VIDEO_DURATION_MIN" ]]; then
    target_video_duration_sec="$(awk "BEGIN{printf \"%.2f\", $TARGET_VIDEO_DURATION_MIN * 60}")"
    # duration が取得できない (空 / 数値でない) ケースは fail-safe で従来動作にフォールバック
    master_duration_for_compare="${duration:-0}"
    if awk "BEGIN{exit !($target_video_duration_sec > $master_duration_for_compare)}"; then
        AUDIO_INPUT_OPTS=(-stream_loop -1)
        video_duration="$target_video_duration_sec"
        echo "  Target   : ${TARGET_VIDEO_DURATION_MIN} min ($(format_duration "$video_duration")) — audio loop enabled"
    else
        echo "  Target   : ${TARGET_VIDEO_DURATION_MIN} min ignored (master ≥ target; master 尺が支配)"
    fi
fi

echo "  Duration : $(format_duration "$video_duration")"
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
if [[ "$OVERLAYS_ENABLED" -eq 1 ]]; then
    # Overlay 経路 (#511): visualizer + subscribe popup を合成する。
    # この経路では `-c:v copy` は不可能 (filter_complex を通すため) なので
    # encoder セクションのパラメータで x264 再エンコードする。
    av_enabled="$(ov_get '.overlays.audio_visualizer.enabled' 'false')"
    sp_enabled="$(ov_get '.overlays.subscribe_popup.enabled' 'false')"

    av_mode="$(ov_get '.overlays.audio_visualizer.mode' 'bar')"
    av_size="$(ov_get '.overlays.audio_visualizer.size' '1280x180')"
    av_rate="$(ov_get '.overlays.audio_visualizer.rate' '24')"
    av_fscale="$(ov_get '.overlays.audio_visualizer.fscale' 'log')"
    av_win_size="$(ov_get '.overlays.audio_visualizer.win_size' '2048')"
    av_win_func="$(ov_get '.overlays.audio_visualizer.win_func' 'hann')"
    av_colors="$(ov_get '.overlays.audio_visualizer.colors' 'white')"
    av_position="$(ov_get '.overlays.audio_visualizer.position' '(W-w)/2:H-h-40')"
    av_opacity="$(ov_get '.overlays.audio_visualizer.opacity' '0.85')"
    av_glow_enabled="$(ov_get '.overlays.audio_visualizer.glow_enabled' 'true')"
    av_glow_sigma="$(ov_get '.overlays.audio_visualizer.glow_sigma' '12')"
    av_glow_opacity="$(ov_get '.overlays.audio_visualizer.glow_opacity' '0.45')"

    sp_image="$(ov_get '.overlays.subscribe_popup.image' 'subscribe-popup.png')"
    sp_start="$(ov_get '.overlays.subscribe_popup.start_sec' '5')"
    sp_duration="$(ov_get '.overlays.subscribe_popup.duration_sec' '8')"
    sp_fade="$(ov_get '.overlays.subscribe_popup.fade_sec' '0.6')"
    sp_position="$(ov_get '.overlays.subscribe_popup.position' 'W-w-40:40')"

    enc_codec="$(ov_get '.overlays.encoder.codec' 'libx264')"
    enc_preset="$(ov_get '.overlays.encoder.preset' 'medium')"
    enc_crf="$(ov_get '.overlays.encoder.crf' '20')"
    enc_pix_fmt="$(ov_get '.overlays.encoder.pix_fmt' 'yuv420p')"
    enc_maxrate="$(ov_get '.overlays.encoder.maxrate' '4M')"
    enc_bufsize="$(ov_get '.overlays.encoder.bufsize' '8M')"
    enc_profile="$(ov_get '.overlays.encoder.profile' 'high')"
    enc_framerate="$(ov_get '.overlays.encoder.framerate' '24')"

    # 入力配列: [0]=背景 (loop or thumbnail), [1]=master audio, [2]=popup PNG (任意)
    INPUTS=()
    if [[ -n "$LOOP_VIDEO" ]]; then
        INPUTS+=(-stream_loop -1 -i "$LOOP_VIDEO")
    else
        INPUTS+=(-framerate "$enc_framerate" -loop 1 -i "$THUMBNAIL")
    fi
    INPUTS+=(-i "$MASTER_AUDIO")

    sp_input_idx=""
    if [[ "$sp_enabled" == "true" ]]; then
        sp_path=""
        if [[ "$sp_image" = /* ]]; then
            sp_path="$sp_image"
        elif [[ -f "${ASSETS_DIR}/${sp_image}" ]]; then
            sp_path="${ASSETS_DIR}/${sp_image}"
        elif [[ -f "${COLLECTION_DIR}/${sp_image}" ]]; then
            sp_path="${COLLECTION_DIR}/${sp_image}"
        fi
        if [[ -z "$sp_path" || ! -f "$sp_path" ]]; then
            echo "  WARN: subscribe popup image not found: ${sp_image} (overlay 経路だが popup はスキップ)"
            sp_enabled="false"
        else
            INPUTS+=(-loop 1 -i "$sp_path")
            sp_input_idx=2
        fi
    fi

    # filter_complex 構築
    # 背景は事前に scale + pad で 1920x1080 / yuv420p に揃える
    FILTER="[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=${enc_framerate}[bg];"
    CURRENT_LABEL="bg"

    if [[ "$av_enabled" == "true" ]]; then
        # showfreqs ベースの bar visualizer (透過 RGBA) を生成
        FILTER+="[1:a]asplit=2[avis_in][a_out];"
        FILTER+="[avis_in]showfreqs=mode=${av_mode}:s=${av_size}:rate=${av_rate}:fscale=${av_fscale}:win_size=${av_win_size}:win_func=${av_win_func}:colors=${av_colors},format=rgba,colorchannelmixer=aa=${av_opacity}[avis];"
        if [[ "$av_glow_enabled" == "true" ]]; then
            FILTER+="[avis]split=2[avis_core][avis_glow_src];"
            FILTER+="[avis_glow_src]gblur=sigma=${av_glow_sigma},colorchannelmixer=aa=${av_glow_opacity}[avis_glow];"
            FILTER+="[${CURRENT_LABEL}][avis_glow]overlay=${av_position}:format=auto[bg_glow];"
            FILTER+="[bg_glow][avis_core]overlay=${av_position}:format=auto[bg_av];"
        else
            FILTER+="[${CURRENT_LABEL}][avis]overlay=${av_position}:format=auto[bg_av];"
        fi
        CURRENT_LABEL="bg_av"
        AUDIO_LABEL="a_out"
    else
        AUDIO_LABEL="1:a"
    fi

    if [[ "$sp_enabled" == "true" ]]; then
        sp_end="$(awk "BEGIN{printf \"%.3f\", ${sp_start} + ${sp_duration}}")"
        sp_fade_out_start="$(awk "BEGIN{printf \"%.3f\", ${sp_end} - ${sp_fade}}")"
        FILTER+="[${sp_input_idx}:v]format=rgba,fade=t=in:st=${sp_start}:d=${sp_fade}:alpha=1,fade=t=out:st=${sp_fade_out_start}:d=${sp_fade}:alpha=1[popup];"
        FILTER+="[${CURRENT_LABEL}][popup]overlay=${sp_position}:enable='between(t,${sp_start},${sp_end})':format=auto[vout];"
        CURRENT_LABEL="vout"
    fi

    # 末尾ラベル統一: 最終 video ラベルが CURRENT_LABEL
    ffmpeg -y "${INPUTS[@]}" \
        -filter_complex "$FILTER" \
        -map "[${CURRENT_LABEL}]" -map "[${AUDIO_LABEL}]" \
        -c:v "$enc_codec" -preset "$enc_preset" -crf "$enc_crf" \
        -maxrate "$enc_maxrate" -bufsize "$enc_bufsize" \
        -profile:v "$enc_profile" -pix_fmt "$enc_pix_fmt" \
        -r "$enc_framerate" \
        "${AUDIO_OUT_OPTS[@]}" \
        -t "$duration" \
        -movflags +faststart \
        -shortest \
        -loglevel error \
        -progress "$PROGRESS_FILE" \
        "$MASTER_OUTPUT" &
elif [[ -n "$LOOP_VIDEO" ]]; then
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

    if [[ "$EFFECT" == "none" ]]; then
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (stream copy)"
        # Stream copy 経路: ビデオは完全無損失（ビット単位コピー）、音声は AUDIO_OUT_OPTS に従う
        # AUDIO_INPUT_OPTS は target_video_duration_min 設定時のみ -stream_loop -1 を持つ (#545)
        ffmpeg -y -stream_loop -1 -i "$LOOP_SOURCE" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -map 0:v:0 -map 1:a:0 \
            -c:v copy \
            "${AUDIO_OUT_OPTS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    else
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (loop + ${EFFECT} effect)"
        # エフェクト有効: ループ素材を libx264 で再エンコードしながら filtergraph をオーバーレイ (#648)
        # 容量増を抑えるため CRF 22 / preset medium / maxrate ガードを共通定数と揃える
        ffmpeg -y -stream_loop -1 -i "$LOOP_SOURCE" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -filter_complex "$EFFECT_FILTER_LOOP" \
            -map "[vout]" -map 1:a:0 \
            -c:v libx264 -preset medium -crf 22 -maxrate "$LOOP_MAX_BITRATE" -bufsize "$LOOP_BUFSIZE" -pix_fmt yuv420p \
            -r "$LOOP_OUTPUT_FRAME_RATE" \
            "${AUDIO_OUT_OPTS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    fi
else
    if [[ "$EFFECT" == "none" ]]; then
        echo "  [Step 1/1] Generating master video (still image)"
        # 静止画背景モード（従来）
        # I-frame を 5 分間隔（1fps なので 300 フレーム）に間引き、変化のないフレームを P-frame で
        # 圧縮することで master.mp4 を大幅に小型化する（#579）。keyint=1 全 I-frame 化は容量が膨らむため廃止。
        # AUDIO_INPUT_OPTS は target_video_duration_min 設定時のみ -stream_loop -1 を持つ (#545)
        ffmpeg -y -framerate 1 -loop 1 -i "$THUMBNAIL" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -c:v libx264 -tune stillimage -preset medium -crf 28 -pix_fmt yuv420p \
            -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
            -g 300 \
            -r 1 \
            "${AUDIO_OUT_OPTS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    else
        echo "  [Step 1/1] Generating master video (still image + ${EFFECT} effect)"
        # エフェクト有効: 静止画背景を 24fps で再エンコードしながら filtergraph をオーバーレイ (#648)
        # 静止画モードは映像が動かないため、エフェクトを目立たせるには 24fps で書き出す必要がある
        ffmpeg -y -framerate 24 -loop 1 -i "$THUMBNAIL" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -filter_complex "$EFFECT_FILTER_STATIC" \
            -map "[vout]" -map 1:a:0 \
            -c:v libx264 -preset medium -crf 24 -pix_fmt yuv420p \
            -r 24 \
            "${AUDIO_OUT_OPTS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    fi
fi
ffmpeg_pid=$!

# ─── Progress Bar ─────────────────────────────────────────
total_us=$(awk "BEGIN{printf \"%.0f\", $video_duration * 1000000}")
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
echo "    Duration: $(format_duration "$video_duration")"
echo "    Time    : $((elapsed/60))m $((elapsed%60))s"
echo ""
