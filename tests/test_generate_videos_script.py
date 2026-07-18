"""`generate_videos.sh` の loop 正規化分岐を固定するテスト."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
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
    # macOS の afinfo をスタブ化し、入力音声の duration を返す。
    _write_executable(
        bin_dir / "afinfo",
        """#!/bin/bash
printf 'File:           %s\\nestimated duration: %s sec\\n' "$1" "${FFPROBE_DURATION:-1.00}"
""",
    )
    _write_executable(
        bin_dir / "ffprobe",
        """#!/bin/bash
set -eu
args="$*"
input_path="${!#}"
if [[ "${FFPROBE_OUTPUT_FAIL:-0}" == "1" && "$input_path" == *"-Master.mp4" ]]; then
    exit 1
fi
if [[ "$args" == *"format=duration"* ]]; then
    if [[ "$input_path" == *"-Master.mp4" && -n "${FFPROBE_OUTPUT_DURATION+x}" ]]; then
        printf '%s\\n' "$FFPROBE_OUTPUT_DURATION"
    elif [[ -f "${input_path}.duration" ]]; then
        cat "${input_path}.duration"
    else
        printf '%s\\n' "${FFPROBE_DURATION:-1.00}"
    fi
    exit 0
fi
if [[ "$args" == *"stream=r_frame_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_OUTPUT_FRAME_RATE-24/1}"
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
if [[ -n "${FFMPEG_FAIL_MATCH:-}" && "$*" == *"${FFMPEG_FAIL_MATCH}"* ]]; then
    exit 9
fi

progress_path=""
duration=""
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-progress" ]]; then
        progress_path="$arg"
    fi
    if [[ "$prev" == "-t" ]]; then
        duration="$arg"
    fi
    prev="$arg"
done

if [[ -n "$progress_path" ]]; then
    printf 'out_time_us=1000000\\n' > "$progress_path"
fi

output_path="${!#}"
mkdir -p "$(dirname "$output_path")"
printf 'stub-output' > "$output_path"
if [[ -n "$duration" ]]; then
    printf '%s\\n' "$duration" > "${output_path}.duration"
fi
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
    *".overlays.audio_visualizer.enabled"*) printf '%s\\n' "${OVERLAY_AV_ENABLED:-${JQ_AV_ENABLED:-false}}" ;;
    *".overlays.audio_visualizer.style"*) printf '%s\\n' "${OVERLAY_AV_STYLE:-}" ;;
    *".overlays.audio_visualizer.bars"*) printf '%s\\n' "${OVERLAY_AV_BARS:-}" ;;
    *".overlays.audio_visualizer.size"*) printf '%s\\n' "${OVERLAY_AV_SIZE:-}" ;;
    *".overlays.audio_visualizer.position"*) printf '%s\\n' "${OVERLAY_AV_POSITION:-}" ;;
    *".overlays.audio_visualizer.glow.enabled // .overlays.audio_visualizer.glow_enabled"*)
        printf '%s\\n' "${JQ_AV_GLOW_ENABLED:-}"
        ;;
    *".overlays.audio_visualizer.glow_enabled"*) printf '%s\\n' "${OVERLAY_AV_GLOW_ENABLED:-}" ;;
    *".overlays.audio_visualizer.ring.inner_r"*) printf '%s\\n' "${OVERLAY_AV_RING_INNER_R:-}" ;;
    *".overlays.audio_visualizer.ring.length"*) printf '%s\\n' "${OVERLAY_AV_RING_LENGTH:-}" ;;
    *".overlays.audio_visualizer.ring.arc_deg[0]"*) printf '%s\\n' "${OVERLAY_AV_ARC_START:-}" ;;
    *".overlays.audio_visualizer.ring.arc_deg[1]"*) printf '%s\\n' "${OVERLAY_AV_ARC_END:-}" ;;
    *".overlays.audio_visualizer.fill.type"*) printf '%s\\n' "${JQ_AV_FILL_TYPE:-}" ;;
    *".overlays.audio_visualizer.fill.color"*) printf '%s\\n' "${JQ_AV_FILL_COLOR:-}" ;;
    *".overlays.audio_visualizer.fill.top"*) printf '%s\\n' "${JQ_AV_FILL_TOP:-}" ;;
    *".overlays.audio_visualizer.fill.bottom"*) printf '%s\\n' "${JQ_AV_FILL_BOTTOM:-}" ;;
    *".overlays.audio_visualizer.mirror_center"*) printf '%s\\n' "${JQ_AV_MIRROR_CENTER:-}" ;;
    *".overlays.audio_visualizer.symmetric_vertical"*) printf '%s\\n' "${JQ_AV_SYMMETRIC_VERTICAL:-}" ;;
    *".overlays.audio_visualizer.rounding.blur"*) printf '%s\\n' "${JQ_AV_ROUNDING_BLUR:-}" ;;
    *".overlays.audio_visualizer.rounding.contrast"*) printf '%s\\n' "${JQ_AV_ROUNDING_CONTRAST:-}" ;;
    *".overlays.audio_visualizer.glow.enabled"*) printf '%s\\n' "${JQ_AV_GLOW_ENABLED:-}" ;;
    *".overlays.audio_visualizer.glow.sigma"*) printf '%s\\n' "${JQ_AV_GLOW_SIGMA:-}" ;;
    *".overlays.audio_visualizer.glow.opacity"*) printf '%s\\n' "${JQ_AV_GLOW_OPACITY:-}" ;;
    *".overlays.subscribe_popup.enabled"*) printf 'false\\n' ;;
    *) printf '\\n' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "yt-audio-visualizer-fill",
        """#!/bin/bash
set -eu
if [[ "${FILL_HELPER_FAIL:-0}" == "1" ]]; then
    printf 'invalid fill config\\n' >&2
    exit 2
fi
output=""
prev=""
for arg in "$@"; do
    if [[ "$prev" == "--output" ]]; then output="$arg"; fi
    prev="$arg"
done
if [[ "${FILL_EFFECTIVE_TYPE:-gradient}" != "solid" ]]; then printf 'png' > "$output"; fi
printf '%s\\n' "${FILL_EFFECTIVE_TYPE:-gradient}"
""",
    )
    return bin_dir


