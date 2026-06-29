"""`generate_videos.sh` の loop 正規化分岐を固定するテスト."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / ".claude" / "skills" / "videoup" / "references" / "generate_videos.sh"
_VIDEOUP_SKILL_PATH = _REPO_ROOT / ".claude" / "skills" / "videoup" / "SKILL.md"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _create_collection(
    tmp_path: Path,
    *,
    master_filename: str = "master-mix.wav",
) -> Path:
    collection = tmp_path / "001-test-ambient-collection"
    master_dir = collection / "01-master"
    assets_dir = collection / "10-assets"
    master_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    (master_dir / master_filename).write_bytes(b"fake-audio")
    (assets_dir / "main.jpg").write_bytes(b"fake-image")
    (assets_dir / "loop.mp4").write_bytes(b"fake-video")
    return collection


def _create_stub_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # macOS の afinfo を スタブ化。FFPROBE_DURATION が設定されていれば
    # `estimated duration: <sec> sec` 形式で返し、未設定なら exit 1。
    _write_executable(
        bin_dir / "afinfo",
        """#!/bin/bash
if [[ -n "${FFPROBE_DURATION:-}" ]]; then
    printf 'File:           %s\\nestimated duration: %s sec\\n' "$1" "${FFPROBE_DURATION}"
    exit 0
fi
exit 1
""",
    )
    _write_executable(
        bin_dir / "ffprobe",
        """#!/bin/bash
set -eu
args="$*"
if [[ "$args" == *"format=duration"* ]]; then
    printf '%s\\n' "${FFPROBE_DURATION:-1.00}"
    exit 0
