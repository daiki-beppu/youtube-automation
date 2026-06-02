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

from youtube_automation.utils.exceptions import ConfigError, YouTubeAPIError

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


# ---------------------------------------------------------------------------
# Locale code normalization (#562)
# ---------------------------------------------------------------------------
#
# YouTube Data API は `localizations` のキーと `brandingSettings.channel.defaultLanguage`
# に **アンダースコア区切りの BCP-47**（例: `ja_JP`）を内部正規形として使う。
#
# 入力側（ローカル config）はユーザーが下記いずれの形式で書いてもよい:
#   - 短縮形 `ja` / `en` / `de` （`config-generation-rules.md` 推奨形式）
#   - BCP-47 ハイフン `ja-JP` / `en-US`
#   - YouTube 内部形 `ja_JP` / `en_US`
#
# 部分失敗の原因（issue #562）:
#   ローカル `["ja", "en", "de"]` をそのまま投げると、YouTube 側は
#   `brandingSettings.defaultLanguage` と一致するもの（例: `en`）だけを受理して
#   `en_US` に正規化し、それ以外の `ja` / `de` を silent skip する。
#
# 解決方針:
#   - 送信時（build_update_body）は短縮 / ハイフン / アンダースコアのいずれを受け取っても
#     API 形式 `xx_YY` に正規化して送る
#   - 受信時（parse_api_response）はローカル persistence 用に短縮形 `xx` へ戻す
#     （`config-generation-rules.md` の推奨形式を維持し、pull 後にファイルが
#      `ja_JP` に書き換わって diff レビューで noisy になるのを避ける）
#   - 差分比較（diff_settings）は両側を同一形式に正規化してから比較する
#     → これにより local `ja` ↔ remote `ja_JP` の永続 diff が消える
#
# マッピングは「短縮 → 内部形」だけを定義し、内部形 → 短縮は逆引きで生成する。
# 同一 short が複数の region に分かれる言語（`pt` / `zh` 系）は明示的に列挙する。

_LOCALE_SHORT_TO_API: dict[str, str] = {
    "ja": "ja_JP",
    "en": "en_US",
    "de": "de_DE",
    "fr": "fr_FR",
    "es": "es_ES",
    "es-419": "es_419",
    "it": "it_IT",
    "ko": "ko_KR",
    "ru": "ru_RU",
    "nl": "nl_NL",
    "pl": "pl_PL",
    "tr": "tr_TR",
    "id": "id_ID",
    "th": "th_TH",
    "vi": "vi_VN",
    "hi": "hi_IN",
    "ar": "ar_SA",
    "pt": "pt_PT",
    "pt-BR": "pt_BR",
    "zh": "zh_CN",
    "zh-CN": "zh_CN",
    "zh-TW": "zh_TW",
    "zh-HK": "zh_HK",
}

# 逆引きは「最も短い region 由来の short」を優先（`pt_PT` → `pt`, `zh_CN` → `zh`）。
_LOCALE_API_TO_SHORT: dict[str, str] = {api: short for short, api in _LOCALE_SHORT_TO_API.items() if "-" not in short}


def _canonical_input(code: str) -> str:
    """ユーザー入力を `xx[-YY]` のハイフン形に正規化する内部ヘルパ。"""
    return code.replace("_", "-")


def normalize_locale_to_api(code: str) -> str:
    """ロケールコードを YouTube API 内部形式 `xx_YY` に正規化する。

    受理する形式:
        - 短縮 BCP-47: `ja` / `en` / `de`（マッピング表で region を補完）
        - BCP-47 ハイフン: `ja-JP` / `en-US`（`_` に置換するだけ）
        - YouTube 内部形: `ja_JP` / `en_US`（そのまま）

    未知のコードはハイフンをアンダースコアに変換するだけのベストエフォートで返す
    （unknown locale を強制的に reject すると YouTube が将来追加した言語で詰まるため）。

    Args:
        code: 任意形式のロケールコード（None / 空文字は呼び出し側でガードすること）

    Returns:
        YouTube API 送信用の `xx_YY` 形式文字列
    """
    if not code:
        return code
    canonical = _canonical_input(code)
    # 短縮 → 内部形（短縮そのものか、`xx-YY` を `xx` 扱いで lookup）
    if canonical in _LOCALE_SHORT_TO_API:
        return _LOCALE_SHORT_TO_API[canonical]
    # `xx-YY` 形式は `_` 置換した内部形が YouTube の受理する形（issue 発生事例参照）
    if "-" in canonical:
        return canonical.replace("-", "_")
    # 既に `xx_YY` 形式（input が `xx_YY` だった場合は canonical で `xx-YY` 化済み）
    return code


