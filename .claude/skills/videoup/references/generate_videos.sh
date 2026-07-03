#!/bin/bash
# generate_videos.sh v14 — Master video generator
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
# v14:   映像エフェクト (#648) をループ・ベイク化して高速化 + 設定を config 駆動化
#        - effect ON は「1 周期だけ fx_baked.mp4 に焼く → -stream_loop -1 -c:v copy」へ刷新し
#          モード C/D の全尺再エンコード(8-15分)を ~1-2分へ短縮。継ぎ目は closed GOP の stream copy で無損失
#        - 周期固定: particles=36s / bokeh=60s(整数周期化) / gradient=72s(speed=0 で静的化)
#        - 静止画/ループのエンコード値・effect・shrink を config/skills/videoup.yaml から取得
#          (新規 env override は追加しない。キー欠落時は現行の固定値へフォールバック=無回帰)
#        - shrink.enabled で生成後の容量最適化 re-encode を opt-in 追加
# v14.1: workflow-state.json::assets.master_audio があれば固定名探索より優先 (#1449)
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

# ─── Config (config/skills/videoup.yaml) reader ──────────
# 設定は env override ではなく config ファイル駆動（既存 audio.target_video_duration_min と同流儀）。
# 2-level flat YAML を awk で読む（jq 非依存）。キー欠落時は fallback（=現行固定値）へ落ちる。
resolve_videoup_yaml() {
    local dir="$COLLECTION_DIR"
    for _ in 1 2 3 4 5 6; do
        if [[ -f "$dir/config/skills/videoup.yaml" ]]; then
            echo "$dir/config/skills/videoup.yaml"; return
        fi
        local parent; parent="$(dirname "$dir")"
        [[ "$parent" == "$dir" ]] && break
        dir="$parent"
    done
}
VIDEOUP_YAML="$(resolve_videoup_yaml)"

resolve_loop_video_yaml() {
    local dir="$COLLECTION_DIR"
    for _ in 1 2 3 4 5 6; do
        if [[ -f "$dir/config/skills/loop-video.yaml" ]]; then
            echo "$dir/config/skills/loop-video.yaml"; return
        fi
        local parent; parent="$(dirname "$dir")"
        [[ "$parent" == "$dir" ]] && break
        dir="$parent"
    done
}
LOOP_VIDEO_YAML="$(resolve_loop_video_yaml)"

yaml_get() {
    # $1=section $2=key $3=fallback  （`section:` 配下の `  key: value` を拾う）
    local section="$1" key="$2" fallback="$3" val
    if [[ -z "$VIDEOUP_YAML" || ! -f "$VIDEOUP_YAML" ]]; then
        echo "$fallback"; return
    fi
    val="$(awk -v section="$section" -v key="$key" '
        /^[^[:space:]#]/ { in_section = ($0 ~ ("^" section ":[[:space:]]*$")) ? 1 : 0; next }
        in_section && $0 ~ ("^[[:space:]]+" key ":") {
            line = $0
            sub(/^[[:space:]]+[^:]+:[[:space:]]*/, "", line)
            sub(/[[:space:]]*#.*$/, "", line)
            sub(/[[:space:]]+$/, "", line)
            print line
            exit
        }
    ' "$VIDEOUP_YAML")"
    # 周囲のクォートを除去
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    if [[ -z "$val" ]]; then echo "$fallback"; else echo "$val"; fi
}

yaml_top_get() {
    # $1=file $2=key $3=fallback  （top-level の `key: value` を拾う）
    local file="$1" key="$2" fallback="$3" val
    if [[ -z "$file" || ! -f "$file" ]]; then
        echo "$fallback"; return
    fi
    val="$(awk -v key="$key" '
        $0 ~ ("^" key ":[[:space:]]*") {
            line = $0
            sub(/^[^:]+:[[:space:]]*/, "", line)
            sub(/[[:space:]]*#.*$/, "", line)
            sub(/[[:space:]]+$/, "", line)
            print line
            exit
        }
    ' "$file")"
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    if [[ -z "$val" ]]; then echo "$fallback"; else echo "$val"; fi
}

stat_mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }

# effect の 1 ループ周期（秒）。filter を整数周期に揃えてあるので定数で持つ。
effect_period() {
    case "$EFFECT" in
        particles) echo 36 ;;
        bokeh)     echo 60 ;;
        gradient)  echo 72 ;;
        *)         echo 0  ;;
    esac
}
_gcd() { local a=$1 b=$2 t; while [[ $b -ne 0 ]]; do t=$b; b=$((a % b)); a=$t; done; echo "$a"; }
_lcm() { local a=$1 b=$2; if [[ $a -le 0 || $b -le 0 ]]; then echo 0; else echo $(( a / $(_gcd "$a" "$b") * b )); fi; }

