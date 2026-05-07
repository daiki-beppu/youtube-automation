"""Issue #137: `.claude/skills/videoup/references/generate_videos.sh` Intro 統合モード v13 (G 節)。

bash スクリプトを偽 ffmpeg / ffprobe stub と共に実行し、
- branding/intro.mp4 検知時の 3 段ビルド (intro_video_only → body → concat)
- 通常 loop モード (intro 無し) のリグレッション
- loop_normalized.mp4 生成時の `-r 24` 強制
- 静止画モード + intro.mp4 ありの組み合わせの早期 fail
- 中間 ffmpeg 失敗時の exit code 伝播
を検証する。
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / ".claude" / "skills" / "videoup" / "references" / "generate_videos.sh"


def _make_ffmpeg_stub(stub_dir: Path, log_path: Path, *, exit_codes: list[int] | None = None) -> None:
    """偽 ffmpeg/ffprobe を `stub_dir` に書く。

    引数はすべて `log_path` に追記し、出力ファイル (cmd 末尾) を空ファイルとして
    生成する。`exit_codes` で呼び出しごとの exit code を制御 (default: 全て 0)。
    """
    stub_dir.mkdir(parents=True, exist_ok=True)
    counter_file = stub_dir / ".counter"
    counter_file.write_text("0", encoding="utf-8")

    exit_seq = ":".join(str(c) for c in (exit_codes or [0] * 10))
    ffmpeg_body = f"""#!/usr/bin/env bash
echo "$@" >> '{log_path}'
# 出力先 (cmd 末尾) を空ファイルとして touch する
output="${{!#}}"
case "$output" in
    *.mp4|*.txt|*.wav|*.m4a)
        mkdir -p "$(dirname "$output")" 2>/dev/null
        : > "$output"
        ;;
esac
# 呼び出しカウントで exit code を切り替え
n=$(cat '{counter_file}')
n=$((n + 1))
echo $n > '{counter_file}'
codes='{exit_seq}'
IFS=':' read -ra arr <<< "$codes"
exit_code="${{arr[$((n - 1))]}}"
exit "${{exit_code:-0}}"
"""
    ffmpeg_path = stub_dir / "ffmpeg"
    ffmpeg_path.write_text(ffmpeg_body, encoding="utf-8")
    ffmpeg_path.chmod(ffmpeg_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # ffprobe: 1920x1080 / yuv420p を返す stub (loop 正規化スキップを許可)
    ffprobe_body = f"""#!/usr/bin/env bash
echo "$@" >> '{log_path}'
# `-show_entries stream=width,height,pix_fmt -of csv=p=0` を要求された場合
case "$*" in
    *show_entries*stream=width,height,pix_fmt*)
        echo "1920,1080,yuv420p"
        ;;
    *show_entries*format=duration*)
        echo "60.00"
        ;;
    *)
        ;;
esac
exit 0
"""
    ffprobe_path = stub_dir / "ffprobe"
    ffprobe_path.write_text(ffprobe_body, encoding="utf-8")
    ffprobe_path.chmod(ffprobe_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # afinfo: macOS 環境で生 afinfo が PATH に出てしまうのを防ぐため、stub PATH に
    # 偽 afinfo を置いて固定 duration (60s) を返す。
    afinfo_body = f"""#!/usr/bin/env bash
echo "$@" >> '{log_path}'
echo "estimated duration: 60.00 sec"
exit 0
"""
    afinfo_path = stub_dir / "afinfo"
    afinfo_path.write_text(afinfo_body, encoding="utf-8")
    afinfo_path.chmod(afinfo_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_ffprobe_returns_unnormalized(stub_dir: Path, log_path: Path) -> None:
    """ffprobe が 1280x720 / yuv422p を返すよう書き換える (= loop 正規化が必要)。"""
    ffprobe_body = f"""#!/usr/bin/env bash
echo "$@" >> '{log_path}'
case "$*" in
    *show_entries*stream=width,height,pix_fmt*)
        echo "1280,720,yuv422p"
        ;;
    *show_entries*format=duration*)
        echo "60.00"
        ;;
    *)
        ;;