_SHARED_STUB_BIN: Path | None = None


@pytest.fixture(scope="session", autouse=True)
def _shared_stub_bin(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """stub 実行ファイル群を session で 1 回だけ作成して全テストで共有する。

    #2092: macOS では新規作成した実行ファイルの初回 exec に Gatekeeper 検査で
    数百 ms かかるため、テストごとに stub を作り直すと 1 テストあたり
    0.5〜0.8s のオーバーヘッドになる。stub は環境変数と引数だけで挙動が決まり
    bin ディレクトリ側に状態を持たないので、session 全体で安全に共有できる。
    """
    global _SHARED_STUB_BIN
    _SHARED_STUB_BIN = _create_stub_bin(tmp_path_factory.mktemp("shared-stub"))
    yield _SHARED_STUB_BIN
    _SHARED_STUB_BIN = None


def _shared_stub_bin_dir() -> Path:
    assert _SHARED_STUB_BIN is not None, "_shared_stub_bin session fixture must provision the stub bin"
    return _SHARED_STUB_BIN


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
        (collection / "10-assets" / "loop.mp4").unlink(missing_ok=True)
    bin_dir = _shared_stub_bin_dir()
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


def _assert_effect_alpha_plane_and_neutral_chroma(
    final_cmd: str,
    *,
    noise_filter: str,
    lum_threshold: int,
) -> None:
    final_cmd = final_cmd.replace("\t", "")
    effect_layer = f"{noise_filter},format=yuva420p,geq=lum='if(gt(lum(X,Y),{lum_threshold}),255,0)':cb=128:cr=128:a="
    assert effect_layer in final_cmd


def _assert_effect_alpha_plane_and_source_chroma(
    final_cmd: str,
    *,
    noise_filter: str,
    lum_threshold: int,
) -> None:
    final_cmd = final_cmd.replace("\t", "")
    effect_layer = (
        f"{noise_filter},format=yuva420p,geq=lum='if(gt(lum(X,Y),{lum_threshold}),255,0)':cb='cb(X,Y)':cr='cr(X,Y)':a="
    )
    assert effect_layer in final_cmd


def _run_ffmpeg_rgba_frame(filtergraph: str, *, width: int, height: int) -> bytes:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for visual filter integration tests")

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            filtergraph,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert len(result.stdout) == width * height * 4
    return result.stdout


def _filter_complex_command(ffmpeg_log: Path) -> str:
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    for command in commands:
        if "-filter_complex" in command:
            return command
    raise AssertionError(f"filter_complex command not found: {commands}")


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


def test_workflow_state_master_audio_takes_priority_over_fixed_names(tmp_path: Path) -> None:
    """#1449: raw=final の任意ファイル名を `/videoup` でも使える."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    (collection / "01-master" / "master-rain.wav").write_bytes(b"fake-raw-final-audio")
    (collection / "workflow-state.json").write_text(
        json.dumps({"assets": {"master_audio": "master-rain.wav"}}),
        encoding="utf-8",
    )

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "Audio    : master-rain.wav" in result.stdout
    master_cmd = _master_ffmpeg_command(ffmpeg_log)
    assert "01-master/master-rain.wav" in master_cmd
    assert "01-master/master-mix.wav" not in master_cmd


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ({"assets": {"master_audio": "../master-rain.wav"}}, "must be a filename"),
        ({"assets": {"master_audio": "subdir/master-rain.wav"}}, "must be a filename"),
        ({"assets": {"master_audio": "subdir\\master-rain.wav"}}, "must be a filename"),
        ({"assets": {"master_audio": "missing.wav"}}, "not found"),
        ({"assets": {"master_audio": 123}}, "assets.master_audio must be a string"),
        ({"assets": None}, "assets must be an object"),
        ({"assets": []}, "assets must be an object"),
    ],
)
def test_workflow_state_master_audio_invalid_values_fail_closed(
    tmp_path: Path,
    state: dict,
    message: str,
) -> None:
    """#1449: 壊れた explicit state では固定名探索へ fallback しない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert message in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


def test_workflow_state_master_audio_malformed_json_fails_closed(tmp_path: Path) -> None:
    """#1449: workflow-state.json が壊れている場合は別音源で進めない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    (collection / "workflow-state.json").write_text("{broken", encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "workflow-state.json is invalid JSON" in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


def test_workflow_state_master_audio_directory_fails_closed(tmp_path: Path) -> None:
    """#1449: workflow-state.json が directory の場合は固定名探索へ fallback しない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    state_path = collection / "workflow-state.json"
    state_path.mkdir()

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "workflow-state.json must be a file" in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


def test_workflow_state_master_audio_broken_symlink_fails_closed(tmp_path: Path) -> None:
    """#1449: broken symlink は未設定扱いせず固定名探索へ fallback しない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    state_path = collection / "workflow-state.json"
    try:
        state_path.symlink_to(collection / "missing-workflow-state.json")
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "workflow-state.json is a broken symlink" in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


def test_workflow_state_master_audio_unreadable_file_fails_closed(tmp_path: Path) -> None:
    """#1449: 読み取り不能な state は固定名探索へ fallback しない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps({"assets": {"master_audio": "selected.wav"}}), encoding="utf-8")
    (collection / "01-master" / "selected.wav").write_bytes(b"selected-audio")
    state_path.chmod(0)

    try:
        result, ffmpeg_log = _run_generate_videos(
            tmp_path,
            "1920,1080,yuv420p,24/1",
            stream_bitrate_output="5000000",
            collection=collection,
        )
    finally:
        state_path.chmod(0o644)

    output = result.stdout + result.stderr
    if result.returncode == 0 and "Audio    : selected.wav" in output:
        pytest.skip("current user can still read chmod 000 files")
    assert result.returncode != 0
    assert "workflow-state.json could not be read" in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


def test_workflow_state_master_audio_non_object_root_fails_closed(tmp_path: Path) -> None:
    """#1449: workflow-state.json root の shape 不正は固定名探索へ fallback しない."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    (collection / "workflow-state.json").write_text("[]", encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "workflow-state.json root must be an object" in output
    assert "Audio    : master-mix.wav" not in output
    assert not ffmpeg_log.exists()


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"assets": {}},
        {"assets": {"master_audio": None}},
        {"assets": {"master_audio": ""}},
    ],
)
def test_workflow_state_master_audio_unset_falls_back_to_fixed_names(tmp_path: Path, state: dict) -> None:
    """#1449: master_audio 未設定だけは従来の固定名探索を維持する."""
    collection = _create_collection(tmp_path, master_filename="master-mix.wav")
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")

    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "Audio    : master-mix.wav" in result.stdout


def test_loop_video_disabled_uses_textless_main_even_when_loop_exists(tmp_path: Path) -> None:
    """#1310: loop-video.enabled=false では既存 loop.mp4 を無視して textless main.* を背景にする。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    (assets_dir / "main.png").write_bytes(b"fake-png-background")
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "loop-video.yaml").write_text("enabled: false\n", encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
    )

    assert result.returncode == 0, result.stderr
    assert "Loop     : disabled by config/skills/loop-video.yaml" in result.stdout
    assert "Video BG : main.png (still)" in result.stdout
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert "10-assets/main.png" in commands[0]
    assert "10-assets/loop.mp4" not in " ".join(commands)
    assert "10-assets/still_baked.mp4" in _master_ffmpeg_command(ffmpeg_log)


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
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert "10-assets/main.png" in commands[0]
    assert "10-assets/main.jpg" not in " ".join(commands)
    assert "10-assets/still_baked.mp4" in _master_ffmpeg_command(ffmpeg_log)


def test_static_effect_none_bakes_one_gop_then_stream_copies_to_audio_duration(tmp_path: Path) -> None:
    """#1681: 静止画 + effect=none は短尺ベイク後に既存 stream-copy 経路を通る。"""
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={"FFPROBE_DURATION": "7200"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    bake_cmd, master_cmd = commands
    assert "10-assets/main.jpg" in bake_cmd
    assert "10-assets/still_baked.mp4" in bake_cmd
    assert " -t 300.000000 " in f" {bake_cmd} "
    assert " -g 300 " in f" {bake_cmd} "
    assert " -r 1 " in f" {bake_cmd} "
    assert "-stream_loop -1" in master_cmd
    assert "10-assets/still_baked.mp4" in master_cmd
    assert "-c:v copy" in master_cmd
    assert " -t 7200.00 " in f" {master_cmd} "
    assert "-shortest" in master_cmd
    assert "Baking still image loop" in result.stdout
    assert "generate_videos.sh v14.2" in result.stdout
    assert "[Step 1/2]" in result.stdout
    assert "[Step 2/2] Generating master video (stream copy)" in result.stdout


def test_static_bake_channel_config_reaches_ffmpeg_and_cache_stamp(tmp_path: Path) -> None:
    """#1681: still 設定の channel override がベイク尺・encoder・stamp まで貫通する。"""
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
        "video:\n  still_fps: 2\n  still_crf: 26\n  still_gop: 10\n",
        encoding="utf-8",
    )

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        collection=collection,
        with_loop=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    bake_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[0]
    assert " -framerate 2 " in f" {bake_cmd} "
    assert " -crf 26 " in f" {bake_cmd} "
    assert " -g 10 " in f" {bake_cmd} "
    assert " -t 5.000000 " in f" {bake_cmd} "
    assert (assets_dir / "still_baked.params").read_text(encoding="utf-8").endswith("|2|26|10")


def test_static_bake_cache_reuses_short_clip(tmp_path: Path) -> None:
    """#1681: 背景と設定が同じ再実行では短尺ベイクを再利用する。"""
    collection = _create_collection(tmp_path)
    first_result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        collection=collection,
        with_loop=False,
    )
    assert first_result.returncode == 0, first_result.stdout + first_result.stderr

    ffmpeg_log.unlink()
    second_result, second_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        collection=collection,
        with_loop=False,
    )

    assert second_result.returncode == 0, second_result.stdout + second_result.stderr
    assert "Still loop cache hit" in second_result.stdout
    commands = second_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "-c:v copy" in commands[0]