def normalize_locale_to_short(code: str) -> str:
    """ロケールコードを短縮形 `xx`（または region 必須なら `xx-YY`）に正規化する。

    `parse_api_response` で YouTube から返ってきた `xx_YY` をローカル persistence 用に
    縮める。マッピング表に無いコードはハイフン形にしてそのまま返す（破壊しない）。

    Args:
        code: 任意形式のロケールコード

    Returns:
        ローカル config 用の短縮形（`ja_JP` → `ja`, `pt_BR` → `pt-BR`）
    """
    if not code:
        return code
    canonical = _canonical_input(code).replace("-", "_")
    if canonical in _LOCALE_API_TO_SHORT:
        return _LOCALE_API_TO_SHORT[canonical]
    # マッピング外: 元の表記がアンダースコアならハイフンに揃え、そうでなければそのまま
    if "_" in code:
        return code.replace("_", "-")
    return code


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
        elif local_key == "default_language" and value:
            # YouTube は localizations 側と整合する `xx_YY` 形式を内部正規形として扱う
            # (#562)。ハイフン形 `ja-JP` も accept されるが pull 後に永続 diff が出るため
            # 統一して `_` 形式で送る。
            value = normalize_locale_to_api(value)
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
            # 入力 `ja` / `ja-JP` / `ja_JP` をすべて `ja_JP` に正規化して送信する (#562)。
            # 正規化しないと、ローカル `["ja", "en", "de"]` を送ると defaultLanguage と
            # 一致する `en` だけが受理されて `ja` / `de` が silent skip される。
            api_lang = normalize_locale_to_api(lang)
            loc_body[api_lang] = {}
            if title is not None:
                loc_body[api_lang]["title"] = title
            if description is not None:
                loc_body[api_lang]["description"] = description
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
        elif local_key == "default_language" and value:
            # YouTube から `ja_JP` で返ってきても、ローカル persistence は短縮形 `ja` で
            # 維持する (#562 / config-generation-rules.md は `["ja", "en", "de"]` 推奨)。
            value = normalize_locale_to_short(value)
        youtube_channel[local_key] = value

    status = resp.get("status") or {}
    if "selfDeclaredMadeForKids" in status:
        youtube_channel["made_for_kids"] = bool(status["selfDeclaredMadeForKids"])

    raw_loc = resp.get("localizations") or {}
    localizations: dict[str, Any] = {}
    if raw_loc:
        # 同様に `ja_JP` → `ja` へ縮める。push で `_` 形式に正規化しているため、
        # 縮めて persist しても次の diff は 0 になる（diff_settings 側も同じ
        # normalizer を通す）。重複キーを避けるため short → entry の dict にマージする。
        normalized: dict[str, Any] = {}
        for lang, entry in raw_loc.items():
            short = normalize_locale_to_short(lang)
            normalized[short] = entry or {}
        langs = sorted(normalized.keys())
        localizations["supported_languages"] = langs
        for lang in langs:
            entry = normalized[lang]
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
        if local_key == "default_language":
            # 表記揺れ（`ja` / `ja-JP` / `ja_JP`）を吸収してから比較する (#562)。
            # 例: local `ja` ↔ remote `ja_JP` は実質同一なので diff にしない。
            if normalize_locale_to_short(l_val or "") == normalize_locale_to_short(r_val or ""):
                continue
        else:
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

    # localizations のキー揺れ（`ja` ↔ `ja_JP` ↔ `ja-JP`）も吸収する (#562)。
    # 両側を短縮形に寄せた dict を作って同じキーで突き合わせる。
    l_loc_norm = _normalize_localizations_for_diff(local_localizations)
    r_loc_norm = _normalize_localizations_for_diff(remote_localizations)
    all_langs = sorted(set(l_loc_norm.keys()) | set(r_loc_norm.keys()))
    for lang in all_langs:
        l_entry = l_loc_norm.get(lang) or {}
        r_entry = r_loc_norm.get(lang) or {}
        for field in ("title", "description"):
            l_val = l_entry.get(field)
            r_val = r_entry.get(field)
            if l_val == r_val:
                continue
            lines.append(f"  localizations.{lang}.{field}:")
            lines.append(f"    - (remote) {_fmt(r_val)}")
            lines.append(f"    + (local)  {_fmt(l_val)}")

    return lines