# ─── Auto-detect Collection Name ─────────────────────────
# 旧: `^[0-9]+-[a-z]+-` だと `20260101-r2d2-foo` のような数字混じり slug が
# 後ろの `-collection` 除去だけで残ってしまうため、`[a-z0-9]+` に緩めて
# 「日付-スラッグ-」プレフィックスを正しく剥がす (#511)。
dir_basename="$(basename "$COLLECTION_DIR")"
COLLECTION_NAME="$(echo "$dir_basename" \
    | sed -E 's/^[0-9]+-[a-z0-9]+-//; s/-collection$//' \
    | awk -F'-' '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2); print}' OFS='-')"

# ─── Auto-detect Assets ─────────────────────────────────
LOOP_VIDEO_ENABLED="$(yaml_top_get "$LOOP_VIDEO_YAML" enabled true)"
LOOP_VIDEO=""
if [[ "$LOOP_VIDEO_ENABLED" == "false" ]]; then
    echo "  Loop     : disabled by config/skills/loop-video.yaml — 静止画モードで出力します"
elif [[ -f "${ASSETS_DIR}/loop.mp4" ]]; then
    LOOP_VIDEO="${ASSETS_DIR}/loop.mp4"
    echo "  Loop     : $(basename "${LOOP_VIDEO}") (detected)"