def test_invalid_static_bake_period_fails_loud(tmp_path: Path) -> None:
    """#1681: 1 GOP 周期を計算できない still 設定では full encode に逃げない。"""
    collection = _create_collection(tmp_path)
    skill_config_dir = tmp_path / "config" / "skills"
    skill_config_dir.mkdir(parents=True)
    (skill_config_dir / "videoup.yaml").write_text(
        "video:\n  still_fps: 0\n  still_gop: 300\n",
        encoding="utf-8",
    )

    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        collection=collection,
        with_loop=False,
    )

    assert result.returncode != 0
    assert "video.still_fps and video.still_gop must be positive numbers" in result.stdout


def test_static_bake_ffmpeg_failure_fails_loud(tmp_path: Path) -> None:
    """#1681: 短尺ベイク失敗時は全尺エンコードへ fallback しない。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={"FFMPEG_FAIL_MATCH": "still_baked.mp4"},
    )

    assert result.returncode != 0
    assert "still_baked.mp4 の生成に失敗" in result.stdout


def test_final_output_duration_over_one_frame_fails_loud(tmp_path: Path) -> None:
    """#1681: -shortest の既知 2.9 秒超過を生成後検証で成功扱いしない。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={
            "FFPROBE_DURATION": "7200",
            "FFPROBE_OUTPUT_DURATION": "7202.9",
            "FFPROBE_OUTPUT_FRAME_RATE": "1/1",
        },
    )

    assert result.returncode != 0
    assert "final output duration mismatch" in result.stdout
    assert "delta=2.900000s" in result.stdout


