"""プレイリスト割り当ての解決ロジック（API 非依存の純関数）。

``PlaylistManager`` と upload preflight の双方がここを共有する。preflight は
YouTube clients を持たないため、解決は必ず副作用の無い純関数として切り出す。

解決の優先順位 (#4346):

1. ``workflow-state.json::planning.playlists`` の明示指定があればそれを採用する。
   これが canonical。``[]`` は「auto_add 以外へは意図的に追加しない」の明示。
2. 明示指定が無い場合のみ、``auto_add_activities`` / ``auto_add_themes`` の
   レガシー照合へフォールバックする。

theme slug の部分一致（``auto_add_themes``）は、新しいテーマを作るたびに
キーワードが未登録となり、黙って ``auto_add`` プレイリストだけに入る事故を
構造的に生む。``check_playlist_assignment`` はその状態を issue として検出し、
呼び出し側が fail-loud できるようにする。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from youtube_automation.core.errors import ValidationError

__all__ = [
    "categorizing_playlist_keys",
    "check_playlist_assignment",
    "resolve_playlist_keys",
    "validate_playlist_keys",
]


def categorizing_playlist_keys(playlists_config: Mapping[str, Mapping[str, object]]) -> list[str]:
    """``auto_add`` ではない（＝テーマ分類用の）プレイリスト key を config 順で返す。"""
    return [key for key, pl in playlists_config.items() if not pl.get("auto_add")]


def _auto_add_keys(playlists_config: Mapping[str, Mapping[str, object]]) -> list[str]:
    return [key for key, pl in playlists_config.items() if pl.get("auto_add")]


def validate_playlist_keys(
    playlists_config: Mapping[str, Mapping[str, object]],
    keys: Sequence[str],
    *,
    source: str,
) -> None:
    """未知の playlist key を fail-loud で弾く。

    typo や config から消えた key を黙って無視すると「指定したのに入らない」
    という最も気付きにくい失敗になるため、必ず例外にする。
    """
    unknown = [key for key in keys if key not in playlists_config]
    if not unknown:
        return
    known = ", ".join(playlists_config) or "(なし)"
    raise ValidationError(
        f"❌ {source} に未知のプレイリスト key: {unknown}\n  config/channel/playlists.json に定義済みの key: {known}"
    )


def resolve_playlist_keys(
    playlists_config: Mapping[str, Mapping[str, object]],
    theme: str,
    *,
    activity: str,
    explicit: Sequence[str] | None,
) -> list[str]:
    """所属すべきプレイリスト key を config の定義順で返す。

    Args:
        playlists_config: ``config.playlists.items``
        theme: コレクションの theme slug
        activity: activity 文字列（``planning.activities`` または
            ``activity_for_theme`` の解決結果）。``explicit`` 指定時は未使用。
        explicit: ``planning.playlists`` の明示指定。``None`` は未決定、
            ``[]`` は「auto_add のみで良い」の明示。

    Raises:
        ValidationError: ``explicit`` に未知の key が含まれる場合。
    """
    if explicit is not None:
        validate_playlist_keys(playlists_config, explicit, source="workflow-state.json::planning.playlists")
        selected = set(explicit)
        # config の定義順を保つ（``all`` を先頭に置く運用が挿入位置に依存するため）。
        return [key for key in playlists_config if key in selected or playlists_config[key].get("auto_add")]

    theme_lower = theme.lower()
    # 中黒は従来形式、カンマは channel-new の生成形式として下流 config に存在する。
    activities = [a.strip() for a in activity.replace("·", ",").split(",")]
    matched: list[str] = []

    for key, pl in playlists_config.items():
        if pl.get("auto_add"):
            matched.append(key)
            continue

        activity_rules = pl.get("auto_add_activities") or []
        if any(a in activity_rules for a in activities):
            matched.append(key)
            continue

        theme_rules = pl.get("auto_add_themes") or []
        if any(theme_kw in theme_lower for theme_kw in theme_rules):
            matched.append(key)

    return matched


def check_playlist_assignment(
    playlists_config: Mapping[str, Mapping[str, object]],
    resolved: Sequence[str],
    *,
    theme: str,
    explicit: Sequence[str] | None,
) -> str | None:
    """分類プレイリストへ 1 つも割り当たっていなければ issue 文字列を返す。

    チャンネルが分類プレイリスト（``auto_add`` 以外）を 1 つも定義していない
    場合は対象外。``explicit`` が空配列で与えられている場合は operator が
    「auto_add のみ」を明示したものとして許容する。
    """
    categorizing = categorizing_playlist_keys(playlists_config)
    if not categorizing:
        return None
    if explicit == []:
        # 明示的な空配列だけが、operator が意図して auto_add のみを選んだ状態。
        return None
    resolved_categorizing = [key for key in resolved if key in categorizing]
    if not resolved_categorizing:
        auto_only = ", ".join(_auto_add_keys(playlists_config)) or "(なし)"
        return (
            f"theme={theme!r} がどの分類プレイリストにも割り当たっていません"
            f"（auto_add の {auto_only} のみ）。\n"
            f"    auto_add_themes のキーワード照合は新テーマで必ず漏れます。"
            f"割り当て先を明示してください:\n"
            f"      uv run yt-workflow-state set-planning playlists "
            f"'[\"{categorizing[0]}\"]'\n"
            f"    分類しないことが意図なら空配列を明示してください: "
            f"set-planning playlists '[]'"
        )

    missing_playlist_ids = [
        key
        for key in resolved_categorizing
        if not isinstance(playlists_config[key].get("playlist_id"), str)
        or not playlists_config[key]["playlist_id"].strip()
    ]
    if missing_playlist_ids:
        return (
            f"分類プレイリストの playlist_id 未設定: {', '.join(missing_playlist_ids)}。"
            "アップロード前に `uv run yt-playlist-manager --init` を実行してください"
        )
    return None