def _normalize_localizations_for_diff(loc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """diff 比較用に localizations dict をキー正規化する (#562)。

    `supported_languages` を除く各 lang エントリを `{short: entry}` 形式に寄せる。
    """
    out: dict[str, dict[str, Any]] = {}
    supported = loc.get("supported_languages") or []
    for lang in supported:
        entry = loc.get(lang)
        if isinstance(entry, dict):
            out[normalize_locale_to_short(lang)] = entry
    # supported_languages 未宣言だが lang エントリだけある（pull 後など）も拾う
    for key, value in loc.items():
        if key == "supported_languages":
            continue
        if not isinstance(value, dict):
            continue
        short = normalize_locale_to_short(key)
        out.setdefault(short, value)
    return out


def _fmt(value: Any) -> str:
    if value is None:
        return "<unset>"
    if isinstance(value, str):
        if "\n" in value:
            preview = value.split("\n", 1)[0]
            return f"{preview!r} … ({len(value)} chars, {value.count(chr(10)) + 1} lines)"
        return repr(value)
    return repr(value)


# combined fetch では `localizations` を要求しない。`brandingSettings` 等と同じ
# `channels.list` 呼び出しに `localizations` を混ぜると、push 直後に旧版が返る
# YouTube Data API のキャッシュ層に当たる（#564）。`localizations` だけを単独
# part で取り直すと push 反映済みの新版が安定して返るため、二段 fetch する。
_COMBINED_PARTS = "brandingSettings,status,snippet"
_LOCALIZATIONS_PART = "localizations"


def fetch_channel(youtube) -> dict[str, Any]:
    """`channels().list(mine=True, part=...)` の薄いラッパ。

    `localizations` は combined fetch のキャッシュ層を避けるため単独 part で
    取得し直し、combined fetch の結果へマージする（#564）。

    Raises:
        YouTubeAPIError: チャンネルが取得できない / レスポンスが空
    """
    try:
        resp = youtube.channels().list(part=_COMBINED_PARTS, mine=True).execute()
    except Exception as e:
        raise YouTubeAPIError(f"channels().list() failed: {e}") from e

    items = resp.get("items") or []
    if not items:
        raise YouTubeAPIError("authenticated user has no YouTube channel")
    item = items[0]

    item["localizations"] = _fetch_localizations(youtube)
    return item


def _fetch_localizations(youtube) -> dict[str, Any]:
    """`localizations` だけを単独 part で取得する（push 直後のキャッシュ回避, #564）。

    Returns:
        `localizations` 辞書（チャンネルに localizations が無ければ空辞書）
    """
    try:
        resp = youtube.channels().list(part=_LOCALIZATIONS_PART, mine=True).execute()
    except Exception as e:
        raise YouTubeAPIError(f"channels().list(part={_LOCALIZATIONS_PART}) failed: {e}") from e

    items = resp.get("items") or []
    if not items:
        return {}
    return items[0].get("localizations") or {}


def verify_channel_id(expected_channel_id: str | None, remote_channel_id: str) -> None:
    """ローカル config の channel_id と認証済みチャンネルの id が一致するか検証する (#561)。

    `auth/token.json` が別チャンネルの OAuth トークンのまま push すると、意図しない
    チャンネルの設定を上書きしてしまう。`config/channel/meta.json` の
    `channel.channel_id` と `channels().list(mine=True).id` を照合し、不一致なら
    取り違え事故として push を拒否する。

    Args:
        expected_channel_id: ローカル config の `channel.channel_id`。未設定（None /
            空文字）ならチェックをスキップする（後方互換）。
        remote_channel_id: 認証済みチャンネルの id（`channels().list` の結果）。

    Raises:
        ConfigError: channel_id が設定済みかつ remote と一致しない場合。
    """
    if not expected_channel_id:
        return
    if expected_channel_id != remote_channel_id:
        raise ConfigError(
            "channel_id mismatch: ローカル config と認証済みチャンネルが一致しません。\n"
            f"  config/channel/meta.json (channel.channel_id): {expected_channel_id}\n"
            f"  authenticated channel (channels().list mine=True): {remote_channel_id}\n"
            "→ 別チャンネルの OAuth トークンで設定を上書きする事故を防ぐため push を中止しました。\n"
            "  対処1: auth/token.json を削除して再認証し、対象チャンネルを選び直す（yt-channel-status）\n"
            "  対処2: meta.json の channel.channel_id を正しい値に修正する"
        )