def test_final_output_duration_exactly_one_frame_succeeds(tmp_path: Path) -> None:
    """#1681: 期待尺との差がちょうど 1 フレームなら許容する。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={
            "FFPROBE_DURATION": "7200",
            "FFPROBE_OUTPUT_DURATION": "7201",
            "FFPROBE_OUTPUT_FRAME_RATE": "1/1",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "final output duration mismatch" not in result.stdout


@pytest.mark.parametrize(
    ("output_duration", "output_frame_rate"),
    [
        ("", "24/1"),
        ("not-a-duration", "24/1"),
        ("7200", ""),
        ("7200", "not-a-frame-rate"),
    ],
)
def test_final_output_invalid_duration_or_frame_rate_fails_loud(
    tmp_path: Path,
    output_duration: str,
    output_frame_rate: str,
) -> None:
    """#1681: 尺または frame-rate が空・不正なら検証成功にしない。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={
            "FFPROBE_DURATION": "7200",
            "FFPROBE_OUTPUT_DURATION": output_duration,
            "FFPROBE_OUTPUT_FRAME_RATE": output_frame_rate,
        },
    )

    assert result.returncode != 0
    assert "final output duration mismatch" in result.stdout


def test_final_output_ffprobe_failure_fails_loud(tmp_path: Path) -> None:
    """#1681: 最終出力を ffprobe で読めなければ非 0 で停止する。"""
    result, _ = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        with_loop=False,
        extra_env={"FFPROBE_OUTPUT_FAIL": "1"},
    )

    assert result.returncode != 0
    assert "ffprobe could not decode final output" in result.stdout


