"""Terraform output から Vultr instance_id を解決する（Issue #110 / R4, R5）。

設計:
- `override` が非 None なら最優先で返す（CLI `--instance-id` 用）
- `override` が None なら `terraform output -raw instance_id` を `terraform_dir` で実行
- terraform バイナリ未検出 / コマンド失敗 / 空 stdout / 両 None は ConfigError (Fail Fast)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError

_TERRAFORM_TIMEOUT_SEC = 30


def resolve_instance_id(*, override: str | None, terraform_dir: Path | None) -> str:
    """Vultr instance_id を解決する。

    Args:
        override: CLI 引数等で直接指定された値。非 None なら最優先。
        terraform_dir: `terraform output` を実行する作業ディレクトリ。

    Returns:
        解決された instance_id (strip 済み)

    Raises:
        ConfigError: いずれの経路でも解決できなかった場合
    """
    if override is not None:
        return override

    if terraform_dir is None:
        raise ConfigError("instance_id を解決できません: --instance-id も terraform_dir も指定されていません")

    try:
        result = subprocess.run(
            ["terraform", "output", "-raw", "instance_id"],
            cwd=str(terraform_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=_TERRAFORM_TIMEOUT_SEC,
        )
    except FileNotFoundError as e:
        raise ConfigError(f"terraform バイナリが見つかりません: {e}") from e
    except subprocess.CalledProcessError as e:
        raise ConfigError(
            f"`terraform output -raw instance_id` が失敗しました (cwd={terraform_dir}): {e.stderr or e}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ConfigError(f"`terraform output` がタイムアウトしました: {e}") from e

    value = result.stdout.strip()
    if not value:
        raise ConfigError(f"`terraform output -raw instance_id` が空文字を返しました (cwd={terraform_dir})")
    return value