esac
exit 0
"""
    ffprobe_path = stub_dir / "ffprobe"
    ffprobe_path.write_text(ffprobe_body, encoding="utf-8")
    ffprobe_path.chmod(ffprobe_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _setup_collection_repo(
    tmp_path: Path,
    *,
    with_intro: bool,
    with_loop: bool,
    with_thumbnail: bool = True,
    with_master: bool = True,
) -> tuple[Path, Path]:
    """tmp_path に repo + collection ツリーを組む。

    Returns:
        (repo_root, collection_dir)
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    # git rev-parse 相当に依存しないよう、collection の上位パスから直接解決させる
    # generate_videos.sh は `branding/intro.mp4` を repo-root 起点で読む想定
    collection = repo / "collections" / "planning" / "20260101-test-collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "10-assets").mkdir()

    if with_thumbnail:
        (collection / "10-assets" / "main.png").write_bytes(b"\x89PNG\x00")
    if with_master:
        (collection / "01-master" / "master-mix.m4a").write_bytes(b"\x00")
    if with_loop:
        (collection / "10-assets" / "loop.mp4").write_bytes(b"\x00")
    if with_intro:
        (repo / "branding").mkdir()
        (repo / "branding" / "intro.mp4").write_bytes(b"\x00")
    return repo, collection


