"""Executable contracts for distributed shell reference scripts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
SKILLS = ROOT / ".claude" / "skills"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(
    script: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(script), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _fake_git_env(tmp_path: Path, worktree_root: Path, main_root: Path, *, fail: bool = False) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    _write_executable(
        bin_dir / "git",
        """#!/bin/bash
[[ "${GIT_FAIL:-0}" == 1 ]] && exit 23
if [[ "$*" == "rev-parse --git-common-dir" ]]; then
  printf '%s/.git\n' "$MAIN_ROOT"
elif [[ "$*" == "rev-parse --show-toplevel" ]]; then
  case "$PWD" in
    "$MAIN_ROOT/.git") printf '%s\n' "$MAIN_ROOT" ;;
    *) printf '%s\n' "$WORKTREE_ROOT" ;;
  esac
else
  exit 2
fi
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "WORKTREE_ROOT": str(worktree_root),
            "MAIN_ROOT": str(main_root),
            "GIT_FAIL": "1" if fail else "0",
        }
    )
    return env


def test_worktree_sync_copies_overwrites_and_cleans_preview(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    main = tmp_path / "main"
    collection_rel = Path("collections/planning/20260731-test")
    source = worktree / collection_rel
    destination = main / collection_rel
    (main / ".git").mkdir(parents=True)
    (source / "01-master" / "preview").mkdir(parents=True)
    (source / "10-assets").mkdir()
    (source / "01-master" / "master.mp3").write_bytes(b"new-master")
    (source / "01-master" / "01-track.wav").write_bytes(b"track")
    (source / "01-master" / "master.wav").write_bytes(b"excluded")
    (source / "01-master" / "loop.mp4").write_bytes(b"video")
    (source / "10-assets" / "main.jpg").write_bytes(b"main")
    (source / "01-master" / "preview" / "sample.mp3").write_bytes(b"preview")
    (destination / "01-master").mkdir(parents=True)
    (destination / "01-master" / "master.mp3").write_bytes(b"old-master")
    env = _fake_git_env(tmp_path, worktree, main)

    result = _run(
        SKILLS / "music" / "references" / "worktree_sync.sh",
        cwd=source,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert (destination / "01-master" / "master.mp3").read_bytes() == b"new-master"
    assert (destination / "02-Individual-music" / "01-track.wav").read_bytes() == b"track"
    assert (destination / "02-Individual-music" / "master.wav").read_bytes() == b"excluded"
    assert (destination / "01-master" / "loop.mp4").read_bytes() == b"video"
    assert (destination / "10-assets" / "main.jpg").read_bytes() == b"main"
    assert not (source / "01-master" / "preview").exists()


def test_worktree_sync_dry_run_preserves_files_and_git_failure_propagates(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    main = tmp_path / "main"
    source = worktree / "collections" / "planning" / "sample"
    (main / ".git").mkdir(parents=True)
    (source / "01-master" / "preview").mkdir(parents=True)
    (source / "01-master" / "master.mp3").write_bytes(b"master")
    env = _fake_git_env(tmp_path, worktree, main)
    dry = _run(
        SKILLS / "music" / "references" / "worktree_sync.sh",
        "--dry-run",
        cwd=source,
        env=env,
    )
    assert dry.returncode == 0
    assert "DRY-RUN" in dry.stdout
    assert (source / "01-master" / "preview").exists()
    assert not (main / "collections").exists()

    failed_env = _fake_git_env(tmp_path / "failure", worktree, main, fail=True)
    failed = _run(
        SKILLS / "music" / "references" / "worktree_sync.sh",
        cwd=source,
        env=failed_env,
    )
    assert failed.returncode == 23


def _ffmpeg_env(tmp_path: Path, *, fail_pattern: str = "") -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    calls = tmp_path / "ffmpeg-calls.txt"
    _write_executable(
        bin_dir / "ffmpeg",
        """#!/bin/bash
printf '%s\n' "$*" >> "$FFMPEG_CALLS"
[[ -n "$FFMPEG_FAIL_PATTERN" && "$*" == *"$FFMPEG_FAIL_PATTERN"* ]] && exit 12
last="${@: -1}"
case "$last" in
  -|/dev/null) ;;
  *) mkdir -p "$(dirname "$last")"; printf 'media' > "$last" ;;
esac
""",
    )
    _write_executable(
        bin_dir / "open",
        '#!/bin/bash\nprintf \'open:%s\\n\' "$*" >> "$FFMPEG_CALLS"\n',
    )
    _write_executable(
        bin_dir / "uv",
        "#!/bin/bash\nprintf '%s\\n' \"$TEST_CONTENT_MODEL\"\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FFMPEG_CALLS": str(calls),
            "FFMPEG_FAIL_PATTERN": fail_pattern,
        }
    )
    return env, calls


def test_short_generates_release_clips_when_config_content_model_is_release(tmp_path: Path) -> None:
    release = tmp_path / "01-blue-night"
    video = release / "video"
    video.mkdir(parents=True)
    (video / "blue-night-jp.mp4").write_bytes(b"jp")
    (video / "blue-night-en.mp4").write_bytes(b"en")
    env, calls = _ffmpeg_env(tmp_path / "ok")
    env["TEST_CONTENT_MODEL"] = "release"

    result = _run(
        SKILLS / "short" / "references" / "generate-shorts.sh",
        str(release),
        "-s",
        "11",
        "-t",
        "22",
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 0
    assert (video / "short-jp.mp4").exists()
    assert (video / "short-en.mp4").exists()
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all("-ss 11 -t 22" in line for line in lines)

    failure_root = tmp_path / "failure"
    failure_root.mkdir()
    fail_env, _ = _ffmpeg_env(failure_root, fail_pattern="blue-night-en.mp4")
    fail_env["TEST_CONTENT_MODEL"] = "release"
    failed = _run(
        SKILLS / "short" / "references" / "generate-shorts.sh",
        str(release),
        cwd=tmp_path,
        env=fail_env,
    )
    assert failed.returncode == 12


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "collection"
    (collection / "10-assets").mkdir(parents=True)
    (collection / "01-master").mkdir()
    (collection / "10-assets" / "short-loop.mp4").write_bytes(b"loop")
    (collection / "01-master" / "TestMaster.mp3").write_bytes(b"audio")
    return collection


def test_collection_shorts_generates_every_label_and_fails_if_any_background_job_fails(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    env, calls = _ffmpeg_env(tmp_path / "ok")
    env.update(
        {
            "TEST_CONTENT_MODEL": "collection",
            "SHORT_STARTS": "10 20",
            "SHORT_LABELS": "first second",
        }
    )
    result = _run(
        SKILLS / "short" / "references" / "generate-shorts.sh",
        str(collection),
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    outputs = sorted((collection / "01-master" / "shorts").glob("*.mp4"))
    assert [path.name for path in outputs] == ["short-01-first.mp4", "short-02-second.mp4"]
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 2

    failure_root = tmp_path / "partial-failure"
    failure_root.mkdir()
    fail_env, _ = _ffmpeg_env(failure_root, fail_pattern="short-02-second.mp4")
    fail_env.update(
        {
            "TEST_CONTENT_MODEL": "collection",
            "SHORT_STARTS": "10 20",
            "SHORT_LABELS": "first second",
        }
    )
    failed = _run(
        SKILLS / "short" / "references" / "generate-shorts.sh",
        str(collection),
        cwd=tmp_path,
        env=fail_env,
    )
    assert failed.returncode == 12
    assert "ffmpeg job failed" in failed.stderr


def test_short_rejects_unknown_config_content_model(tmp_path: Path) -> None:
    env, calls = _ffmpeg_env(tmp_path / "unknown")
    env["TEST_CONTENT_MODEL"] = "other"

    result = _run(
        SKILLS / "short" / "references" / "generate-shorts.sh",
        str(tmp_path / "target"),
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 2
    assert "unsupported content_model.type: other" in result.stderr
    assert not calls.exists()


def test_crop_positions_rejects_missing_input_and_propagates_ffmpeg_failure(tmp_path: Path) -> None:
    script = SKILLS / "short" / "references" / "test-crop-positions.sh"
    env, calls = _ffmpeg_env(tmp_path / "missing")
    missing = _run(script, str(tmp_path / "missing.mp4"), cwd=tmp_path, env=env)
    assert missing.returncode == 1
    assert "master video" in missing.stderr
    assert not calls.exists()

    video = tmp_path / "master.mp4"
    video.write_bytes(b"video")
    fail_root = tmp_path / "crop-failure"
    fail_root.mkdir()
    fail_env, _ = _ffmpeg_env(fail_root, fail_pattern="x400")
    failed = _run(script, str(video), "15", cwd=tmp_path, env=fail_env)
    assert failed.returncode == 12


def _streaming_env(tmp_path: Path, *, op_fail: bool = False, terraform_fail: str = "") -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    calls = tmp_path / "streaming-calls.jsonl"
    _write_executable(
        bin_dir / "op",
        """#!/bin/bash
[[ "${OP_FAIL:-0}" == 1 ]] && exit 19
case "$2" in
  *token*) printf '{"token":"youtube"}' ;;
  *client*) printf '{"installed":{"client_id":"client"}}' ;;
  *codex*) printf '{"auth":"codex"}' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "terraform",
        """#!/bin/bash
python3 - "$*" >> "$STREAMING_CALLS" <<'PY'
import json, os, sys
print(json.dumps({
    "argv": sys.argv[1],
    "token": os.environ.get("TF_VAR_live_chat_youtube_token_json"),
    "client": os.environ.get("TF_VAR_live_chat_client_secrets_json"),
    "codex": os.environ.get("TF_VAR_live_chat_codex_auth_json"),
    "channel": os.environ.get("TF_VAR_live_chat_channel_dir"),
    "revision": os.environ.get("TF_VAR_live_chat_credentials_revision"),
}))
PY
[[ -n "$TERRAFORM_FAIL" && "$*" == *"$TERRAFORM_FAIL"* ]] && exit 21
exit 0
""",
    )
    _write_executable(
        bin_dir / "realpath",
        "#!/bin/bash\npython3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' \"$1\"\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "STREAMING_CALLS": str(calls),
            "OP_FAIL": "1" if op_fail else "0",
            "TERRAFORM_FAIL": terraform_fail,
            "OP_LIVE_CHAT_TOKEN_REF": "op://vault/token/value",
            "OP_LIVE_CHAT_CLIENT_SECRETS_REF": "op://vault/client/value",
            "OP_CODEX_AUTH_REF": "op://vault/codex/value",
        }
    )
    return env, calls


def _live_chat_paths(tmp_path: Path) -> tuple[Path, Path]:
    terraform = tmp_path / "terraform"
    channel = tmp_path / "channel"
    terraform.mkdir()
    (terraform / "main.tf").write_text("# terraform\n", encoding="utf-8")
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / "config" / "channel" / "comments.json").write_text("{}\n", encoding="utf-8")
    return terraform, channel


def test_live_chat_deploy_passes_ephemeral_payload_and_terraform_exit(tmp_path: Path) -> None:
    terraform, channel = _live_chat_paths(tmp_path)
    env, calls = _streaming_env(tmp_path / "ok")
    result = _run(
        SKILLS / "streaming" / "references" / "deploy_live_chat.sh",
        "--tf-dir",
        str(terraform),
        "--auto-approve",
        str(channel),
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payloads = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert [payload["argv"] for payload in payloads] == [
        f"-chdir={terraform} plan",
        f"-chdir={terraform} apply -auto-approve",
    ]
    assert payloads[0]["token"] == '{"token":"youtube"}'
    assert payloads[0]["client"] == '{"installed":{"client_id":"client"}}'
    assert payloads[0]["codex"] == '{"auth":"codex"}'
    assert payloads[0]["channel"] == str(channel.resolve())
    assert len(payloads[0]["revision"]) == 64
    for secret_value in (
        '{"token":"youtube"}',
        '{"installed":{"client_id":"client"}}',
        '{"auth":"codex"}',
    ):
        assert secret_value not in result.stdout

    failure_root = tmp_path / "terraform-failure"
    failure_root.mkdir()
    fail_env, _ = _streaming_env(failure_root, terraform_fail="plan")
    failed = _run(
        SKILLS / "streaming" / "references" / "deploy_live_chat.sh",
        "--tf-dir",
        str(terraform),
        str(channel),
        cwd=tmp_path,
        env=fail_env,
    )
    assert failed.returncode == 21


def test_live_chat_deploy_propagates_op_failure_before_terraform(tmp_path: Path) -> None:
    terraform, channel = _live_chat_paths(tmp_path)
    env, calls = _streaming_env(tmp_path / "op-failure", op_fail=True)
    result = _run(
        SKILLS / "streaming" / "references" / "deploy_live_chat.sh",
        "--tf-dir",
        str(terraform),
        str(channel),
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 19
    assert not calls.exists()


def test_notify_emits_escaped_payload_and_absorbs_curl_failure(tmp_path: Path) -> None:
    env_file = tmp_path / "health.env"
    env_file.write_text(
        'DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/id/token"\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "curl-args.txt"
    _write_executable(
        bin_dir / "curl",
        '#!/bin/bash\nprintf \'%s\\n\' "$*" > "$CURL_CALLS"\nexit "${CURL_RC:-0}"\n',
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "YOUTUBE_STREAM_HEALTHCHECK_ENV_FILE": str(env_file),
            "CURL_CALLS": str(calls),
            "CURL_RC": "22",
        }
    )
    message = 'line 1\n"quoted"\\tab\t'
    result = _run(
        SKILLS / "streaming" / "references" / "notify.sh",
        message,
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 0
    argv = calls.read_text(encoding="utf-8")
    assert "--connect-timeout 5 --max-time 10" in argv
    assert '{"content":"line 1\\n\\"quoted\\"\\\\tab\\t"}' in argv
    assert "https://discord.com/api/webhooks/id/token" in argv


def test_run_ffmpeg_forwards_exact_argv_and_exit_code(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "ffmpeg-wrapper.txt"
    _write_executable(
        bin_dir / "ffmpeg",
        '#!/bin/bash\nprintf \'%s\\n\' "$*" > "$FFMPEG_WRAPPER_CALLS"\nexit 18\n',
    )
    env = os.environ.copy()
    env.update(
        {
            "VIDEO": "/videos/live.mp4",
            "RTMP_URL": "rtmp://example.test/key",
            "FFMPEG_BIN": str(bin_dir / "ffmpeg"),
            "FFMPEG_WRAPPER_CALLS": str(calls),
        }
    )
    result = _run(
        SKILLS / "streaming" / "references" / "run-ffmpeg.sh",
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 18
    assert calls.read_text(encoding="utf-8").strip() == (
        "-re -stream_loop -1 -i /videos/live.mp4 -c:v copy -c:a copy -f flv rtmp://example.test/key"
    )


def _overlay_benchmark_env(tmp_path: Path, *, fail_pattern: str = "") -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    output_dir = tmp_path / "output"
    bin_dir.mkdir(parents=True)
    calls = tmp_path / "benchmark-ffmpeg.txt"
    _write_executable(
        bin_dir / "ffmpeg",
        """#!/bin/bash
printf '%s\n' "$*" >> "$BENCHMARK_FFMPEG_CALLS"
if [[ "$*" == *"-encoders"* ]]; then
  printf ' V..... libx264 software encoder\n'
  exit 0
fi
if [[ -n "$BENCHMARK_FAIL_PATTERN" && "$*" == *"$BENCHMARK_FAIL_PATTERN"* ]]; then
  exit 31
fi
last="${@: -1}"
if [[ "$last" == "-" ]]; then
  printf 'SSIM Y:0.99 All:0.987654 (19.0)\n' >&2
else
  mkdir -p "$(dirname "$last")"
  printf 'encoded-media' > "$last"
fi
""",
    )
    _write_executable(bin_dir / "ffprobe", "#!/bin/bash\nprintf 'h264\\n'\n")
    _write_executable(
        bin_dir / "time",
        """#!/bin/bash
time_file=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -p) shift ;;
    -o) time_file="$2"; shift 2 ;;
    *) break ;;
  esac
done
"$@"
rc=$?
printf 'real 1.25\nuser 0.50\nsys 0.25\n' > "$time_file"
exit "$rc"
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "BENCHMARK_FFMPEG_CALLS": str(calls),
            "BENCHMARK_FAIL_PATTERN": fail_pattern,
            "VIDEOUP_BENCH_DURATION": "1",
            "VIDEOUP_BENCH_RUNS": "2",
            "VIDEOUP_BENCH_OUTPUT_DIR": str(output_dir),
        }
    )
    return env, output_dir, calls


def test_overlay_benchmark_runs_available_candidates_and_aggregates_results(tmp_path: Path) -> None:
    env, output_dir, calls = _overlay_benchmark_env(tmp_path)
    result = _run(
        SKILLS / "video" / "references" / "benchmark_overlay_encoders.sh",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    rows = (output_dir / "results.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "mode\trun\treal_seconds\tsize_bytes\tcodec"
    assert [row.split("\t")[:2] for row in rows[1:]] == [
        ["baseline", "1"],
        ["software-veryfast", "1"],
        ["twostage", "1"],
        ["baseline", "2"],
        ["software-veryfast", "2"],
        ["twostage", "2"],
    ]
    assert all(row.endswith("\th264") for row in rows[1:])
    assert "h264_videotoolbox-" not in result.stdout
    assert "h264_nvenc-" not in result.stdout
    assert "software-veryfast-2\t0.987654" in result.stdout
    assert "twostage-2\t0.987654" in result.stdout
    assert "-lavfi ssim -f null -" in calls.read_text(encoding="utf-8")


def test_overlay_benchmark_propagates_candidate_failure_without_complete_results(tmp_path: Path) -> None:
    env, output_dir, _calls = _overlay_benchmark_env(
        tmp_path,
        fail_pattern="software-veryfast-1.mp4",
    )
    result = _run(
        SKILLS / "video" / "references" / "benchmark_overlay_encoders.sh",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 31
    rows = (output_dir / "results.tsv").read_text(encoding="utf-8").splitlines()
    assert [row.split("\t")[0] for row in rows] == ["mode", "baseline"]
    assert "quality against baseline" not in result.stdout