def test_missing_ffprobe_fails_before_ffmpeg(tmp_path: Path) -> None:
    """#1681: 必須になった最終検証器が無ければ生成を開始しない。"""
    collection = _create_collection(tmp_path)
    bin_dir = _create_stub_bin(tmp_path)
    (bin_dir / "ffprobe").unlink()
    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    result = subprocess.run(
        ["/bin/bash", str(_SCRIPT_PATH), str(collection)],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
    )

    assert result.returncode != 0
    assert "ERROR: ffprobe not found" in result.stdout


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
    assert len(ffmpeg_log.read_text(encoding="utf-8").splitlines()) == 1
    assert "-filter_complex" in master_cmd
    assert "-c:v libx264" in master_cmd
    assert "still_baked.mp4" not in master_cmd
    assert "-c:v copy" not in master_cmd


def test_audio_visualizer_legacy_config_keeps_original_filtergraph(tmp_path: Path) -> None:
    """#1686: 新キー未指定なら既存 colors + glow filtergraph を維持する。"""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"OVERLAYS_CONFIG": str(overlays_config), "JQ_AV_ENABLED": "true"},
    )

    assert result.returncode == 0, result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert "showfreqs=mode=bar:s=1280x180:rate=24:fscale=log:win_size=2048:win_func=hann:colors=white" in command
    assert "alphaextract" not in command
    assert "alphamerge" not in command


def test_audio_visualizer_combines_fill_mirror_symmetry_rounding_and_nested_glow(tmp_path: Path) -> None:
    """#1686: 各 effect を組み合わせた b2 相当の filtergraph を構築する。"""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "OVERLAYS_CONFIG": str(overlays_config),
            "JQ_AV_ENABLED": "true",
            "JQ_AV_FILL_TYPE": "gradient",
            "JQ_AV_FILL_TOP": "0xFF8800",
            "JQ_AV_FILL_BOTTOM": "0x4400AA",
            "JQ_AV_MIRROR_CENTER": "true",
            "JQ_AV_SYMMETRIC_VERTICAL": "true",
            "JQ_AV_ROUNDING_BLUR": "2.3",
            "JQ_AV_ROUNDING_CONTRAST": "3.2",
            "JQ_AV_GLOW_ENABLED": "true",
            "JQ_AV_GLOW_SIGMA": "6",
            "JQ_AV_GLOW_OPACITY": "0.40",
        },
    )

    assert result.returncode == 0, result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert "showfreqs=mode=bar:s=640x90" in command
    assert "hflip[avis_half_flip]" in command
    assert "hstack=inputs=2[avis_mirror]" in command
    assert "vflip[avis_bottom]" in command
    assert "vstack=inputs=2[avis_symmetric]" in command
    assert "format=gray,lut=y='val*0.85'[avis_shape]" in command
    assert "null,gblur=sigma=2.3,eq=contrast=3.2[avis_alpha]" in command
    assert "format=rgb24[avis_fill]" in command
    assert "[avis_fill][avis_alpha]alphamerge[avis]" in command
    assert "gblur=sigma=6,colorchannelmixer=aa=0.40" in command


