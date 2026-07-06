"""Remote metadata and lockfile readers for `yt-automation-update`."""

from __future__ import annotations

import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from youtube_automation.cli.automation_update_refs import PACKAGE_NAME, UPSTREAM_REPO, _canonicalize_name
from youtube_automation.utils.exceptions import ConfigError


def _github_api_get(path: str) -> dict:
    url = f"https://api.github.com/{path}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "yt-automation-update"},
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ConfigError(f"GitHub API の呼び出しに失敗しました ({url}): {e}")


def _fetch_latest_release_tag() -> str:
    release = _github_api_get(f"repos/{UPSTREAM_REPO}/releases/latest")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise ConfigError("upstream 最新リリースの tag_name を取得できません")
    return tag


def _fetch_branch_head_sha(branch: str) -> str:
    commit = _github_api_get(f"repos/{UPSTREAM_REPO}/commits/{branch}")
    sha = commit.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ConfigError(f"upstream {branch} の HEAD sha を取得できません")
    return sha


def _locked_git_sha(root: Path) -> str | None:
    """uv.lock から youtube-channels-automation の解決済み git sha を取り出す."""
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        return None
    try:
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"uv.lock を読み込めません: {lock_path}: {e}")
    packages = lock.get("package")
    if not isinstance(packages, list):
        return None
    for package in packages:
        if not isinstance(package, dict):
            continue
        if _canonicalize_name(str(package.get("name", ""))) != PACKAGE_NAME:
            continue
        source = package.get("source")
        git = source.get("git") if isinstance(source, dict) else None
        if isinstance(git, str) and "#" in git:
            return git.rsplit("#", 1)[1]
    return None