fi
if [[ "$args" == *"stream=width,height,pix_fmt,r_frame_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_STREAM_OUTPUT}"
    exit 0
fi
if [[ "$args" == *"stream=bit_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_STREAM_BITRATE_OUTPUT:-}"
    exit 0
fi
if [[ "$args" == *"format=bit_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_FORMAT_BITRATE_OUTPUT:-}"
    exit 0
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "ffmpeg",
        """#!/bin/bash
set -eu
if [[ "$*" == *"-encoders"* ]]; then
    printf ' A..... aac \\n'
    exit 0
fi

if [[ -n "${FFMPEG_LOG:-}" ]]; then
    printf '%s\\n' "$*" >> "${FFMPEG_LOG}"
fi

progress_path=""
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-progress" ]]; then
        progress_path="$arg"
    fi
    prev="$arg"
done

if [[ -n "$progress_path" ]]; then
    printf 'out_time_us=1000000\\n' > "$progress_path"
fi

output_path="${!#}"
mkdir -p "$(dirname "$output_path")"
printf 'stub-output' > "$output_path"
""",
    )
    _write_executable(
        bin_dir / "jq",
        """#!/bin/bash
set -eu
expr=""
file=""
for arg in "$@"; do
    if [[ "$arg" != "-r" ]]; then
        expr="$arg"
        break
    fi
done
for arg in "$@"; do
    file="$arg"
done

case "$expr" in
    *".overlays.enabled // false"*)
        if [[ -f "$file" ]] && grep -Eq '"enabled"[[:space:]]*:[[:space:]]*true' "$file"; then
            printf 'true\\n'
        else
            printf 'false\\n'
        fi
        ;;
    *".overlays.audio_visualizer.enabled"*) printf 'false\\n' ;;
    *".overlays.subscribe_popup.enabled"*) printf 'false\\n' ;;
    *) printf '\\n' ;;
esac
""",
    )
    return bin_dir


def _run_generate_videos(
    tmp_path: Path,
    stream_output: str,
    *,
    stream_bitrate_output: str = "",
    extra_env: dict[str, str] | None = None,
    collection: Path | None = None,
    master_filename: str = "master-mix.wav",
    with_loop: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    if collection is None:
        collection = _create_collection(tmp_path, master_filename=master_filename)
    if not with_loop:
        (collection / "10-assets" / "loop.mp4").unlink()
    bin_dir = _create_stub_bin(tmp_path)
    ffmpeg_log = tmp_path / "ffmpeg.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FFPROBE_STREAM_OUTPUT"] = stream_output
    env["FFPROBE_STREAM_BITRATE_OUTPUT"] = stream_bitrate_output
    env["FFMPEG_LOG"] = str(ffmpeg_log)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(collection)],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
    )
    return result, ffmpeg_log


@pytest.mark.parametrize("thumbnail_name", ["thumbnail.jpg", "thumbnail.png"])
def test_static_background_rejects_thumbnail_only_assets(tmp_path: Path, thumbnail_name: str) -> None:
    """#1310: thumbnail.* は upload 用なので静止動画背景には使わない。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    (assets_dir / "main.jpg").unlink()
    (assets_dir / thumbnail_name).write_bytes(b"text-included-thumbnail")

    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        collection=collection,
        with_loop=False,
    )

    assert result.returncode != 0
    assert "No video background found" in result.stdout + result.stderr
    assert "thumbnail.jpg/png is upload-only" in result.stdout + result.stderr


def test_loop_video_background_does_not_require_main_image(tmp_path: Path) -> None:
    """#1310: loop.mp4 があれば main.* 不在でも動画背景として使える。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    (assets_dir / "main.jpg").unlink()
    (assets_dir / "thumbnail.jpg").write_bytes(b"text-included-thumbnail")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "Video BG : loop.mp4 (loop)" in result.stdout
    assert "Thumbnail:" not in result.stdout
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    assert "10-assets/loop.mp4" in master_cmd
    assert "10-assets/thumbnail.jpg" not in master_cmd


def test_static_background_prefers_textless_main_png(tmp_path: Path) -> None:
    """#1310: 静止背景は textless main.png を main.jpg より優先する。"""
    collection = _create_collection(tmp_path)
    (collection / "10-assets" / "main.png").write_bytes(b"fake-png-background")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Video BG : main.png (still)" in result.stdout
    assert "Thumbnail:" not in result.stdout
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    assert "10-assets/main.png" in master_cmd
    assert "10-assets/main.jpg" not in master_cmd


def test_overlay_static_background_uses_textless_main_png(tmp_path: Path) -> None:
    """#1310: overlay 経路でも thumbnail.* ではなく textless main.png を背景入力にする。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    (assets_dir / "loop.mp4").unlink()
    (assets_dir / "main.png").write_bytes(b"fake-png-background")
    (assets_dir / "thumbnail.jpg").write_bytes(b"text-included-thumbnail")
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
        extra_env={"OVERLAYS_CONFIG": str(overlays_config)},
    )

    assert result.returncode == 0, result.stderr
    assert "Overlays : enabled" in result.stdout
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    assert "10-assets/main.png" in master_cmd
    assert "10-assets/thumbnail.jpg" not in master_cmd


def test_videoup_skill_documents_current_overlay_support() -> None:
    """#1310: videoup 文書は overlay 未実装時代の説明を残さない。"""
    skill = _VIDEOUP_SKILL_PATH.read_text(encoding="utf-8")

    assert "`generate_videos.sh` は `config/channel/youtube.json::overlays.enabled: true`" in skill
    assert "filter_complex" in skill
    assert "Suno 側ではなく `/videoup` の overlays 設定で反映する" in skill
    assert "未実装" not in skill
    assert "v12.x にはこの filter 経路が無い" not in skill
    assert "#511 の実装を待つ" not in skill


def test_24fps_loop_skips_normalization(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "loop_normalized.mp4" not in commands[0]
    assert "10-assets/loop.mp4" in commands[0]


def test_high_bitrate_24fps_loop_runs_normalization(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="15650000",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "loop_normalized.mp4" in commands[0]
    assert " -crf 22 " in f" {commands[0]} "
    assert " -maxrate 6000k " in f" {commands[0]} "
    assert " -bufsize 12000k " in f" {commands[0]} "
    assert "10-assets/loop_normalized.mp4" in commands[1]


def test_non_24fps_loop_runs_normalization_with_fixed_24fps(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(tmp_path, "1920,1080,yuv420p,30/1")

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "loop_normalized.mp4" in commands[0]
    assert " -r 24 " in f" {commands[0]} "
    assert "10-assets/loop_normalized.mp4" in commands[1]


# ─── target_video_duration_min opt-in (#545) ──────────────


def _master_ffmpeg_command(ffmpeg_log: Path) -> str:
    """正規化コマンドを除いた master 動画生成コマンドを返す."""
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    for cmd in commands:
        if "Master.mp4" in cmd:
            return cmd
    raise AssertionError(f"master ffmpeg command not found: {commands}")


def test_target_video_duration_unset_keeps_legacy_behavior(tmp_path: Path) -> None:
    """env / channel override が無ければ従来動作 (音声側 -stream_loop 無し)."""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
    )

    assert result.returncode == 0, result.stderr
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    # 動画側 1 つだけが -stream_loop -1 を持つ (音声側には付かない)
    assert master_cmd.count("-stream_loop -1") == 1
    # opt-in 通知は出ない
    assert "audio loop enabled" not in result.stdout
    assert "Target" not in result.stdout


def test_target_video_duration_env_enables_audio_loop(tmp_path: Path) -> None:
    """env で target_video_duration_min を指定すると音声側にも -stream_loop -1 が付き -t が target 秒になる."""
    # master_duration = 1.00 sec (stub), target = 120 min = 7200 sec → 7200 > 1.00 なので audio loop 有効化
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN": "120"},
    )

    assert result.returncode == 0, result.stderr
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    # 音声側にも -stream_loop -1 が付くので 2 個になる
    assert master_cmd.count("-stream_loop -1") == 2
    # -t は target 秒 (120 * 60 = 7200)
    assert " -t 7200.00 " in f" {master_cmd} "
    # 標準出力に target 通知
    assert "audio loop enabled" in result.stdout


def test_target_video_duration_ignored_when_master_longer(tmp_path: Path) -> None:
    """master 尺 ≥ target のときは従来動作 (audio loop 無し・-t は master 尺)."""
    # master_duration = 9000 sec (= 150 min) を target 120 min より長く取り master が支配
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN": "120",
            "FFPROBE_DURATION": "9000",
        },
    )

    assert result.returncode == 0, result.stderr
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    # 動画側だけが -stream_loop -1 を持つ (音声側は付かない)
    assert master_cmd.count("-stream_loop -1") == 1
    # -t は master 尺 (9000)
    assert " -t 9000 " in f" {master_cmd} " or " -t 9000.00 " in f" {master_cmd} "
    # 標準出力に ignore 通知
    assert "ignored" in result.stdout


def test_target_video_duration_channel_override_enables_audio_loop(tmp_path: Path) -> None:
    """env が無くても channel-side `config/skills/videoup.yaml` の audio.target_video_duration_min を拾える."""
    # channel root 直下に config/skills/videoup.yaml を置く
    channel_root = tmp_path / "channel"
    collection = channel_root / "collections" / "planning" / "001-test-ambient-collection"
    master_dir = collection / "01-master"
    assets_dir = collection / "10-assets"
    master_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    (master_dir / "master-mix.wav").write_bytes(b"fake-audio")
    (assets_dir / "main.jpg").write_bytes(b"fake-image")
    (assets_dir / "loop.mp4").write_bytes(b"fake-video")

    skill_config_dir = channel_root / "config" / "skills"
    skill_config_dir.mkdir(parents=True)
    (skill_config_dir / "videoup.yaml").write_text(
        "audio:\n  target_video_duration_min: 90\n",
        encoding="utf-8",
    )

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    # channel override で audio loop 有効
    assert master_cmd.count("-stream_loop -1") == 2
    # -t は 90 * 60 = 5400 秒
    assert " -t 5400.00 " in f" {master_cmd} "


def test_target_video_duration_env_overrides_channel_override(tmp_path: Path) -> None:
    """env が channel override より優先される."""
    channel_root = tmp_path / "channel"
    collection = channel_root / "collections" / "planning" / "001-test-ambient-collection"
    master_dir = collection / "01-master"
    assets_dir = collection / "10-assets"
    master_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    (master_dir / "master-mix.wav").write_bytes(b"fake-audio")
    (assets_dir / "main.jpg").write_bytes(b"fake-image")
    (assets_dir / "loop.mp4").write_bytes(b"fake-video")

    skill_config_dir = channel_root / "config" / "skills"
    skill_config_dir.mkdir(parents=True)
    (skill_config_dir / "videoup.yaml").write_text(
        "audio:\n  target_video_duration_min: 90\n",
        encoding="utf-8",
    )

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN": "30"},
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    # env が優先 (30 min = 1800 秒)
    assert " -t 1800.00 " in f" {master_cmd} "


# ─── master.{wav,mp3} detection (#507) ────────────────────


def test_detects_lyria_master_wav(tmp_path: Path) -> None:
    """#507: `/lyria` (yt-generate-master) 出力の `master.wav` を検出できる."""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        master_filename="master.wav",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "01-master/master.wav" in commands[0]


def test_detects_masterup_master_mp3(tmp_path: Path) -> None:
    """#507: `/masterup` (yt-generate-master) 出力の `master.mp3` を検出できる."""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        master_filename="master.mp3",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "01-master/master.mp3" in commands[0]


def test_master_mix_takes_precedence_over_master(tmp_path: Path) -> None:
    """#507: 両方存在する場合は `master-mix.*` (DAW バウンス) を優先する."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    # `master.mp3` も追加で配置 → `master-mix.wav` が優先されることを検証
    (collection / "01-master" / "master.mp3").write_bytes(b"fake-audio-mp3")

    bin_dir = _create_stub_bin(tmp_path)
    ffmpeg_log = tmp_path / "ffmpeg.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FFPROBE_STREAM_OUTPUT"] = "1920,1080,yuv420p,24/1"
    env["FFPROBE_STREAM_BITRATE_OUTPUT"] = "5000000"
    env["FFMPEG_LOG"] = str(ffmpeg_log)
    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(collection)],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "01-master/master-mix.wav" in commands[0]
    assert "01-master/master.mp3" not in commands[0]


# ─── Video Effects (#648) ────────────────────────────────


def test_default_effect_none_uses_stream_copy_for_loop(tmp_path: Path) -> None:
    """エフェクト未指定（デフォルト=none）ではループモードは stream copy のままで挙動が温存される。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
    )
    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "-c:v copy" in final_cmd
    assert "-filter_complex" not in final_cmd


def test_particles_effect_switches_to_libx264_with_filter_complex(tmp_path: Path) -> None:
    """particles 指定でループ素材を libx264 再エンコード + filtergraph に切り替わる。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_EFFECT": "particles"},
    )
    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "-filter_complex" in final_cmd
    assert "[vout]" in final_cmd
    assert "-c:v libx264" in final_cmd
    assert "-c:v copy" not in final_cmd
    # subtle (default) は alpha=0.10
    assert "0.10*255" in final_cmd


def test_bokeh_effect_uses_gblur(tmp_path: Path) -> None:
    """bokeh エフェクトでは gblur フィルタが使われる。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_EFFECT": "bokeh", "VIDEOUP_EFFECT_INTENSITY": "medium"},
    )
    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "gblur" in final_cmd
    # medium は alpha=0.20
    assert "0.20*255" in final_cmd