def test_audio_visualizer_solid_fill_uses_color_source(tmp_path: Path) -> None:
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "OVERLAYS_CONFIG": str(overlays_config),
            "JQ_AV_ENABLED": "true",
            "JQ_AV_FILL_TYPE": "solid",
            "JQ_AV_FILL_COLOR": "0x12ABEF",
            "FILL_EFFECTIVE_TYPE": "solid",
        },
    )

    assert result.returncode == 0, result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert "color=c=0x12ABEF:s=1280x180:r=24,format=rgb24[avis_fill]" in command
    assert "alphamerge[avis]" in command


@pytest.mark.parametrize(
    ("env_key", "enabled", "fragment"),
    [
        ("JQ_AV_MIRROR_CENTER", True, "hflip[avis_half_flip]"),
        ("JQ_AV_MIRROR_CENTER", False, "hflip[avis_half_flip]"),
        ("JQ_AV_SYMMETRIC_VERTICAL", True, "vflip[avis_bottom]"),
        ("JQ_AV_SYMMETRIC_VERTICAL", False, "vflip[avis_bottom]"),
        ("JQ_AV_ROUNDING_BLUR", True, "null,gblur=sigma=2.3,eq=contrast=3.2"),
        ("JQ_AV_ROUNDING_BLUR", False, "null,gblur=sigma=2.3,eq=contrast=3.2"),
        ("JQ_AV_GLOW_ENABLED", True, "[avis]split=2[avis_core][avis_glow_src]"),
        ("JQ_AV_GLOW_ENABLED", False, "[avis]split=2[avis_core][avis_glow_src]"),
    ],
)
def test_audio_visualizer_effect_flags_are_independent(
    tmp_path: Path, env_key: str, enabled: bool, fragment: str
) -> None:
    """#1686: 各 effect の ON/OFF が他フラグに依存せず filtergraph へ反映される。"""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")
    extra_env = {
        "OVERLAYS_CONFIG": str(overlays_config),
        "JQ_AV_ENABLED": "true",
        "JQ_AV_FILL_TYPE": "solid",
        "JQ_AV_FILL_COLOR": "0x12ABEF",
        "FILL_EFFECTIVE_TYPE": "solid",
        "JQ_AV_GLOW_ENABLED": "false",
    }
    if env_key == "JQ_AV_ROUNDING_BLUR":
        extra_env[env_key] = "2.3" if enabled else ""
    else:
        extra_env[env_key] = "true" if enabled else "false"

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env=extra_env,
    )

    assert result.returncode == 0, result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert (fragment in command) is enabled


def test_audio_visualizer_invalid_fill_stops_before_render(tmp_path: Path) -> None:
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays": {"enabled": true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "OVERLAYS_CONFIG": str(overlays_config),
            "JQ_AV_ENABLED": "true",
            "JQ_AV_FILL_TYPE": "gradient",
            "FILL_HELPER_FAIL": "1",
        },
    )

    assert result.returncode != 0
    assert "invalid overlays.audio_visualizer.fill config" in result.stdout + result.stderr
    assert not ffmpeg_log.exists()


def test_videoup_skill_documents_current_overlay_support() -> None:
    """#1310: videoup 文書は overlay 未実装時代の説明を残さない。"""
    skill = _VIDEOUP_SKILL_PATH.read_text(encoding="utf-8")

    assert "`generate_videos.sh` は `config/channel/youtube.json::overlays.enabled: true`" in skill
    assert "filter_complex" in skill
    assert "Suno 側ではなく `/videoup` の overlays 設定で反映する" in skill
    assert "未実装" not in skill
    assert "v12.x にはこの filter 経路が無い" not in skill
    assert "#511 の実装を待つ" not in skill


def _audio_visualizer_env(style: str, **overrides: str) -> dict[str, str]:
    env = {
        "OVERLAY_AV_ENABLED": "true",
        "OVERLAY_AV_STYLE": style,
        "OVERLAY_AV_GLOW_ENABLED": "false",
    }
    env.update(overrides)
    return env