else
    echo "  Loop     : not found — 静止画モードで出力します"
    loop_artifacts=()
    for f in "${ASSETS_DIR}"/loop_raw.mp4 "${ASSETS_DIR}"/loop-v*.mp4; do
        [[ -f "$f" ]] && loop_artifacts+=("$f")
    done
    if [[ ${#loop_artifacts[@]} -gt 0 ]]; then
        echo "  ⚠️  生成途中の痕跡が存在します: ${loop_artifacts[*]##*/}"
        echo "     → yt-generate-loop-video で再生成するか、手動で loop.mp4 を配置してください"
    fi
fi

VIDEO_BACKGROUND=""
for candidate in "${ASSETS_DIR}/main.png" "${ASSETS_DIR}/main.jpg"; do
    if [[ -f "$candidate" ]]; then
        VIDEO_BACKGROUND="$candidate"
        break
    fi
done

workflow_state_master_audio() {
    local state_path="${COLLECTION_DIR}/workflow-state.json"
    [[ -e "$state_path" ]] || return 1
    if [[ ! -f "$state_path" ]]; then
        echo "ERROR: workflow-state.json must be a file: ${state_path}" >&2
        return 2
    fi
    if ! command -v python3 &>/dev/null; then
        echo "ERROR: python3 is required to read workflow-state.json::assets.master_audio" >&2
        return 2
    fi
    python3 - "$state_path" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except json.JSONDecodeError as exc:
    print(f"ERROR: workflow-state.json is invalid JSON: {exc}", file=sys.stderr)
    sys.exit(2)
except OSError as exc:
    print(f"ERROR: workflow-state.json could not be read: {exc}", file=sys.stderr)
    sys.exit(2)

if not isinstance(data, dict):
    print("ERROR: workflow-state.json root must be an object", file=sys.stderr)
    sys.exit(2)

assets = data.get("assets", {}) if "assets" not in data else data["assets"]
if not isinstance(assets, dict):
    print("ERROR: workflow-state.json::assets must be an object", file=sys.stderr)
    sys.exit(2)

value = assets.get("master_audio")
if value is None or value == "":
    sys.exit(1)
if not isinstance(value, str):
    print("ERROR: workflow-state.json::assets.master_audio must be a string", file=sys.stderr)
    sys.exit(2)
print(value)
PY
}

# 検出順:
#   1. `workflow-state.json::assets.master_audio` — `/wf-next` が確定した最終マスター
#   2. `master-mix.{wav,m4a,aac,mp3,flac}` — DAW バウンス・手動配置
#   3. `master.{wav,m4a,aac,mp3,flac}` — `/lyria` / `/masterup` (`yt-generate-master`) の自動生成出力 (#507)
# 拡張子は wav 優先、なければ m4a / aac / mp3 / flac の順
MASTER_AUDIO=""
STATE_MASTER_AUDIO=""
workflow_state_status=0
STATE_MASTER_AUDIO="$(workflow_state_master_audio)" || workflow_state_status=$?
if [[ "$workflow_state_status" -eq 2 ]]; then
    exit 1
fi
if [[ -n "$STATE_MASTER_AUDIO" ]]; then
    if [[ "$STATE_MASTER_AUDIO" == */* || "$STATE_MASTER_AUDIO" == *..* ]]; then
        echo "ERROR: workflow-state.json::assets.master_audio must be a filename: ${STATE_MASTER_AUDIO}"
        exit 1
    fi
    candidate="${MASTER_DIR}/${STATE_MASTER_AUDIO}"
    if [[ ! -f "$candidate" ]]; then
        echo "ERROR: workflow-state.json::assets.master_audio not found in ${MASTER_DIR}/: ${STATE_MASTER_AUDIO}"
        exit 1
    fi
    MASTER_AUDIO="$candidate"
else
    for basename in master-mix master; do
        for ext in wav m4a aac mp3 flac; do
            candidate="${MASTER_DIR}/${basename}.${ext}"
            if [[ -f "$candidate" ]]; then
                MASTER_AUDIO="$candidate"
                break 2
            fi
        done
    done
fi

MASTER_OUTPUT="${MASTER_DIR}/${COLLECTION_NAME}-Master.mp4"
LOOP_TARGET_WIDTH="1920"
LOOP_TARGET_HEIGHT="1080"
LOOP_TARGET_PIX_FMT="yuv420p"
LOOP_TARGET_FRAME_RATE="24/1"
LOOP_OUTPUT_FRAME_RATE="24"
LOOP_MAX_BITRATE="$(yaml_get video loop_maxrate 6000k)"
LOOP_BUFSIZE="$(yaml_get video loop_bufsize 12000k)"
# 静止画(effect 無し)のエンコード値も config 駆動（fallback=現行値）
STILL_FPS="$(yaml_get video still_fps 1)"
STILL_CRF="$(yaml_get video still_crf 28)"
STILL_GOP="$(yaml_get video still_gop 300)"
# effect ベイクの内部定数（静止画 effect は 24fps で焼く / ベイク尺の上限ガード）
STILL_EFFECT_FPS=24
STILL_EFFECT_CRF=24
BAKE_MAX_LEN=900

# ─── Video Effects (#648) ────────────────────────────────
# VIDEOUP_EFFECT / VIDEOUP_EFFECT_INTENSITY を読み取り、ffmpeg filtergraph を構築する
# config を一次ソースに（effect.type / effect.intensity）。
# 既存 VIDEOUP_EFFECT / VIDEOUP_EFFECT_INTENSITY env は #648 互換の legacy fallback としてのみ残す。
EFFECT="$(yaml_get effect type "${VIDEOUP_EFFECT:-none}")"
EFFECT_INTENSITY="$(yaml_get effect intensity "${VIDEOUP_EFFECT_INTENSITY:-subtle}")"

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
            # ボケ: 色付きドットを巨大スケール + gblur で円形ぼかし → 60s 周期でゆっくり揺れる
            # overlay の sin/cos は 2*PI*t/60 で x/y とも 60s 周期に揃え、ベイクの継ぎ目をシームレスにする
            # noise alls は 0-100 範囲制約があるため上限内に収める
            echo "[${input_label}]format=yuv420p,setsar=1[bg];\
color=c=0xffe8b0:s=240x135:r=24:d=1,format=yuv420p,\
noise=alls=100:allf=t+u,\
geq=lum='if(gt(lum(X,Y),240),255,0)':a='if(gt(lum(X,Y),240),${EFFECT_ALPHA}*255,0)',\
loop=loop=-1:size=1:start=0,\
scale=1920:1080:flags=lanczos,\
gblur=sigma=18[fx];\
[bg][fx]overlay='40*sin(2*PI*t/60)':'30*cos(2*PI*t/60)':format=auto,format=yuv420p[vout]"
            ;;
        gradient)
            # グラデーション流れ: 静的グラデーション(speed=0)を crop で上下に流す → 72s 周期でシームレス
            # speed=0 で色回転を止めて motion を crop の mod(t*15,1080)=72s 周期だけに限定し、ベイクの継ぎ目を消す
            echo "[${input_label}]format=yuv420p,setsar=1[bg];\
gradients=s=1920x2160:c0=0x1a3a8a:c1=0xff8a3a:r=24:speed=0:type=linear,\
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
if [[ -z "$VIDEO_BACKGROUND" && -z "$LOOP_VIDEO" ]]; then
    echo "ERROR: No video background found in ${ASSETS_DIR}/ (main.png or main.jpg required; thumbnail.jpg/png is upload-only)"; exit 1
fi
if [[ -z "$MASTER_AUDIO" ]]; then
    echo "ERROR: workflow-state.json::assets.master_audio, master-mix.{wav,m4a,aac,mp3,flac}, or master.{wav,m4a,aac,mp3,flac} not found in ${MASTER_DIR}/"; exit 1
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
echo "  generate_videos.sh v14 — ${COLLECTION_NAME}"
echo "  ──────────────────────────────────────────"
echo ""
if [[ -n "$LOOP_VIDEO" ]]; then
    echo "  Video BG : $(basename "$LOOP_VIDEO") (loop)"
else
    echo "  Video BG : $(basename "$VIDEO_BACKGROUND") (still)"
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
# env (VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN, 既存) >
#   config/skills/videoup.yaml::audio.target_video_duration_min > 未設定
# 未設定なら従来動作 (音声尺 = 動画尺)。設定時は音声側にも -stream_loop -1 を
# 適用し -t target_video_duration_sec で動画長を強制する。
# master 尺 ≥ target のときは現状動作維持 (master 尺が支配)。
TARGET_VIDEO_DURATION_MIN="${VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN:-}"
if [[ -z "$TARGET_VIDEO_DURATION_MIN" ]]; then
    TARGET_VIDEO_DURATION_MIN="$(yaml_get audio target_video_duration_min "")"
fi

AUDIO_INPUT_OPTS=()
AUDIO_LOOP_ACTIVE=0
AUDIO_LOUDNORM=""
video_duration="$duration"
if [[ -n "$TARGET_VIDEO_DURATION_MIN" ]]; then
    # 数値バリデーション: 整数 or 小数のみ許容
    if ! [[ "$TARGET_VIDEO_DURATION_MIN" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        echo "ERROR: invalid target_video_duration_min value: '${TARGET_VIDEO_DURATION_MIN}' (must be numeric)"
        exit 1
    fi
    target_video_duration_sec="$(awk -v target="$TARGET_VIDEO_DURATION_MIN" 'BEGIN{printf "%.2f", target * 60}')"
    # duration が取得できない (空 / 数値でない) ケースは fail-safe で従来動作にフォールバック
    master_duration_for_compare="${duration:-0}"
    if awk -v target="$target_video_duration_sec" -v master="$master_duration_for_compare" 'BEGIN{exit !(target > master)}'; then
        AUDIO_INPUT_OPTS=(-stream_loop -1)
        AUDIO_LOOP_ACTIVE=1
        video_duration="$target_video_duration_sec"
        echo "  Target   : ${TARGET_VIDEO_DURATION_MIN} min ($(format_duration "$video_duration")) — audio loop enabled"
    else
        echo "  Target   : ${TARGET_VIDEO_DURATION_MIN} min ignored (master ≥ target; master 尺が支配)"
    fi
fi

# 音声ループ時は再エンコード必須 + loudnorm で音割れ防止 (#1057)
# loudnorm は AUDIO_OUT_OPTS ではなく別変数に保持する。
# overlay 経路では filter_complex に統合し、非 overlay 経路では -af で適用する。
# (-af と filter_complex は同一ストリームに併用不可)
if [[ "$AUDIO_LOOP_ACTIVE" -eq 1 ]]; then
    AUDIO_OUT_OPTS=(-c:a "$AUDIO_ENCODER" -b:a 384k -ar 48000)
    AUDIO_LOUDNORM="loudnorm=I=-14:TP=-1:LRA=11"
    echo "  Audio    : re-encode + loudnorm (loop boundary clipping prevention)"
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
if [[ -n "$LOOP_VIDEO" || "$EFFECT" != "none" ]]; then
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

    # 入力配列: [0]=背景 (loop or textless main image), [1]=master audio, [2]=popup PNG (任意)
    INPUTS=()
    if [[ -n "$LOOP_VIDEO" ]]; then
        INPUTS+=(-stream_loop -1 -i "$LOOP_VIDEO")
    else
        INPUTS+=(-framerate "$enc_framerate" -loop 1 -i "$VIDEO_BACKGROUND")
    fi
    INPUTS+=("${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO")

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

    # loudnorm を filter_complex に統合 (overlay 経路では -af 併用不可)
    if [[ -n "$AUDIO_LOUDNORM" ]]; then
        FILTER+="[${AUDIO_LABEL}]${AUDIO_LOUDNORM}[a_norm];"
        AUDIO_LABEL="a_norm"
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
        -t "$video_duration" \
        -movflags +faststart \
        -shortest \
        -loglevel error \
        -progress "$PROGRESS_FILE" \
        "$MASTER_OUTPUT" &
else
    # ── 非 overlay 経路（v14: effect をループ・ベイク化） ─────────────
    # 最終形を「シームレスな短尺ループクリップを -stream_loop -1 -c:v copy で連結」に寄せる。
    #   - loop.mp4 あり        → 1 度だけ正規化して LOOP_SOURCE を得る
    #   - effect != none かつ可 → 1 周期だけ fx_baked.mp4 に焼き、それを stream copy
    #   - どちらでもない        → 静止画 1fps（従来 mode A）
    # effect ベイク不能（短尺/過大尺）は従来の全尺再エンコードへフォールバックする。

    # 1) loop.mp4 正規化（あれば LOOP_SOURCE を確定。無ければ空のまま）
    LOOP_SOURCE=""
    if [[ -n "$LOOP_VIDEO" ]]; then
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
    fi

    # 2) effect ベイク（可能なら 1 周期だけ焼いて STREAM_SOURCE にする）
    #    継ぎ目シームレス条件: bake_len が effect 周期の倍数、かつ（loop 背景なら）loop 尺の倍数。
    #    → 静止画背景は bake_len=period、loop 背景は lcm(round(loop_dur), period)。
    STREAM_SOURCE=""
    if [[ "$EFFECT" != "none" ]]; then
        period="$(effect_period)"
        if [[ -n "$LOOP_SOURCE" ]]; then
            loop_dur_raw="$(get_duration "$LOOP_SOURCE")"
            loop_dur_int="$(awk "BEGIN{printf \"%d\", (${loop_dur_raw:-0})+0.5}")"
            [[ "${loop_dur_int:-0}" -lt 1 ]] && loop_dur_int=1
            bake_len="$(_lcm "$loop_dur_int" "$period")"
            bake_filter="$EFFECT_FILTER_LOOP"
            bake_input=(-stream_loop -1 -i "$LOOP_SOURCE")
            bake_crf=22
            bake_src_file="$LOOP_SOURCE"
        else
            bake_len="$period"
            bake_filter="$EFFECT_FILTER_STATIC"
            bake_input=(-framerate "$STILL_EFFECT_FPS" -loop 1 -i "$VIDEO_BACKGROUND")
            bake_crf="$STILL_EFFECT_CRF"
            bake_src_file="$VIDEO_BACKGROUND"
        fi
        if [[ "${bake_len:-0}" -le 0 ]] || awk "BEGIN{exit !(${bake_len:-0} >= ${video_duration:-0})}" || [[ "${bake_len:-0}" -gt "$BAKE_MAX_LEN" ]]; then
            echo "  Effect bake skip (bake_len=${bake_len}s, video=${video_duration%.*}s) — 全尺再エンコードにフォールバック"
        else
            FX_BAKED="${ASSETS_DIR}/fx_baked.mp4"
            FX_STAMP="${ASSETS_DIR}/fx_baked.params"
            want_stamp="${EFFECT}|${EFFECT_INTENSITY}|${bake_len}|$(stat_mtime "$bake_src_file")|${LOOP_MAX_BITRATE}"
            have_stamp=""
            [[ -f "$FX_STAMP" ]] && have_stamp="$(cat "$FX_STAMP" 2>/dev/null)"
            if [[ -f "$FX_BAKED" && "$have_stamp" == "$want_stamp" ]]; then
                echo "  [Step 1/${FF_TOTAL_STEPS}] Effect loop cache hit (${bake_len}s, ${EFFECT}) → fx_baked.mp4 再利用"
            else
                echo "  [Step 1/${FF_TOTAL_STEPS}] Baking ${EFFECT} effect loop (${bake_len}s, 1 回だけ) → fx_baked.mp4"
                ffmpeg -y "${bake_input[@]}" \
                    -filter_complex "$bake_filter" \
                    -map "[vout]" \
                    -c:v libx264 -preset medium -crf "$bake_crf" -maxrate "$LOOP_MAX_BITRATE" -bufsize "$LOOP_BUFSIZE" -pix_fmt yuv420p \
                    -r "$LOOP_OUTPUT_FRAME_RATE" \
                    -t "$bake_len" \
                    -an -movflags +faststart \
                    -loglevel error \
                    "$FX_BAKED"
                if [[ $? -ne 0 || ! -f "$FX_BAKED" ]]; then
                    echo "  ERROR: fx_baked.mp4 の生成に失敗"
                    exit 1
                fi
                printf '%s' "$want_stamp" > "$FX_STAMP"
            fi
            STREAM_SOURCE="$FX_BAKED"
        fi
    elif [[ -n "$LOOP_SOURCE" ]]; then
        STREAM_SOURCE="$LOOP_SOURCE"
    fi

    # 3) 最終マスター動画生成
    if [[ -n "$STREAM_SOURCE" ]]; then
        # Stream copy 経路（effect ベイク / loop 背景 共通）: ビデオは完全無損失（ビット単位コピー）。
        # AUDIO_INPUT_OPTS は target_video_duration_min 設定時のみ -stream_loop -1 を持つ (#545)
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (stream copy)"
        AUDIO_AF_ARGS=()
        [[ -n "$AUDIO_LOUDNORM" ]] && AUDIO_AF_ARGS=(-af "$AUDIO_LOUDNORM")
        ffmpeg -y -stream_loop -1 -i "$STREAM_SOURCE" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -map 0:v:0 -map 1:a:0 \
            -c:v copy \
            "${AUDIO_OUT_OPTS[@]}" "${AUDIO_AF_ARGS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    elif [[ "$EFFECT" != "none" && -n "$LOOP_SOURCE" ]]; then
        # フォールバック: loop + effect を全尺再エンコード（従来 mode C）
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (loop + ${EFFECT} effect, full encode fallback)"
        AUDIO_AF_ARGS=()
        [[ -n "$AUDIO_LOUDNORM" ]] && AUDIO_AF_ARGS=(-af "$AUDIO_LOUDNORM")
        ffmpeg -y -stream_loop -1 -i "$LOOP_SOURCE" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -filter_complex "$EFFECT_FILTER_LOOP" \
            -map "[vout]" -map 1:a:0 \
            -c:v libx264 -preset medium -crf 22 -maxrate "$LOOP_MAX_BITRATE" -bufsize "$LOOP_BUFSIZE" -pix_fmt yuv420p \
            -r "$LOOP_OUTPUT_FRAME_RATE" \
            "${AUDIO_OUT_OPTS[@]}" "${AUDIO_AF_ARGS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    elif [[ "$EFFECT" != "none" ]]; then
        # フォールバック: 静止画 + effect を全尺再エンコード（従来 mode D）
        echo "  ℹ️  ループ動画なし → 静止画 + ${EFFECT} effect で出力 (loop.mp4 を配置すればループ動画になります)"
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (still image + ${EFFECT} effect, full encode fallback)"
        AUDIO_AF_ARGS=()
        [[ -n "$AUDIO_LOUDNORM" ]] && AUDIO_AF_ARGS=(-af "$AUDIO_LOUDNORM")
        ffmpeg -y -framerate "$STILL_EFFECT_FPS" -loop 1 -i "$VIDEO_BACKGROUND" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -filter_complex "$EFFECT_FILTER_STATIC" \
            -map "[vout]" -map 1:a:0 \
            -c:v libx264 -preset medium -crf "$STILL_EFFECT_CRF" -pix_fmt yuv420p \
            -r "$STILL_EFFECT_FPS" \
            "${AUDIO_OUT_OPTS[@]}" "${AUDIO_AF_ARGS[@]}" \
            -t "$video_duration" \
            -movflags +faststart \
            -shortest \
            -loglevel error \
            -progress "$PROGRESS_FILE" \
            "$MASTER_OUTPUT" &
    else
        # 静止画背景モード（従来 mode A）。エンコード値は config 駆動（fallback=現行値）。
        # I-frame を STILL_GOP フレーム間隔に間引き、変化のないフレームを P-frame で圧縮して小型化（#579）。
        echo "  [Step ${FF_TOTAL_STEPS}/${FF_TOTAL_STEPS}] Generating master video (still image)"
        AUDIO_AF_ARGS=()
        [[ -n "$AUDIO_LOUDNORM" ]] && AUDIO_AF_ARGS=(-af "$AUDIO_LOUDNORM")
        echo "  ℹ️  ループ動画なし → 静止画背景で出力 (loop.mp4 を配置すればループ動画になります)"
        ffmpeg -y -framerate "$STILL_FPS" -loop 1 -i "$VIDEO_BACKGROUND" \
            "${AUDIO_INPUT_OPTS[@]}" -i "$MASTER_AUDIO" \
            -c:v libx264 -tune stillimage -preset medium -crf "$STILL_CRF" -pix_fmt yuv420p \
            -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
            -g "$STILL_GOP" \
            -r "$STILL_FPS" \
            "${AUDIO_OUT_OPTS[@]}" "${AUDIO_AF_ARGS[@]}" \
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

# ─── 生成後の容量最適化パス (opt-in, config 駆動) ──────────
# shrink.enabled = true かつ maxrate or crf 指定時のみ、出力を 2 パス目で再エンコードして置換する。
# 注意: 全尺を再エンコードするため stream copy の速度メリットは相殺される（長尺で数分〜十数分）。
#       本来は loop_maxrate を下げて上流で容量制御するのが推奨。これは容量最小化したい最終版向け。
SHRINK_ENABLED="$(yaml_get shrink enabled false)"
SHRINK_MAXRATE="$(yaml_get shrink maxrate "")"
SHRINK_CRF="$(yaml_get shrink crf "")"
if [[ "$SHRINK_ENABLED" == "true" && ( -n "$SHRINK_MAXRATE" || -n "$SHRINK_CRF" ) ]]; then
    echo ""
    echo "  [shrink] 生成後の容量最適化パスを実行します（全尺を再エンコード: 長尺は数分〜十数分）"
    echo "           ※ stream copy の速度メリットは相殺されます。容量最小化したい最終版向け。"
    shrink_tmp="${MASTER_OUTPUT%.mp4}.shrink.mp4"
    if [[ -n "$SHRINK_CRF" ]]; then
        shrink_venc=(-c:v libx264 -preset medium -crf "$SHRINK_CRF" -pix_fmt yuv420p)
        echo "           target: crf=${SHRINK_CRF}"
    else
        shrink_maxrate_bps="$(bitrate_to_bps "$SHRINK_MAXRATE")"
        shrink_buf="$(awk "BEGIN{printf \"%dk\", (${shrink_maxrate_bps:-0}/1000)*2}")"
        shrink_venc=(-c:v libx264 -preset medium -b:v 0 -maxrate "$SHRINK_MAXRATE" -bufsize "$shrink_buf" -pix_fmt yuv420p)
        echo "           target: maxrate=${SHRINK_MAXRATE} (bufsize=${shrink_buf})"
    fi
    before_size="$(ls -lh "$MASTER_OUTPUT" | awk '{print $5}')"
    if ffmpeg -y -i "$MASTER_OUTPUT" "${shrink_venc[@]}" -c:a copy -movflags +faststart -loglevel error "$shrink_tmp" && [[ -f "$shrink_tmp" ]]; then
        mv "$shrink_tmp" "$MASTER_OUTPUT"
        after_size="$(ls -lh "$MASTER_OUTPUT" | awk '{print $5}')"
        echo "  [shrink] 完了: ${before_size} → ${after_size}"
    else
        echo "  [shrink] WARN: 再エンコードに失敗。元ファイルを保持します"
        rm -f "$shrink_tmp"
    fi
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
