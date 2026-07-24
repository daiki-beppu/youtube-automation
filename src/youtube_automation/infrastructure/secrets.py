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

import json
import os
import shutil
import subprocess
from functools import lru_cache

from youtube_automation.infrastructure.errors import ConfigError

# シークレット名 → 1Password の参照 URI
_SECRET_REFS: dict[str, str] = {
    "CLIENT_SECRETS_JSON": "op://Personal/YouTube_OAuth_Client_Secrets/credential",
    "OPENAI_API_KEY": "op://Personal/OpenAI_API_Key/credential",
    "GEMINI_API_KEY": "op://Personal/Gemini_API_Key/credential",
    "YOUTUBE_STREAM_KEY": "op://Personal/YouTube/stream_key",
    "VULTR_API_KEY": "op://Personal/Vultr/api_key",
    "STREAM_WEBHOOK_URL": "op://Personal/Stream_Notification_Webhook/url",
    "DISCORD_WEBHOOK_URL": "op://Personal/YouTube_Stream_Discord_Webhook/url",
}

_OP_READ_TIMEOUT_SEC = 10
_OP_WRITE_TIMEOUT_SEC = 10
_OP_READ_DISABLED_ENV = "YOUTUBE_AUTOMATION_DISABLE_OP_READ"
_OP_ITEM_NOT_FOUND_MARKERS = ("item not found", "isn't an item in")


def _is_op_read_disabled() -> bool:
    return os.environ.get(_OP_READ_DISABLED_ENV) == "1"


def _op_error_detail(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command timed out after {exc.timeout} seconds"
    return (exc.stderr or "").strip()


def _is_op_item_not_found(exc: subprocess.CalledProcessError) -> bool:
    stderr = (exc.stderr or "").lower()
    return any(marker in stderr for marker in _OP_ITEM_NOT_FOUND_MARKERS)


def _write_op_error(vault: str, item: str, field: str, operation: str, detail: str) -> ConfigError:
    return ConfigError(
        f"1Password への書き込みに失敗しました (vault={vault}, item={item}, field={field})。\n"
        f"  op item {operation} が失敗しました。stderr: {detail}"
    )


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


def get_client_secrets_config() -> dict[str, object]:
    """client_secrets の JSON 内容を in-memory dict で取得する。

    tempfile を経由しないため、異常終了時にも secret がディスクに残らない。

    Raises:
        ConfigError: 取得できない、または JSON object として解釈できない場合
    """
    raw = get_secret("CLIENT_SECRETS_JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"CLIENT_SECRETS_JSON を JSON として解釈できません: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("CLIENT_SECRETS_JSON は JSON object である必要があります")
    return data


def write_op_secret(vault: str, item: str, field: str, value: str) -> None:
    """1Password の指定 vault / item / field にシークレットを書き込む。

    既存 item があれば ``op item edit`` で field を更新し、無ければ
    PASSWORD item JSON を ``op item create`` に渡して新規作成する
    （初回 / 2 回目以降の両ケースを 1 関数で吸収する）。

    Args:
        vault: 1Password vault 名（例: ``"Personal"``）
        item:  item 名（例: ``"YouTube"``）
        field: field 名（例: ``"stream_key"``）
        value: 書き込む値

    Raises:
        ConfigError: ``op`` CLI が PATH 上に無い、または edit / create が失敗した場合
    """
    op_path = shutil.which("op")
    if not op_path:
        raise ConfigError(
            "1Password CLI (op) が見つかりません。\n"
            "  → https://developer.1password.com/docs/cli/get-started/ からインストールするか、\n"
            "  → 既にインストール済みなら PATH を確認してください"
        )

    edit_template = json.dumps({"fields": [{"id": field, "type": "CONCEALED", "value": value}]})

    edit_cmd = ["op", "item", "edit", item, "--vault", vault]
    try:
        subprocess.run(
            edit_cmd,
            input=edit_template,
            check=True,
            capture_output=True,
            text=True,
            timeout=_OP_WRITE_TIMEOUT_SEC,
        )
        return
    except subprocess.CalledProcessError as exc:
        if not _is_op_item_not_found(exc):
            raise _write_op_error(vault, item, field, "edit", _op_error_detail(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise _write_op_error(vault, item, field, "edit", _op_error_detail(exc)) from exc

    create_fields = [{"id": "password", "type": "CONCEALED", "purpose": "PASSWORD", "value": value}]
    if field != "password":
        create_fields.append({"id": field, "type": "CONCEALED", "value": value})
    create_template = json.dumps({"category": "PASSWORD", "title": item, "fields": create_fields})
    create_cmd = [
        "op",
        "item",
        "create",
        "--vault",
        vault,
        "-",
    ]
    try:
        subprocess.run(
            create_cmd,
            input=create_template,
            check=True,
            capture_output=True,
            text=True,
            timeout=_OP_WRITE_TIMEOUT_SEC,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise _write_op_error(vault, item, field, "create", _op_error_detail(exc)) from exc


def reset_cache() -> None:
    """テスト用: lru_cache をクリアする。"""
    get_secret.cache_clear()
