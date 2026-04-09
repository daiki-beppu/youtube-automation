"""アプリ層で秘密値を取得するヘルパー。

設計方針:
- 秘密はシェル環境変数や `.env` ファイルに常時存在させない
- 必要になった瞬間に Python プロセス内だけで取得する
- 取得経路は次の順で試行する
    1. 既に `os.environ` にあればそれを使う（OSS 利用者の `.env` / 既存 export 経由）
    2. `op` (1Password CLI) が利用可能なら `op read` で取得する
    3. どちらも失敗したら `ConfigError` を raise する
- 同一プロセス内で 2 回以上呼ばれた場合は `lru_cache` でメモ化する
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache

from utils.exceptions import ConfigError

# シークレット名 → 1Password の参照 URI
_SECRET_REFS: dict[str, str] = {
    "GEMINI_API_KEY": "op://Personal/GEMINI_API_KEY/credential",
}

_OP_READ_TIMEOUT_SEC = 10


@lru_cache(maxsize=None)
def get_secret(name: str) -> str:
    """指定した名前のシークレットを取得する。

    Args:
        name: `_SECRET_REFS` に登録されたシークレット名

    Returns:
        取得した値

    Raises:
        ConfigError: 未登録の名前が渡された、または全ての取得経路で失敗した場合
    """
    if name not in _SECRET_REFS:
        raise ConfigError(f"未登録のシークレット名: {name}")

    env_value = os.environ.get(name)
    if env_value:
        return env_value

    op_ref = _SECRET_REFS[name]
    if shutil.which("op"):
        try:
            result = subprocess.run(
                ["op", "read", op_ref],
                check=True,
                capture_output=True,
                text=True,
                timeout=_OP_READ_TIMEOUT_SEC,
            )
            value = result.stdout.strip()
            if value:
                # SDK ライブラリが暗黙に os.environ を参照するケースに備えて
                # プロセス内の環境変数にもセットしておく（プロセス終了で消える）
                os.environ[name] = value
                return value
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

    raise ConfigError(
        f"{name} を取得できませんでした。\n"
        f"  → .env に {name}=... を設定するか、\n"
        f"  → 1Password の {op_ref} に登録してください"
    )


def get_gemini_api_key() -> str:
    """Google Gemini API キーを取得する。"""
    return get_secret("GEMINI_API_KEY")


def reset_cache() -> None:
    """テスト用: lru_cache をクリアする。"""
    get_secret.cache_clear()
