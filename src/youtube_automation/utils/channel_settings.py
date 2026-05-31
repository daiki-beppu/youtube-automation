"""YouTube チャンネル設定 (brandingSettings / localizations / status) の同期ロジック。

双方向 CLI (`yt-channel-settings`) から使われるドメイン層。HTTP 呼び出し以外は
純粋関数として実装し、テストでモック不要にしている。

ローカル側スキーマ:

    config/channel/meta.json:
        youtube_channel:
          description: str                    # ブランディング説明文
          keywords: list[str]                 # タグ (API 側ではスペース区切り)
          country: str                        # ISO 3166-1 alpha-2
          default_language: str               # BCP-47
          unsubscribed_trailer: str           # videoId
          made_for_kids: bool

    localizations.json:
        supported_languages: [ja, en, ...]
        {lang}:
          title: str
          description: str

YouTube API 側スキーマ (`channels().update(part='brandingSettings,localizations,status')`):

    brandingSettings.channel.{description, keywords, country, defaultLanguage, unsubscribedTrailer}
    localizations.{lang}.{title, description}
    status.selfDeclaredMadeForKids
"""

from __future__ import annotations

import logging
import shlex
from typing import Any

from youtube_automation.utils.exceptions import YouTubeAPIError

logger = logging.getLogger(__name__)

_FIELD_MAP: dict[str, str] = {
    "description": "description",
    "keywords": "keywords",
    "country": "country",
    "default_language": "defaultLanguage",
    "unsubscribed_trailer": "unsubscribedTrailer",
}

# YouTube Data API の brandingSettings.channel.keywords は合計 500 文字までに制限される。
# 超過すると channels().update() が 400 (`Request contains an invalid argument.`) を返すが、
# 原因が keywords 長だとは判別できないため push 前にこの定数で事前検証する (#563)。
KEYWORDS_MAX_LENGTH = 500


def build_upload_status_flags(youtube_api: Any) -> dict[str, bool]:
    """動画アップロード時の `status` 用 AI 開示・子供向け申告フラグを解決する。

    `config.youtube.api` の `contains_synthetic_media` / `self_declared_made_for_kids`
    を YouTube `videos.insert` の `status` キーへマッピングする。未設定時のデフォルトは
    dataclass 側で現行の振る舞い（synthetic=True / made_for_kids=False）に固定されている。

    Args:
        youtube_api: `config.youtube.api`（`YoutubeApi` dataclass）

    Returns:
        `{"selfDeclaredMadeForKids": bool, "containsSyntheticMedia": bool}`
    """
    return {
        "selfDeclaredMadeForKids": bool(youtube_api.self_declared_made_for_kids),
        "containsSyntheticMedia": bool(youtube_api.contains_synthetic_media),
    }


def _keywords_to_api(keywords: list[str]) -> str:
    """['bgm', 'lo fi beats'] → 'bgm "lo fi beats"' (YouTube 仕様のスペース区切り)。"""
    return " ".join(shlex.quote(k) if " " in k else k for k in keywords)


def _validate_keywords_length(api_keywords: str, keywords: list[str]) -> None:
    """API 形式 keywords の合計長が 500 文字制限内かを検証する (#563)。

    超過時は YouTube に push する前に `YouTubeAPIError` で止め、短縮候補として
    長い順に上位タグを提示する。400 応答待ちより原因が即座に分かる。

    Args:
        api_keywords: `_keywords_to_api()` が返す API 送信形式の文字列
        keywords: 元のタグリスト（短縮ヒント生成用）

    Raises:
        YouTubeAPIError: api_keywords が `KEYWORDS_MAX_LENGTH` を超える場合
    """
    length = len(api_keywords)
    if length <= KEYWORDS_MAX_LENGTH:
        return
    longest = sorted(keywords, key=len, reverse=True)[:3]
    hint = ", ".join(repr(k) for k in longest)
    raise YouTubeAPIError(
        f"keywords exceeds {KEYWORDS_MAX_LENGTH} chars "
        f"(got {length}, over by {length - KEYWORDS_MAX_LENGTH}). "
        f"remove some tags to fit. longest tags: {hint}. "
        f"current: {api_keywords!r}"
    )


def _keywords_from_api(raw: str) -> list[str]:
    """YouTube の keywords 文字列 → リスト。空白区切り + quote 対応。"""
    if not raw:
        return []
    return shlex.split(raw)