def test_audio_visualizer_style_missing_preserves_bar_filtergraph(tmp_path: Path) -> None:
    """#1684: style 未指定は v13 と同じ bar filtergraph を使う."""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays":{"enabled":true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"OVERLAYS_CONFIG": str(overlays_config), **_audio_visualizer_env("")},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert "showfreqs=mode=bar:s=1280x180" in command
    assert "hstack=inputs=2" not in command
    assert "geq=r=" not in command
    assert "audio-visualizer-mask" not in command


def test_audio_visualizer_mirror_mountain_builds_symmetric_filtergraph(tmp_path: Path) -> None:
    """#1684: mirror-mountain は低音センターの左右鏡像 + 上下対称にする."""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays":{"enabled":true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "OVERLAYS_CONFIG": str(overlays_config),
            **_audio_visualizer_env(
                "mirror-mountain",
                OVERLAY_AV_SIZE="300x110",
                OVERLAY_AV_BARS="16",
            ),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert "showfreqs=mode=bar:s=150x55" in command
    assert "hflip[avis_left]" in command
    assert "hstack=inputs=2" in command
    assert "vflip[avis_bottom]" in command
    assert "vstack=inputs=2" in command
    assert "alphamerge" in command


@pytest.mark.parametrize(("style", "mode"), [("ring", "bar"), ("ring-line", "line")])
def test_audio_visualizer_ring_styles_build_polar_filtergraph(tmp_path: Path, style: str, mode: str) -> None:
    """#1684: ring 系は showfreqs を極座標ワープして runtime mask で切り抜く."""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays":{"enabled":true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={
            "OVERLAYS_CONFIG": str(overlays_config),
            **_audio_visualizer_env(
                style,
                OVERLAY_AV_SIZE="300x110",
                OVERLAY_AV_BARS="12",
                OVERLAY_AV_RING_INNER_R="30",
                OVERLAY_AV_RING_LENGTH="20",
                OVERLAY_AV_ARC_START="30",
                OVERLAY_AV_ARC_END="330",
                OVERLAY_AV_POSITION="(W-w)/2:412",
            ),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    command = _filter_complex_command(ffmpeg_log)
    assert f"showfreqs=mode={mode}:s=300x110" in command
    assert "scale=12:110:flags=neighbor,scale=100:100:flags=neighbor" in command
    assert "geq=r='r(mod(atan2(" in command
    assert "-30)*H/20" in command
    assert "overlay=(W-w)/2:412" in command


