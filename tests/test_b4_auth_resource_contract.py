"""Issue #2307 の canonical auth resource と配布経路の契約テスト。"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_RELATIVE = Path("src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json")
TEMPLATE_NAME = "client_secrets.template.json"
LIVE_CREDENTIAL_NAMES = {
    "client_secrets.json",
    "token.json",
    "token.readonly.json",
}


def _canonical_bytes() -> bytes:
    return (ROOT / CANONICAL_RELATIVE).read_bytes()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(*args: str | Path, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _wheel_template(wheel: Path) -> tuple[list[str], bytes]:
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist() if name.endswith(TEMPLATE_NAME)]
        assert len(members) == 1
        return members, archive.read(members[0])


def _sdist_template(sdist: Path) -> tuple[list[str], bytes]:
    with tarfile.open(sdist) as archive:
        members = [member.name for member in archive.getmembers() if member.name.endswith(TEMPLATE_NAME)]
        assert len(members) == 1
        extracted = archive.extractfile(members[0])
        assert extracted is not None
        return members, extracted.read()


def _archive_has_live_credentials(archive_path: Path) -> list[str]:
    if archive_path.suffix == ".whl":
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(archive_path) as archive:
            names = [member.name for member in archive.getmembers()]
    return [name for name in names if Path(name).name in LIVE_CREDENTIAL_NAMES]


def test_canonical_template_is_the_only_source_and_has_no_root_copy() -> None:
    canonical = ROOT / CANONICAL_RELATIVE

    templates = sorted(
        path.relative_to(ROOT)
        for path in ROOT.rglob(TEMPLATE_NAME)
        if ".git" not in path.parts and ".takt" not in path.parts and ".venv" not in path.parts
    )

    assert canonical.is_file()
    assert templates == [CANONICAL_RELATIVE]
    channel_templates = (ROOT / "src/youtube_automation/cli/channel_init_templates.py").read_text(encoding="utf-8")
    assert "_render_auth_template" not in channel_templates


def test_channel_init_and_skills_sync_read_identical_canonical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical = _canonical_bytes()
    target = tmp_path / "channel"
    target.mkdir()
    monkeypatch.delenv("CHANNEL_DIR", raising=False)

    from youtube_automation.cli.channel_init import main as channel_init
    from youtube_automation.cli.skills_sync import main as skills_sync

    assert channel_init(["--target", str(target), "--short", "DEMO", "--name", "Demo Channel"]) == 0
    synced = tmp_path / "synced"
    synced.mkdir()
    assert skills_sync(["sync", "--asset", "auth-template", "--target", str(synced)]) == 0
    assert skills_sync(["diff", "--asset", "auth-template", "--target", str(synced)]) == 0

    channel_output = (target / "auth/client_secrets.template.json").read_bytes()
    sync_output = (synced / "auth/client_secrets.template.json").read_bytes()
    assert channel_output == canonical
    assert sync_output == canonical
    assert _digest(channel_output) == _digest(sync_output) == _digest(canonical)


def test_skills_sync_and_diff_resolve_existing_template_named_directory(
    tmp_path: Path,
) -> None:
    """A directory target is a parent even when its name matches the source file."""
    from youtube_automation.cli.skills_sync import main as skills_sync

    target = tmp_path / TEMPLATE_NAME
    target.mkdir()

    assert skills_sync(["sync", "--asset", "auth-template", "--target", str(target)]) == 0
    output = target / "auth/client_secrets.template.json"
    assert output.read_bytes() == _canonical_bytes()
    assert skills_sync(["diff", "--asset", "auth-template", "--target", str(target)]) == 0


def test_source_wheel_sdist_channel_init_and_installed_wheel_are_byte_identical(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    built = _run("uv", "build", "--out-dir", dist, cwd=ROOT)
    assert built.returncode == 0, built.stderr
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    wheel_members, wheel_bytes = _wheel_template(wheels[0])
    sdist_members, sdist_bytes = _sdist_template(sdists[0])
    assert wheel_members[0].startswith("youtube_automation/infrastructure/resources/auth/")
    assert sdist_members[0].endswith("/src/youtube_automation/infrastructure/resources/auth/" + TEMPLATE_NAME)
    assert _archive_has_live_credentials(wheels[0]) == []
    assert _archive_has_live_credentials(sdists[0]) == []

    venv = tmp_path / "venv"
    created = _run("uv", "venv", venv, cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    python = venv / "bin/python"
    installed = _run("uv", "pip", "install", "--python", python, wheels[0], cwd=tmp_path)
    assert installed.returncode == 0, installed.stderr
    downstream = tmp_path / "installed-downstream"
    downstream.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("UV_PROJECT", None)
    environment["VIRTUAL_ENV"] = str(venv)
    synced = _run(
        venv / "bin/yt-skills",
        "sync",
        "--asset",
        "auth-template",
        "--target",
        downstream,
        cwd=downstream,
        env=environment,
    )
    assert synced.returncode == 0, synced.stderr
    installed_bytes = (downstream / "auth/client_secrets.template.json").read_bytes()

    target = tmp_path / "channel-init"
    target.mkdir()
    from youtube_automation.cli.channel_init import main as channel_init

    assert channel_init(["--target", str(target), "--short", "DEMO", "--name", "Demo Channel"]) == 0
    channel_bytes = (target / "auth/client_secrets.template.json").read_bytes()
    all_bytes = [_canonical_bytes(), wheel_bytes, sdist_bytes, channel_bytes, installed_bytes]
    assert all(candidate == all_bytes[0] for candidate in all_bytes)
    assert {_digest(candidate) for candidate in all_bytes} == {_digest(all_bytes[0])}
