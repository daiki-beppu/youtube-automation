"""アプリ層で秘密値を取得するヘルパー。

設計方針:
- 秘密はシェル環境変数や `.env` ファイルに常時存在させない
- 必要になった瞬間に Python プロセス内だけで取得する
- 取得経路は次の順で試行する
    1. 既に `os.environ` にあればそれを使う（OSS 利用者の `.env` / 既存 export 経由）
    2. `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` でなく、かつ `op` (1Password CLI)
       が利用可能なら `op read` で取得する
    3. どちらも失敗したら `ConfigError` を raise する
- 同一プロセス内で 2 回以上呼ばれた場合は `lru_cache` でメモ化する
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

# シークレット名 → 1Password の参照 URI
_SECRET_REFS: dict[str, str] = {
    "CLIENT_SECRETS_JSON": "op://Personal/YouTube_OAuth_Client_Secrets/credential",
    "OPENAI_API_KEY": "op://Personal/OpenAI_API_Key/credential",
    "YOUTUBE_STREAM_KEY": "op://Personal/YouTube/stream_key",
    "VULTR_API_KEY": "op://Personal/Vultr/api_key",
    "STREAM_WEBHOOK_URL": "op://Personal/Stream_Notification_Webhook/url",
    "DISCORD_WEBHOOK_URL": "op://Personal/YouTube_Stream_Discord_Webhook/url",
}

_OP_READ_TIMEOUT_SEC = 10
_OP_WRITE_TIMEOUT_SEC = 10
_OP_READ_DISABLED_ENV = "YOUTUBE_AUTOMATION_DISABLE_OP_READ"


def _is_op_read_disabled() -> bool:
    return os.environ.get(_OP_READ_DISABLED_ENV) == "1"


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
    if not _is_op_read_disabled() and shutil.which("op"):
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
                return value
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

    raise ConfigError(
        f"{name} を取得できませんでした。\n"
        f"  → .env に {name}=... を設定するか、\n"
        f"  → 1Password の {op_ref} に登録してください"
    )


_client_secrets_tempfile: Path | None = None


def get_client_secrets_path() -> Path:
    """client_secrets.json のパスを取得する。

    `get_secret("CLIENT_SECRETS_JSON")` で JSON 内容を取得し、一時ファイルに書き出して返す。
    `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` の場合、env が無ければ 1Password は読まない。
    同一プロセス内では同じ一時ファイルを再利用する。

    Returns:
        一時ファイルのパス

    Raises:
        ConfigError: 取得できなかった場合
    """
    global _client_secrets_tempfile
    if _client_secrets_tempfile and _client_secrets_tempfile.exists():
        return _client_secrets_tempfile

    json_content = get_secret("CLIENT_SECRETS_JSON")
    # mkstemp → chmod → fdopen の順序を厳守: 書き込み前に 0o600 を確定させ
    # OS umask に依存せず world-readable な状態を経由しないことを保証する
    fd, path = tempfile.mkstemp(prefix="client_secrets_", suffix=".json")
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json_content)

    def _cleanup(p: str = path) -> None:
        # idempotent: ファイルが既に消えていても atexit 連鎖を止めない
        if os.path.exists(p):
            os.unlink(p)

    atexit.register(_cleanup)
    _client_secrets_tempfile = Path(path)
    return _client_secrets_tempfile


def write_op_secret(vault: str, item: str, field: str, value: str) -> None:
    """1Password の指定 vault / item / field にシークレットを書き込む。

    既存 item があれば ``op item edit`` で field を更新し、無ければ
    ``op item create --category=password`` で新規作成にフォールバックする
    （初回 / 2 回目以降の両ケースを 1 関数で吸収する）。

    Args:
        vault: 1Password vault 名（例: ``"Personal"``）
        item:  item 名（例: ``"YouTube"``）
        field: field 名（例: ``"stream_key"``）
        value: 書き込む値

    Raises:
        ConfigError: ``op`` CLI が PATH 上に無い、または edit / create 双方が失敗した場合
    """
    op_path = shutil.which("op")
    if not op_path:
        raise ConfigError(
            "1Password CLI (op) が見つかりません。\n"
            "  → https://developer.1password.com/docs/cli/get-started/ からインストールするか、\n"
            "  → 既にインストール済みなら PATH を確認してください"
        )

    # 値は argv に埋め込まず stdin (`subprocess.run(input=value)`) で渡す。
    # argv に乗せると `ps aux` / `/proc/<pid>/cmdline` から同一ホスト他ユーザーが
    # secret を奪取できてしまう（Issue #151）。`[password]` 型指示子 + 末尾 `=`
    # の空値 assignment と `input=value` を組み合わせ、op CLI に stdin から値を渡す。
    assignment = f"{field}[password]="

    edit_cmd = ["op", "item", "edit", item, "--vault", vault, assignment]
    try:
        subprocess.run(
            edit_cmd,
            input=value,
            check=True,
            capture_output=True,
            text=True,
            timeout=_OP_WRITE_TIMEOUT_SEC,
        )
        return
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # item 不在ケース。create にフォールバックする
        pass

    create_cmd = [
        "op",
        "item",
        "create",
        "--category=password",
        "--vault",
        vault,
        "--title",
        item,
        assignment,
    ]
    try:
        subprocess.run(
            create_cmd,
            input=value,
            check=True,
            capture_output=True,
            text=True,
            timeout=_OP_WRITE_TIMEOUT_SEC,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise ConfigError(
            f"1Password への書き込みに失敗しました (vault={vault}, item={item}, field={field})。\n"
            f"  op item edit / create の両方が失敗しています。stderr: {stderr.strip()}"
        ) from exc


def reset_cache() -> None:
    """テスト用: lru_cache をクリアする。"""
    get_secret.cache_clear()