def test_gradient_effect_uses_gradients_source(tmp_path: Path) -> None:
    """gradient エフェクトでは gradients ソースが filtergraph に含まれる。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_EFFECT": "gradient", "VIDEOUP_EFFECT_INTENSITY": "strong"},
    )
    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "gradients=" in final_cmd
    # strong は alpha=0.35
    assert "0.35*255" in final_cmd


def test_static_image_with_effect_uses_filter_complex(tmp_path: Path) -> None:
    """静止画モード + エフェクトでも filter_complex 経路に乗る。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        extra_env={"VIDEOUP_EFFECT": "particles"},
        with_loop=False,
    )
    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "-filter_complex" in final_cmd
    assert "[vout]" in final_cmd
    # 静止画モード固有の scale+pad 前処理が含まれる
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in final_cmd


# ─── Loop artifact warning (#868) ────────────────────────


def test_loop_absent_with_loop_raw_shows_warning(tmp_path: Path) -> None:
    """loop.mp4 が無いが loop_raw.mp4 が残っていれば警告を出力する."""
    collection = _create_collection(tmp_path)
    (collection / "10-assets" / "loop.mp4").unlink()
    (collection / "10-assets" / "loop_raw.mp4").write_bytes(b"fake-raw")

    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "生成途中の痕跡が存在します" in result.stdout
    assert "loop_raw.mp4" in result.stdout