def _run_script(
    collection: Path,
    stub_dir: Path,
    *,
    extra_env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """generate_videos.sh を stub PATH 限定で実行する (実 ffmpeg / afinfo を排除)。"""
    env = {
        "PATH": f"{stub_dir}:/bin:/usr/bin",
        "HOME": str(stub_dir.parent),
    }
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(collection)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def script_exists() -> None:
    if not _SCRIPT_PATH.exists():
        pytest.skip(f"generate_videos.sh が無い: {_SCRIPT_PATH}")


# ---------- G-1: intro mode (intro.mp4 + loop.mp4) ----------


def test_intro_mode_runs_3stage_concat_when_intro_and_loop_present(
    script_exists, tmp_path: Path,
) -> None:
    """Given branding/intro.mp4 + 10-assets/loop.mp4 が両方存在
    When generate_videos.sh を実行
    Then 3 段ビルド (intro_video_only → body → concat) のために ffmpeg が
        複数回呼ばれ、かつ concat demuxer の `-f concat` か
        `concat:` プロトコル相当が cmd ログに出る。
    """
    repo, collection = _setup_collection_repo(tmp_path, with_intro=True, with_loop=True)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    _make_ffmpeg_stub(stub_dir, log)

    result = _run_script(collection, stub_dir)
    assert result.returncode == 0, (
        f"intro mode で失敗:\nrc={result.returncode}\nstderr={result.stderr}\nstdout={result.stdout}"
    )

    log_text = log.read_text(encoding="utf-8") if log.exists() else ""
    assert log_text, "ffmpeg stub が呼ばれていない"

    # 3 段ビルド経路: intro_video_only.mp4 / body_video.mp4 / concat 連結のいずれかが見える
    assert (
        "intro_video_only" in log_text
        or "body_video" in log_text
        or "-f concat" in log_text
    ), (
        f"intro mode の 3 段ビルド痕跡が ffmpeg cmd ログに無い:\n{log_text}"
    )


# ---------- G-2: loop mode (intro.mp4 なし) — 既存挙動リグレッション ----------


def test_loop_mode_falls_back_to_single_pass_stream_copy_when_intro_absent(
    script_exists, tmp_path: Path,
) -> None:
    """Given branding/intro.mp4 が存在せず loop.mp4 のみ
    When generate_videos.sh を実行
    Then 既存の単発 stream copy 経路 (`-c:v copy`) が cmd ログに出る。
    """
    _, collection = _setup_collection_repo(tmp_path, with_intro=False, with_loop=True)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    _make_ffmpeg_stub(stub_dir, log)

    result = _run_script(collection, stub_dir)
    assert result.returncode == 0, (
        f"loop mode (intro 無し) で失敗:\nrc={result.returncode}\nstderr={result.stderr}"
    )

    log_text = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "-c:v copy" in log_text, (
        f"既存 stream copy 経路が消えた:\n{log_text}"
    )


# ---------- G-3: loop_normalized 生成時に `-r 24` が強制される ----------


def test_loop_normalize_pass_includes_r_24(
    script_exists, tmp_path: Path,
) -> None:
    """Given loop.mp4 が 1280x720 / yuv422p (= 正規化キャッシュが必要)
    When generate_videos.sh を実行
    Then loop_normalized.mp4 生成 ffmpeg cmd に `-r 24` が含まれる
        (intro.mp4 と fps を揃え concat demuxer + stream copy を可能にするため)。
    """
    _, collection = _setup_collection_repo(tmp_path, with_intro=True, with_loop=True)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    _make_ffmpeg_stub(stub_dir, log)
    _make_ffprobe_returns_unnormalized(stub_dir, log)

    result = _run_script(collection, stub_dir)
    # 失敗してもログは見たいので、fail 内容を含めて assert
    log_text = log.read_text(encoding="utf-8") if log.exists() else ""

    # loop_normalized.mp4 への出力を含む cmd 行を抽出
    normalize_lines = [
        line for line in log_text.splitlines() if "loop_normalized.mp4" in line
    ]
    assert normalize_lines, (
        f"loop_normalized.mp4 生成 cmd が記録されていない (rc={result.returncode}):\n"
        f"stderr={result.stderr}\nlog={log_text}"
    )
    joined = " ".join(normalize_lines)
    assert "-r 24" in joined, (
        f"loop_normalized.mp4 生成に `-r 24` 強制が無い:\n  cmds={normalize_lines}"
    )


# ---------- G-4: loop.mp4 が既に正規化済みなら正規化スキップ ----------


def test_loop_normalize_skipped_when_loop_already_normalized(
    script_exists, tmp_path: Path,
) -> None:
    """Given loop.mp4 が 1920x1080 / yuv420p (= 正規化不要)
    When generate_videos.sh を実行
    Then loop_normalized.mp4 を作る ffmpeg cmd は呼ばれない
        (既存最適化のリグレッション防止)。
    """
    _, collection = _setup_collection_repo(tmp_path, with_intro=False, with_loop=True)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    _make_ffmpeg_stub(stub_dir, log)  # ffprobe は 1920x1080/yuv420p を返す

    result = _run_script(collection, stub_dir)
    assert result.returncode == 0

    log_text = log.read_text(encoding="utf-8") if log.exists() else ""
    normalize_lines = [
        line for line in log_text.splitlines() if "loop_normalized.mp4" in line
    ]
    assert not normalize_lines, (
        f"既に正規化済みの loop.mp4 で loop_normalized.mp4 を再生成している:\n  {normalize_lines}"
    )


# ---------- G-5: intro.mp4 あり + loop.mp4 なし → exit 1 ----------


def test_intro_with_static_only_exits_1(
    script_exists, tmp_path: Path,
) -> None:
    """Given branding/intro.mp4 はあるが loop.mp4 が無い (= 静止画モード)
    When generate_videos.sh を実行
    Then exit 1 + 「静止画モードでは intro 統合非対応」相当のエラー文。
    """
    _, collection = _setup_collection_repo(tmp_path, with_intro=True, with_loop=False)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    _make_ffmpeg_stub(stub_dir, log)

    result = _run_script(collection, stub_dir)
    assert result.returncode != 0, (
        f"静止画モード + intro.mp4 で rc=0 で抜けた:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "intro" in combined.lower() or "静止画" in combined, (
        f"intro 統合非対応のエラー文が出ていない:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ---------- G-6: 中間 ffmpeg 失敗時に exit code が伝播される ----------


def test_intro_mode_propagates_intermediate_ffmpeg_failure(
    script_exists, tmp_path: Path,
) -> None:
    """Given intro mode で 1 回目の ffmpeg (intro_video_only) が exit 5 で失敗
    When generate_videos.sh を実行
    Then exit code が 0 でない (中間ステップ失敗が呼び出し側に伝播)。
    """
    _, collection = _setup_collection_repo(tmp_path, with_intro=True, with_loop=True)
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "ffmpeg.log"
    # ffmpeg 1 回目は exit 5、後続は 0 (実装が早期 return しなければ呼ばれてしまう)
    _make_ffmpeg_stub(stub_dir, log, exit_codes=[5, 0, 0, 0, 0])

    result = _run_script(collection, stub_dir)
    assert result.returncode != 0, (
        f"中間 ffmpeg 失敗が伝播していない (rc=0 で返った):\nstderr={result.stderr}"
    )