def build_update_body(
    local: dict[str, Any],
    localizations: dict[str, Any] | None,
    channel_id: str,
) -> dict[str, Any]:
    """ローカル設定から channels().update() 用のリクエストボディを組み立てる。

    未定義キーはリクエストから除外し、YouTube 側の値を破壊しない。

    Args:
        local: config/channel/meta.json の youtube_channel セクション
        localizations: localizations.json 全体（None なら同期しない）
        channel_id: 対象チャンネル ID

    Returns:
        channels().update() に渡す body 辞書
    """
    body: dict[str, Any] = {"id": channel_id}

    branding: dict[str, Any] = {}
    for local_key, api_key in _FIELD_MAP.items():
        if local_key not in local:
            continue
        value = local[local_key]
        if local_key == "keywords":
            keywords_list = list(value)
            value = _keywords_to_api(keywords_list)
            _validate_keywords_length(value, keywords_list)
        branding[api_key] = value
    if branding:
        body["brandingSettings"] = {"channel": branding}

    if localizations:
        loc_body: dict[str, dict[str, str]] = {}
        for lang in localizations.get("supported_languages", []):
            entry = localizations.get(lang)
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            description = entry.get("description")
            if title is None and description is None:
                continue
            loc_body[lang] = {}
            if title is not None:
                loc_body[lang]["title"] = title
            if description is not None:
                loc_body[lang]["description"] = description
        if loc_body:
            body["localizations"] = loc_body

    if "made_for_kids" in local:
        body["status"] = {"selfDeclaredMadeForKids": bool(local["made_for_kids"])}

    return body


def parse_api_response(resp: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """channels().list() レスポンスをローカル config 形式に変換する。

    Returns:
        (youtube_channel セクション, localizations.json 全体) のタプル
    """
    branding = (resp.get("brandingSettings") or {}).get("channel") or {}
    youtube_channel: dict[str, Any] = {}
    for local_key, api_key in _FIELD_MAP.items():
        if api_key not in branding:
            continue
        value = branding[api_key]
        if local_key == "keywords":
            value = _keywords_from_api(value)
        youtube_channel[local_key] = value

    status = resp.get("status") or {}
    if "selfDeclaredMadeForKids" in status:
        youtube_channel["made_for_kids"] = bool(status["selfDeclaredMadeForKids"])

    raw_loc = resp.get("localizations") or {}
    localizations: dict[str, Any] = {}
    if raw_loc:
        langs = sorted(raw_loc.keys())
        localizations["supported_languages"] = langs
        for lang in langs:
            entry = raw_loc[lang] or {}
            localizations[lang] = {
                "title": entry.get("title", ""),
                "description": entry.get("description", ""),
            }

    return youtube_channel, localizations


def diff_settings(
    local_channel: dict[str, Any],
    local_localizations: dict[str, Any],
    remote_channel: dict[str, Any],
    remote_localizations: dict[str, Any],
) -> list[str]:
    """ローカルとリモートの差分を人間可読な行リストで返す。

    `local → remote` の視点（push 前提）。逆向きは呼び出し側で引数を入れ替える。
    """
    lines: list[str] = []

    for local_key in _FIELD_MAP.keys():
        if local_key not in local_channel and local_key not in remote_channel:
            continue
        l_val = local_channel.get(local_key)
        r_val = remote_channel.get(local_key)
        if l_val == r_val:
            continue
        lines.append(f"  {local_key}:")
        lines.append(f"    - (remote) {_fmt(r_val)}")
        lines.append(f"    + (local)  {_fmt(l_val)}")

    if "made_for_kids" in local_channel or "made_for_kids" in remote_channel:
        l_val = local_channel.get("made_for_kids")
        r_val = remote_channel.get("made_for_kids")
        if l_val != r_val:
            lines.append("  made_for_kids:")
            lines.append(f"    - (remote) {_fmt(r_val)}")
            lines.append(f"    + (local)  {_fmt(l_val)}")

    l_langs = set(local_localizations.get("supported_languages", []))
    r_langs = set(remote_localizations.get("supported_languages", []))
    all_langs = sorted(l_langs | r_langs)
    for lang in all_langs:
        l_entry = local_localizations.get(lang) or {}
        r_entry = remote_localizations.get(lang) or {}
        for field in ("title", "description"):
            l_val = l_entry.get(field)
            r_val = r_entry.get(field)
            if l_val == r_val:
                continue
            lines.append(f"  localizations.{lang}.{field}:")
            lines.append(f"    - (remote) {_fmt(r_val)}")
            lines.append(f"    + (local)  {_fmt(l_val)}")

    return lines


def _fmt(value: Any) -> str:
    if value is None:
        return "<unset>"
    if isinstance(value, str):
        if "\n" in value:
            preview = value.split("\n", 1)[0]
            return f"{preview!r} … ({len(value)} chars, {value.count(chr(10)) + 1} lines)"
        return repr(value)
    return repr(value)


def fetch_channel(youtube) -> dict[str, Any]:
    """`channels().list(mine=True, part=...)` の薄いラッパ。

    Raises:
        YouTubeAPIError: チャンネルが取得できない / レスポンスが空
    """
    try:
        resp = youtube.channels().list(part="brandingSettings,localizations,status,snippet", mine=True).execute()
    except Exception as e:
        raise YouTubeAPIError(f"channels().list() failed: {e}") from e

    items = resp.get("items") or []
    if not items:
        raise YouTubeAPIError("authenticated user has no YouTube channel")
    return items[0]
