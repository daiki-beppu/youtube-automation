#!/usr/bin/env python3
"""Generate the channel-wide intro.mp4 (one-time, brand-level asset).

Design D / v7.1 photoreal video-only: intro.mp4 は **音声を一切含まない
video-only mp4** として出力する。背景は 4 Veo loop の 5 segments concat
(0/5/10/15/25/30s) で、サムネ参照画像と整合する photoreal キャラ + 雨の
曇りガラス。drawtext / 雫 PNG overlay / drawbox の text / font / color は
`config.default.yaml` で channel が上書き可能。設計 D の本質的タイムライン
(30s, 5 segments, 1920×1080, 24fps) は module 定数として固定する。

Audio (SFX cup/vinyl/paper および rain ambience) は **intro.mp4 には焼き込まない**。
すべて `/masterup` の `finalize_master.py` が `branding/intro_sfx/*.wav` および
`branding/rain_layers/*.wav` から直接読んで最終 master.mp3 に統合する。
intro.mp4 は video のみのブランド素材なので、`/videoup` の concat 段階でも
audio map を持たず、master.mp3 が単一の audio source となる。

Usage:
    python generate_intro.py
    python generate_intro.py --force            # overwrite existing intro.mp4
    python generate_intro.py --repo-root <path> # 明示指定 (auto-detect で十分)
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

# `_common` は隣接モジュール (`.claude/skills/intro/references/_common.py`) で、
# `yt-skills sync` 後の配布形態でもテストの `load_skill_script` 経由でも同様に
# 解決できるよう、自スクリプトの親ディレクトリを sys.path に登録してから import する。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import resolve_repo_root  # noqa: E402

from youtube_automation.utils.exceptions import ConfigError  # noqa: E402
from youtube_automation.utils.skill_config import load_skill_config  # noqa: E402

# 設計 D の本質的定数 (config 化しない)
DURATION = 30
W, H = 1920, 1080
FPS = 24

# 各 segment の Veo loop ファイル名 (segment.name → 実体ファイル名)。
# 04_cinemagraph は a/b の 2 セグで同じ Veo 出力を 2 度 input する。
_SEGMENT_VIDEO_FILES = {
    "01_rain_cu": "01_rain_cu_loop.mp4",
    "02_lamp_steam": "02_lamp_steam_loop.mp4",
    "04_cinemagraph_a": "04_cinemagraph_loop.mp4",
    "03_room_ws": "03_room_ws_loop.mp4",
    "04_cinemagraph_b": "04_cinemagraph_loop.mp4",
}

_DROPLET_FILE = "05_droplet.png"


def _hex_to_ffmpeg_color(hex_str: str) -> str:
    """`#RRGGBB` → `0xRRGGBB` (大文字で正規化)。ffmpeg drawtext fontcolor 形式。"""
    s = hex_str.strip().lstrip("#").upper()
    if len(s) != 6:
        raise ConfigError(f"color は #RRGGBB 形式である必要があります: {hex_str!r}")
    return f"0x{s}"


def _write_textfile(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


_TEXT_REQUIRED_KEYS: tuple[str, ...] = (
    "fontsize_en",
    "fontsize_ja",
    "fontsize_logo",
    "fontsize_tagline",
    "fade_seconds",
    "shadow_color",
    "shadow_x",
    "shadow_y",
)


def _validate_text_config(text: dict) -> None:
    missing = [k for k in _TEXT_REQUIRED_KEYS if k not in text]
    if missing:
        raise ConfigError(
            f"intro/config の text に必須キーが欠落: {missing} "
            "(intro/config.default.yaml の text: namespace を確認してください)"
        )


def build_filter_complex(
    *,
    segments: list[dict],
    text: dict,
    font: dict,
    color: dict,
    logo: dict,
    tmp: Path,
) -> tuple[str, str]:
    """Build the giant filter_complex graph for intro.mp4.

    Args:
        segments: list of segment dicts with `name`/`start`/`end`/`text_en`/`text_ja`
        text: drawtext 共通スタイル dict (fontsize_en/ja/logo/tagline,
              fade_seconds, shadow_color/x/y)。channel が config/skills/intro.yaml
              で上書きすると ffmpeg cmd に伝搬する。
        font: dict with `en` / `ja` font paths
        color: dict with `drawtext` / `droplet` hex strings
        logo: dict with `heading_left` / `heading_right` / `tagline`
        tmp: 一時ディレクトリ (drawtext textfile= の永続化先)

    Returns:
        (filter_complex 文字列, 最終 video label 名)

    Raises:
        ConfigError: segments が空 (concat=n=0 を防ぐ) / text の必須キー欠落
    """
    if not segments:
        raise ConfigError("intro segments が空です。少なくとも 1 segment が必要")
    _validate_text_config(text)

    font_en = font["en"]
    font_ja = font["ja"]
    drawtext_color = _hex_to_ffmpeg_color(color["drawtext"])

    fontsize_en = text["fontsize_en"]
    fontsize_ja = text["fontsize_ja"]
    fontsize_logo = text["fontsize_logo"]
    fontsize_tagline = text["fontsize_tagline"]
    fade_s = text["fade_seconds"]
    shadow_color = text["shadow_color"]
    shadow_x = text["shadow_x"]
    shadow_y = text["shadow_y"]
    shadow_suffix = (
        f"shadowcolor={shadow_color}:shadowx={shadow_x}:shadowy={shadow_y}"
    )

    parts: list[str] = []
    tmp.mkdir(parents=True, exist_ok=True)

    # ── Video segments: trim each Veo loop to its time slot, scale, fps ──
    for idx, seg in enumerate(segments):
        seg_dur = int(seg["end"]) - int(seg["start"])
        parts.append(
            f"[{idx}:v]trim=duration={seg_dur},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},format=yuv420p,fps={FPS}[v{idx}]"
        )

    # Concat all segments
    n = len(segments)
    concat_inputs = "".join(f"[v{i}]" for i in range(n))
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vconcat]")

    # ── Drawtext for text-bearing segments (EN main + JA sub) ──
    # alpha {fade_s}s in/out fade (config 駆動)。segment 境界の両端でフェード。
    alpha_template = (
        f"if(lt(t-{{start}},{fade_s}),(t-{{start}})/{fade_s},"
        f"if(lt(t-{{start}},{{seg_dur_minus_fade}}),1,max(0,({{end}}-t)/{fade_s})))"
    )
    drawtext_chain = "vconcat"
    text_idx = 0
    for idx, seg in enumerate(segments):
        en = seg.get("text_en", "")
        ja = seg.get("text_ja", "")
        if not en:
            continue
        start, end = int(seg["start"]), int(seg["end"])
        seg_dur = end - start
        a = alpha_template.format(start=start, seg_dur_minus_fade=seg_dur - fade_s, end=end)
        # 0-5s segment: center に置く (mug 中心被り回避のため -50px)
        # それ以外 (5-10s 等): upper-third
        y_en = "(h-text_h)/2-50" if start == 0 else "h/3-text_h/2"
        y_ja = "(h-text_h)/2+50" if start == 0 else "h/3+text_h+10"

        en_file = tmp / f"text_en_{idx}.txt"
        _write_textfile(en_file, en)
        next_label = f"d{text_idx}"
        parts.append(
            f"[{drawtext_chain}]drawtext=fontfile='{font_en}':"
            f"textfile='{en_file}':"
            f"fontsize={fontsize_en}:fontcolor={drawtext_color}@1:"
            f"x=(w-text_w)/2:y={y_en}:"
            f"alpha='{a}':enable='between(t,{start},{end})':"
            f"{shadow_suffix}[{next_label}]"
        )
        drawtext_chain = next_label
        text_idx += 1

        ja_file = tmp / f"text_ja_{idx}.txt"
        _write_textfile(ja_file, ja)
        next_label = f"d{text_idx}"
        parts.append(
            f"[{drawtext_chain}]drawtext=fontfile='{font_ja}':"
            f"textfile='{ja_file}':"
            f"fontsize={fontsize_ja}:fontcolor={drawtext_color}@0.85:"
            f"x=(w-text_w)/2:y={y_ja}:"
            f"alpha='{a}':enable='between(t,{start},{end})':"
            f"{shadow_suffix}[{next_label}]"
        )
        drawtext_chain = next_label
        text_idx += 1

    # ── Logo drawtext 15-25s (heading 左右 + 雫 PNG overlay + rule + tagline) ──
    logo_alpha = (
        "if(lt(t-15,0.8),(t-15)/0.8,"
        "if(lt(t-15,9.2),1,max(0,(25-t)/0.8)))"
    )

    # 左 heading: 中央から左 50px gap
    heading_left = logo["heading_left"]
    heading_right = logo["heading_right"]
    tagline = logo["tagline"]

    rain_file = tmp / "text_logo_left.txt"
    _write_textfile(rain_file, heading_left)
    next_label = f"d{text_idx}"
    parts.append(
        f"[{drawtext_chain}]drawtext=fontfile='{font_en}':"
        f"textfile='{rain_file}':"
        f"fontsize={fontsize_logo}:fontcolor={drawtext_color}@1:"
        f"x=w/2-50-text_w:y=(h-text_h)/2-80:"
        f"alpha='{logo_alpha}':enable='between(t,15,25)':"
        f"{shadow_suffix}[{next_label}]"
    )
    drawtext_chain = next_label
    text_idx += 1

    # 右 heading: 中央から右 50px gap
    jazz_file = tmp / "text_logo_right.txt"
    _write_textfile(jazz_file, heading_right)
    next_label = f"d{text_idx}"
    parts.append(
        f"[{drawtext_chain}]drawtext=fontfile='{font_en}':"
        f"textfile='{jazz_file}':"
        f"fontsize={fontsize_logo}:fontcolor={drawtext_color}@1:"
        f"x=w/2+50:y=(h-text_h)/2-80:"
        f"alpha='{logo_alpha}':enable='between(t,15,25)':"
        f"{shadow_suffix}[{next_label}]"
    )
    drawtext_chain = next_label
    text_idx += 1

    # 雫 PNG overlay (heading 左右の中央)。input index = len(segments)
    droplet_idx = n
    parts.append(
        f"[{droplet_idx}:v]scale=60:60,format=rgba,"
        f"fade=t=in:st=15:d=0.8:alpha=1,"
        f"fade=t=out:st=24.2:d=0.8:alpha=1[droplet_keyed]"
    )
    next_label = f"d{text_idx}"
    parts.append(
        f"[{drawtext_chain}][droplet_keyed]overlay=x=(W-60)/2:y=H/2-110:"
        f"enable='between(t,15,25)'[{next_label}]"
    )
    drawtext_chain = next_label
    text_idx += 1

    # Rule line (heading と tagline の間の罫線)
    next_label = f"d{text_idx}"
    parts.append(
        f"[{drawtext_chain}]drawbox=x=(w-600)/2:y=(h/2)-12:w=600:h=1:"
        f"color={drawtext_color}@0.5:t=fill:"
        f"enable='between(t,15.8,24.2)'[{next_label}]"
    )
    drawtext_chain = next_label
    text_idx += 1

    # Tagline (heading の下 / rule の下に置く 32pt italic 風)
    tagline_file = tmp / "text_logo_tagline.txt"
    _write_textfile(tagline_file, tagline)
    next_label = f"d{text_idx}"
    parts.append(
        f"[{drawtext_chain}]drawtext=fontfile='{font_en}':"
        f"textfile='{tagline_file}':"
        f"fontsize={fontsize_tagline}:fontcolor={drawtext_color}@0.85:"
        f"x=(w-text_w)/2:y=(h/2)+8:"
        f"alpha='{logo_alpha}':enable='between(t,15,25)':"
        f"{shadow_suffix}[{next_label}]"
    )
    drawtext_chain = next_label
    text_idx += 1

    return ";".join(parts), drawtext_chain


def _resolve_segment_video(intro_dir: Path, name: str) -> Path:
    """segment 名から実体 mp4 ファイルパスを解決する。"""
    if name not in _SEGMENT_VIDEO_FILES:
        raise ConfigError(f"unknown segment name: {name!r} (expected one of {list(_SEGMENT_VIDEO_FILES)})")
    return intro_dir / _SEGMENT_VIDEO_FILES[name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="リポジトリルート (default: 起動位置から auto-detect)")
    parser.add_argument("--force", action="store_true",
                        help="既存の branding/intro.mp4 を上書きする")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parent
    repo_root = (args.repo_root.resolve() if args.repo_root
                 else resolve_repo_root(skill_dir))
    intro_dir = repo_root / "branding" / "intro_assets"
    output_path = repo_root / "branding" / "intro.mp4"

    if output_path.exists() and not args.force:
        print(f"intro.mp4 exists at {output_path}. Use --force to overwrite.")
        return 0

    cfg = load_skill_config("intro", use_cache=False)
    segments = cfg["segments"]
    text = cfg["text"]
    font = cfg["font"]
    color = cfg["color"]
    logo = cfg["logo"]

    # 必要 input ファイル (segments 順 + 雫 PNG)
    required: list[Path] = []
    for seg in segments:
        required.append(_resolve_segment_video(intro_dir, seg["name"]))
    required.append(intro_dir / _DROPLET_FILE)
    missing = [p for p in required if not p.exists()]
    if missing:
        print("ERROR: missing inputs:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return 1

    tmp = skill_dir / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        filter_complex, vfinal = build_filter_complex(
            segments=segments, text=text, font=font, color=color, logo=logo, tmp=tmp,
        )

        # ffmpeg cmd 組み立て: 5 video inputs (in segments order) + 雫 PNG。
        # 音声は出力に含めない (-an)。設計 D の音声合流は /masterup 側。
        cmd: list[str] = ["ffmpeg", "-y"]
        for seg in segments:
            cmd += [
                "-stream_loop", "-1",
                "-i", str(_resolve_segment_video(intro_dir, seg["name"])),
            ]
        cmd += [
            "-loop", "1", "-i", str(intro_dir / _DROPLET_FILE),
            "-filter_complex", filter_complex,
            "-map", f"[{vfinal}]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-an",
            "-t", str(DURATION),
            "-movflags", "+faststart",
            str(output_path),
        ]

        print("$ " + " ".join(shlex.quote(c) for c in cmd))
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"ERROR: ffmpeg failed (exit {result.returncode})", file=sys.stderr)
            return result.returncode

        print(f"\nSuccess: {output_path}")
        return 0
    finally:
        for f in tmp.glob("*.txt"):
            f.unlink()


if __name__ == "__main__":
    sys.exit(main())