def test_audio_visualizer_invalid_style_fails_before_ffmpeg(tmp_path: Path) -> None:
    """#1684: 不正 style は有効値を表示し ffmpeg 起動前に停止する."""
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text('{"overlays":{"enabled":true}}', encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        extra_env={"OVERLAYS_CONFIG": str(overlays_config), **_audio_visualizer_env("heart")},
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "allowed: bar, mirror-mountain, ring, ring-line" in output
    assert not ffmpeg_log.exists()


@pytest.mark.parametrize("style", ["mirror-mountain", "ring", "ring-line"])
def test_audio_visualizer_new_styles_render_minimal_video_with_real_ffmpeg(tmp_path: Path, style: str) -> None:
    """#1684: 追加 preset は外部素材なしで最小動画を最後まで生成できる."""
    if any(shutil.which(command) is None for command in ("ffmpeg", "ffprobe", "jq")):
        pytest.skip("ffmpeg, ffprobe and jq are required for visualizer e2e tests")

    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    master_path = collection / "01-master" / "master-mix.wav"
    (assets_dir / "loop.mp4").unlink()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            str(master_path),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x202030:s=320x180",
            "-frames:v",
            "1",
            str(assets_dir / "main.jpg"),
        ],
        check=True,
    )
    overlays_config = tmp_path / "youtube.json"
    overlays_config.write_text(
        json.dumps(
            {
                "overlays": {
                    "enabled": True,
                    "audio_visualizer": {
                        "enabled": True,
                        "style": style,
                        "bars": 12,
                        "size": "300x110",
                        "position": "(W-w)/2:(H-h)/2",
                        "glow_enabled": False,
                        "ring": {"inner_r": 30, "length": 20, "arc_deg": [30, 330]},
                    },
                    "encoder": {"preset": "ultrafast", "crf": 30},
                }
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["OVERLAYS_CONFIG"] = str(overlays_config)

    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(collection)],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = next((collection / "01-master").glob("*-Master.mp4"))
    assert output.stat().st_size > 0


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

    bin_dir = _shared_stub_bin_dir()
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
    final_cmd = _filter_complex_command(ffmpeg_log)
    assert "-filter_complex" in final_cmd
    assert "[vout]" in final_cmd
    assert "-c:v libx264" in final_cmd
    assert "-c:v copy" not in final_cmd
    _assert_effect_alpha_plane_and_neutral_chroma(
        final_cmd,
        noise_filter="noise=alls=80:allf=t+u",
        lum_threshold=230,
    )
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
    final_cmd = _filter_complex_command(ffmpeg_log)
    assert "gblur" in final_cmd
    _assert_effect_alpha_plane_and_source_chroma(
        final_cmd,
        noise_filter="noise=alls=100:allf=t+u",
        lum_threshold=240,
    )
    # medium は alpha=0.20
    assert "0.20*255" in final_cmd


def test_effect_bake_cache_stamp_includes_filtergraph(tmp_path: Path) -> None:
    """旧形式の stamp は filtergraph 変更後に cache hit せず再ベイクされる。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    background = assets_dir / "main.jpg"
    (assets_dir / "fx_baked.mp4").write_bytes(b"stale-cache")
    old_stamp = f"particles|subtle|36|{int(background.stat().st_mtime)}|6000k"
    (assets_dir / "fx_baked.params").write_text(old_stamp, encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        extra_env={"VIDEOUP_EFFECT": "particles", "FFPROBE_DURATION": "120"},
        collection=collection,
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Baking particles effect loop" in result.stdout
    assert "Effect loop cache hit" not in result.stdout
    assert "|filter:" in (assets_dir / "fx_baked.params").read_text(encoding="utf-8")
    assert len(ffmpeg_log.read_text(encoding="utf-8").splitlines()) == 2


def test_particles_geq_outputs_neutral_non_green_pixels_with_real_ffmpeg() -> None:
    """geq 後の色差固定で実出力が緑被りしないことを最小フレームで確認する。"""
    frame = _run_ffmpeg_rgba_frame(
        "color=c=white:s=2x2:r=1:d=1,format=yuv420p,format=yuva420p,"
        "geq=lum='if(gt(lum(X,Y),230),255,0)':cb=128:cr=128:a='if(gt(lum(X,Y),230),255,0)',"
        "format=rgba",
        width=2,
        height=2,
    )
    pixels = [tuple(frame[index : index + 4]) for index in range(0, len(frame), 4)]
    assert pixels
    for red, green, blue, alpha in pixels:
        assert alpha == 255
        assert red >= 250 and green >= 250 and blue >= 250
        assert max(red, green, blue) - min(red, green, blue) <= 2


def test_bokeh_geq_preserves_warm_chroma_with_real_ffmpeg() -> None:
    """bokeh は alpha plane を持たせつつ 0xffe8b0 由来の暖色 chroma を維持する。"""
    frame = _run_ffmpeg_rgba_frame(
        "color=c=0xffe8b0:s=240x135:r=24:d=1,format=yuv420p,"
        "noise=alls=100:allf=t+u,format=yuva420p,"
        "geq=lum='if(gt(lum(X,Y),240),255,0)':cb='cb(X,Y)':cr='cr(X,Y)':a='if(gt(lum(X,Y),240),255,0)',"
        "scale=240:135:flags=lanczos,gblur=sigma=2,format=rgba",
        width=240,
        height=135,
    )
    pixels = [tuple(frame[index : index + 4]) for index in range(0, len(frame), 4)]
    visible = [pixel for pixel in pixels if pixel[3] > 0]
    assert visible
    avg_red = sum(pixel[0] for pixel in visible) / len(visible)
    avg_green = sum(pixel[1] for pixel in visible) / len(visible)
    avg_blue = sum(pixel[2] for pixel in visible) / len(visible)
    assert avg_red > avg_green > avg_blue
    assert avg_red - avg_blue >= 40


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


def test_static_image_with_effect_uses_textless_main_not_thumbnail(tmp_path: Path) -> None:
    """#1310: effect あり静止画経路でも thumbnail.* ではなく textless main.* を背景にする。"""
    collection = _create_collection(tmp_path)
    assets_dir = collection / "10-assets"
    (assets_dir / "main.png").write_bytes(b"fake-png-background")
    (assets_dir / "thumbnail.jpg").write_bytes(b"text-included-thumbnail")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        extra_env={"VIDEOUP_EFFECT": "particles"},
        collection=collection,
        with_loop=False,
    )

    assert result.returncode == 0, result.stderr
    final_cmd = ffmpeg_log.read_text(encoding="utf-8").splitlines()[-1]
    assert "10-assets/main.png" in final_cmd
    assert "10-assets/thumbnail.jpg" not in final_cmd


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
