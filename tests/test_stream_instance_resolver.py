"""utils/streaming/instance_resolver.py のユニットテスト。

要件 R4/R5: `instance_id` を Terraform output から取得。`--instance-id` 直接指定もサポート。

設計:
- `resolve_instance_id(override, terraform_dir)` は境界で全解決する関数
- override が非 None なら最優先で返す
- override が None なら `terraform output -raw instance_id` を terraform_dir で実行
- terraform バイナリ未検出 / コマンド失敗時は ConfigError
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.streaming import instance_resolver


def test_override_takes_precedence_over_terraform():
    """Given override="VULTR_123"
    When resolve_instance_id を呼ぶ
    Then terraform を呼ばず override をそのまま返す。
    """
    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run") as mock_run:
        got = instance_resolver.resolve_instance_id(override="VULTR_123", terraform_dir=Path("/nowhere"))
    assert got == "VULTR_123"
    mock_run.assert_not_called()


def test_resolve_runs_terraform_output_in_terraform_dir(tmp_path: Path):
    """Given override=None, terraform_dir 指定
    When resolve_instance_id を呼ぶ
    Then `terraform output -raw instance_id` が cwd=terraform_dir で実行される。
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(stdout="VULTR_FROM_TF\n", returncode=0)

    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run", side_effect=fake_run):
        got = instance_resolver.resolve_instance_id(override=None, terraform_dir=tmp_path)

    assert got == "VULTR_FROM_TF"
    assert captured["cmd"][:3] == ["terraform", "output", "-raw"]
    assert "instance_id" in captured["cmd"]
    assert str(captured["cwd"]) == str(tmp_path)


def test_resolve_strips_whitespace_from_terraform_output(tmp_path: Path):
    """Given terraform output に末尾改行が含まれる
    When resolve_instance_id を呼ぶ
    Then strip() された値が返る。
    """

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="  VULTR_TRIM  \n", returncode=0)

    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run", side_effect=fake_run):
        got = instance_resolver.resolve_instance_id(override=None, terraform_dir=tmp_path)
    assert got == "VULTR_TRIM"


def test_resolve_raises_config_error_when_terraform_missing(tmp_path: Path):
    """Given terraform バイナリが PATH に無い
    When resolve_instance_id を呼ぶ
    Then ConfigError (フォールバックで空文字を返さない)。
    """

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("terraform: command not found")

    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run", side_effect=fake_run):
        with pytest.raises(ConfigError):
            instance_resolver.resolve_instance_id(override=None, terraform_dir=tmp_path)


def test_resolve_raises_config_error_when_terraform_fails(tmp_path: Path):
    """Given `terraform output` が exit code 非 0
    When resolve_instance_id を呼ぶ
    Then ConfigError。
    """

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="No outputs found")

    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run", side_effect=fake_run):
        with pytest.raises(ConfigError):
            instance_resolver.resolve_instance_id(override=None, terraform_dir=tmp_path)


def test_resolve_raises_config_error_when_output_empty(tmp_path: Path):
    """Given terraform output が空文字
    When resolve_instance_id を呼ぶ
    Then ConfigError (空でも instance_id として返さない、Fail Fast)。
    """

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="\n", returncode=0)

    with patch("youtube_automation.utils.streaming.instance_resolver.subprocess.run", side_effect=fake_run):
        with pytest.raises(ConfigError):
            instance_resolver.resolve_instance_id(override=None, terraform_dir=tmp_path)


def test_resolve_raises_when_neither_override_nor_terraform_dir():
    """Given override=None かつ terraform_dir=None
    When resolve_instance_id を呼ぶ
    Then ConfigError (どこからも引けないため)。
    """
    with pytest.raises(ConfigError):
        instance_resolver.resolve_instance_id(override=None, terraform_dir=None)