def test_loop_absent_with_loop_version_shows_warning(tmp_path: Path) -> None:
    """loop.mp4 が無いが loop-v*.mp4 が残っていれば警告を出力する."""
    collection = _create_collection(tmp_path)
    (collection / "10-assets" / "loop.mp4").unlink()
    (collection / "10-assets" / "loop-v1.mp4").write_bytes(b"fake-v1")
    (collection / "10-assets" / "loop-v2.mp4").write_bytes(b"fake-v2")

    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "生成途中の痕跡が存在します" in result.stdout
    assert "loop-v1.mp4" in result.stdout
    assert "loop-v2.mp4" in result.stdout


def test_loop_absent_no_artifacts_no_warning(tmp_path: Path) -> None:
    """loop.mp4 も痕跡ファイルも無い場合は警告を出さない."""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    assert "生成途中の痕跡が存在します" not in result.stdout
    assert "loop_raw.mp4" not in result.stdout


def test_loop_detected_log_shows_basename(tmp_path: Path) -> None:
    """loop.mp4 検出時のログに basename のみ表示される (フルパスではない)."""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
    )

    assert result.returncode == 0, result.stderr
    assert "Loop     : loop.mp4 (detected)" in result.stdout
    assert "10-assets/loop.mp4 (detected)" not in result.stdout


def test_loop_not_found_log(tmp_path: Path) -> None:
    """loop.mp4 が存在しない場合は not found ログを出力する."""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Loop     : not found" in result.stdout


def test_static_image_effect_fallback_shows_no_loop_log(tmp_path: Path) -> None:
    """静止画 + effect fallback 時に not found ログが出力される."""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        extra_env={"VIDEOUP_EFFECT": "particles"},
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Loop     : not found" in result.stdout


def test_invalid_effect_name_fails_loud(tmp_path: Path) -> None:
    """未知のエフェクト名は fail-loud で停止する。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_EFFECT": "sparkle"},
    )
    assert result.returncode != 0
    assert "Unknown VIDEOUP_EFFECT" in result.stdout + result.stderr


def test_invalid_intensity_fails_loud(tmp_path: Path) -> None:
    """未知の intensity は fail-loud で停止する。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"VIDEOUP_EFFECT": "particles", "VIDEOUP_EFFECT_INTENSITY": "extreme"},
    )
    assert result.returncode != 0
    assert "Unknown VIDEOUP_EFFECT_INTENSITY" in result.stdout + result.stderr
