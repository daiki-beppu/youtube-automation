"""yt-collection-serve の Suno playlist capture endpoint (POST /suno/playlists) のテスト (#893).

channel-agnostic な「Suno UI のプレイリスト一覧を下流チャンネルの
`config/suno-playlists.json` へ atomic merge write する」機能の契約を pin する。

契約（draft が実装すべき public API。SSOT は order.md 要件 1-5 / plan §2-A）:

- `normalize_suno_title(title: str, prefix: str) -> str | None`
    `<prefix> | <theme>` を `<prefix>-<theme-slug>` に正規化する純関数。
    prefix 一致時のみ slug を返し、不一致は None。大小無視・連続空白の `-` 畳み込み。
- `write_suno_playlists(root: Path, payload: list[dict], *, prefix: str) -> int`
    `<root>/config/suno-playlists.json` へ atomic merge write（tempfile→os.replace）。
    prefix 不一致 item は skip、同 slug は後勝ちで上書き、破損 JSON は再作成。書込件数を返す。
- `read_mapped_slugs(root: Path) -> set[str]`
    既存 `config/suno-playlists.json` の slug 集合。不在・破損は空集合。
- `derive_collection_slug(collection_id: str, prefix: str) -> str | None`
    collection dir 名から `<prefix>-<theme-slug>` を導出する。normalize_suno_title と
    同じ slug 形を生成し、マージキーとして突合可能（不変条件）。
- `build_collections_index(root, *, mapped_slugs=..., prefix=...)`
    各 entry に `mapped: bool`（derive_collection_slug(id) in mapped_slugs）を含める。
    prefix 未指定は全件 mapped=False（後方互換）。
- `create_server(..., playlist_capture: tuple[Path, str] | None=None)`
    playlist_capture 指定時のみ POST `/suno/playlists` を有効化する。
- POST `/suno/playlists`: 200（許可 Origin）/ 403（Origin 未設定・不許可）/
    404（playlist_capture 未設定・別パス）/ 400（body が JSON list でない）。
- `OPTIONS` の `Access-Control-Allow-Methods` に `POST` を含む。
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from youtube_automation.scripts.collection_serve import (
    _resolve_playlist_capture,
    build_collections_index,
    create_server,
    derive_collection_slug,
    derive_playlist_name,
    normalize_suno_title,
    read_mapped_slugs,
    write_suno_playlists,
)
from youtube_automation.utils.exceptions import ConfigError

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

# 外部 HTTP 契約: 拡張が POST する Suno playlist capture サブパス（リテラルで pin する）。
# SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PLAYLISTS_ROUTE /
#       extensions/shared/constants.ts PLAYLISTS_CAPTURE_ROUTE。
_SUNO_PLAYLISTS_ROUTE = "/suno/playlists"

# 出力先 JSON の相対パス（`<root>/config/suno-playlists.json`）。
_OUTPUT_RELPATH = Path("config") / "suno-playlists.json"


# ---------------------------------------------------------------------------
# SSOT: ルート文字列の契約一致（拡張・サーバーで同一値を共有する）
# ---------------------------------------------------------------------------


def test_suno_playlists_route_constant_matches_contract():
    """Given suno_artifacts の SUNO_PLAYLISTS_ROUTE
    When 値を読む
    Then 拡張側 PLAYLISTS_CAPTURE_ROUTE と対の `/suno/playlists` リテラルに一致する。
    """
    from youtube_automation.scripts.suno_artifacts import SUNO_PLAYLISTS_ROUTE

    assert SUNO_PLAYLISTS_ROUTE == _SUNO_PLAYLISTS_ROUTE


# ---------------------------------------------------------------------------
# normalize_suno_title: `<prefix> | <theme>` → `<prefix>-<theme-slug>` 純関数
# ---------------------------------------------------------------------------


def test_normalize_suno_title_basic_prefix_match():
    """Given `df365 | Deep Focus`（prefix 一致）
    When normalize_suno_title を呼ぶ
    Then `df365-deep-focus`（小文字・空白→`-`）を返す。
    """
    assert normalize_suno_title("df365 | Deep Focus", "df365") == "df365-deep-focus"


def test_normalize_suno_title_is_case_insensitive_on_prefix_and_theme():
    """Given prefix / theme の大文字混じり `RJN | Graphite Hour`
    When normalize_suno_title を呼ぶ
    Then 大小無視で `rjn-graphite-hour` を返す。
    """
    assert normalize_suno_title("RJN | Graphite Hour", "rjn") == "rjn-graphite-hour"


def test_normalize_suno_title_folds_consecutive_whitespace_to_single_hyphen():
    """Given 連続空白・前後空白を含む theme `df365 |   Deep    Focus  `
    When normalize_suno_title を呼ぶ
    Then 連続空白を `-` 1 つに畳み込み `df365-deep-focus` を返す。
    """
    assert normalize_suno_title("df365 |   Deep    Focus  ", "df365") == "df365-deep-focus"


def test_normalize_suno_title_matches_without_spaces_around_pipe():
    """Given パイプ前後に空白の無い `df365|Deep Focus`
    When normalize_suno_title を呼ぶ
    Then `\\s*` により空白なしでも一致し `df365-deep-focus` を返す。
    """
    assert normalize_suno_title("df365|Deep Focus", "df365") == "df365-deep-focus"


def test_normalize_suno_title_returns_none_for_prefix_mismatch():
    """Given prefix 不一致 `df365 | x`（prefix=rjn）
    When normalize_suno_title を呼ぶ
    Then None を返す（channel-agnostic フィルタはサーバー側に閉じる）。
    """
    assert normalize_suno_title("df365 | x", "rjn") is None


def test_normalize_suno_title_returns_none_when_prefix_is_a_partial_token():
    """Given prefix がパイプ前トークンの部分文字列でしかない `df365 | x`（prefix=df）
    When normalize_suno_title を呼ぶ
    Then 行頭アンカー + パイプ直前一致でないため None を返す（前方一致の取りこぼし防止）。
    """
    assert normalize_suno_title("df365 | x", "df") is None


def test_normalize_suno_title_returns_none_without_pipe_separator():
    """Given パイプ区切りの無いタイトル `just a title`
    When normalize_suno_title を呼ぶ
    Then None を返す。
    """
    assert normalize_suno_title("just a title", "df365") is None


# ---------------------------------------------------------------------------
# derive_collection_slug: collection dir 名 → `<prefix>-<theme-slug>`
#   normalize_suno_title と同じ slug 形を生成する（マージキー突合の不変条件）。
# ---------------------------------------------------------------------------


def test_derive_collection_slug_strips_date_and_uses_prefix():
    """Given collection id `20260601-rjn-graphite-hour-collection`（prefix=rjn）
    When derive_collection_slug を呼ぶ
    Then 日付・接尾辞を除いて `rjn-graphite-hour` を返す。
    """
    assert derive_collection_slug("20260601-rjn-graphite-hour-collection", "rjn") == "rjn-graphite-hour"


def test_derive_collection_slug_matches_normalize_suno_title_for_same_theme():
    """Given 同一 theme を表す collection id と Suno タイトル
    When それぞれ derive_collection_slug / normalize_suno_title を呼ぶ
    Then 同じ slug を返す（マージキーとして突合可能、という不変条件）。
    """
    slug_from_id = derive_collection_slug("20260601-rjn-graphite-hour-collection", "rjn")
    slug_from_title = normalize_suno_title("rjn | Graphite Hour", "rjn")

    assert slug_from_id == slug_from_title == "rjn-graphite-hour"


# ---------------------------------------------------------------------------
# #976: prefix の空白/ハイフン無差別マッチと複数トークンチャンネル名の slug 導出
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# derive_playlist_name: collection dir 名 → `<prefix> | <theme>` の playlist 名
# ---------------------------------------------------------------------------


def test_derive_playlist_name_single_word_prefix():
    assert derive_playlist_name("20260601-df365-morning-mode-collection", "df365") == "df365 | morning-mode"


def test_derive_playlist_name_multi_word_prefix():
    """マルチワード prefix でも正しい境界で分割される。"""
    assert (
        derive_playlist_name("20260601-soulful-grooves-wah-groove-collection", "soulful-grooves")
        == "soulful-grooves | wah-groove"
    )


def test_derive_playlist_name_without_date():
    assert derive_playlist_name("df365-morning-mode-collection", "df365") == "df365 | morning-mode"


def test_derive_playlist_name_without_collection_suffix():
    assert derive_playlist_name("20260601-rjn-dawn-cloud-fold", "rjn") == "rjn | dawn-cloud-fold"


def test_derive_playlist_name_matches_normalize_roundtrip():
    """derive_playlist_name の出力を normalize_suno_title に通すと derive_collection_slug と同じ slug になる。"""
    pname = derive_playlist_name("20260601-soulful-grooves-horn-stab-master-collection", "soulful-grooves")
    slug_from_name = normalize_suno_title(pname, "soulful-grooves")
    slug_from_id = derive_collection_slug("20260601-soulful-grooves-horn-stab-master-collection", "soulful-grooves")
    assert slug_from_name == slug_from_id == "soulful-grooves-horn-stab-master"


def test_normalize_suno_title_matches_space_separated_prefix_against_hyphen_prefix():
    """Given タイトル `Soulful Grooves | Horn Stab Master`（prefix=soulful-grooves）
    When normalize_suno_title を呼ぶ
    Then 空白とハイフンを同一視して `soulful-grooves-horn-stab-master` を返す（#976）。
    """
    assert (
        normalize_suno_title("Soulful Grooves | Horn Stab Master", "soulful-grooves")
        == "soulful-grooves-horn-stab-master"
    )


def test_normalize_suno_title_still_rejects_partial_multi_token_prefix():
    """Given タイトル `Soulful | Horn Stab`（prefix=soulful-grooves の前半のみ）
    When normalize_suno_title を呼ぶ
    Then prefix 全体が一致しないため None を返す。
    """
    assert normalize_suno_title("Soulful | Horn Stab", "soulful-grooves") is None


def test_derive_collection_slug_strips_multi_token_channel_matching_prefix():
    """Given collection id `20260611-soulful-grooves-horn-stab-master-collection`（prefix=soulful-grooves）
    When derive_collection_slug を呼ぶ
    Then チャンネル名 2 トークンを丸ごと剥がし `soulful-grooves-horn-stab-master` を返す（#976）。

    旧実装は 1 トークンしか剥がさず `soulful-grooves-grooves-horn-stab-master` になり、
    playlist 側 slug と永遠に一致しなかった。
    """
    assert (
        derive_collection_slug("20260611-soulful-grooves-horn-stab-master-collection", "soulful-grooves")
        == "soulful-grooves-horn-stab-master"
    )


def test_derive_collection_slug_falls_back_to_single_token_strip_when_prefix_differs():
    """Given dir のチャンネル表記（df365）と prefix（DF）が異なる運用
    When derive_collection_slug を呼ぶ
    Then 従来どおり先頭 1 トークンを channel として剥がす（後方互換）。
    """
    assert (
        derive_collection_slug("20260601-df365-cognitive-sharpness-mode-collection", "DF")
        == "df-cognitive-sharpness-mode"
    )


def test_derive_collection_slug_multi_token_matches_normalize_suno_title():
    """Given 同一 theme の collection id と空白区切りタイトル（複数トークンチャンネル）
    When それぞれを slug 化する
    Then 同じ slug を返す（マージキー突合の不変条件、#976）。
    """
    slug_from_id = derive_collection_slug("20260611-soulful-grooves-horn-stab-master-collection", "soulful-grooves")
    slug_from_title = normalize_suno_title("Soulful Grooves | Horn Stab Master", "soulful-grooves")

    assert slug_from_id == slug_from_title == "soulful-grooves-horn-stab-master"


# ---------------------------------------------------------------------------
# _resolve_playlist_capture: root/prefix の意味的不変条件（fail-loud）+ env fallback
# 要件 1/2/4: 両指定でのみ有効・片方欠落は ConfigError・両不在は None。
# ---------------------------------------------------------------------------


def test_resolve_playlist_capture_returns_none_when_both_absent(monkeypatch):
    """Given root も prefix も未指定（CLI 引数 None・env 未設定）
    When _resolve_playlist_capture を呼ぶ
    Then None を返す（POST は無効、silent でよい唯一のケース）。
    """
    monkeypatch.delenv("PLAYLIST_CAPTURE_ROOT", raising=False)
    monkeypatch.delenv("PLAYLIST_CAPTURE_PREFIX", raising=False)

    assert _resolve_playlist_capture(None, None) is None


def test_resolve_playlist_capture_raises_when_only_root_given(monkeypatch):
    """Given root だけ指定・prefix 不在
    When _resolve_playlist_capture を呼ぶ
    Then ConfigError で fail-loud する（silent 無効化しない）。
    """
    monkeypatch.delenv("PLAYLIST_CAPTURE_ROOT", raising=False)
    monkeypatch.delenv("PLAYLIST_CAPTURE_PREFIX", raising=False)

    with pytest.raises(ConfigError):
        _resolve_playlist_capture("/tmp/channel", None)


def test_resolve_playlist_capture_raises_when_only_prefix_given(monkeypatch):
    """Given prefix だけ指定・root 不在
    When _resolve_playlist_capture を呼ぶ
    Then ConfigError で fail-loud する（silent 無効化しない）。
    """
    monkeypatch.delenv("PLAYLIST_CAPTURE_ROOT", raising=False)
    monkeypatch.delenv("PLAYLIST_CAPTURE_PREFIX", raising=False)

    with pytest.raises(ConfigError):
        _resolve_playlist_capture(None, "df365")


def test_resolve_playlist_capture_returns_expanded_root_and_prefix_when_both_given(monkeypatch):
    """Given root と prefix の両方を CLI 引数で指定（`~` を含む root）
    When _resolve_playlist_capture を呼ぶ
    Then `(Path(root).expanduser(), prefix)` のタプルを返す。
    """
    monkeypatch.delenv("PLAYLIST_CAPTURE_ROOT", raising=False)
    monkeypatch.delenv("PLAYLIST_CAPTURE_PREFIX", raising=False)
    monkeypatch.setenv("HOME", "/home/df365")

    result = _resolve_playlist_capture("~/channel", "df365")

    assert result == (Path("/home/df365/channel"), "df365")


def test_resolve_playlist_capture_falls_back_to_env_when_args_absent(monkeypatch):
    """Given CLI 引数は None だが env に root/prefix が両方ある
    When _resolve_playlist_capture を呼ぶ
    Then env 値から `(Path(root).expanduser(), prefix)` を解決する。
    """
    monkeypatch.setenv("PLAYLIST_CAPTURE_ROOT", "/srv/df365-channel")
    monkeypatch.setenv("PLAYLIST_CAPTURE_PREFIX", "df365")

    assert _resolve_playlist_capture(None, None) == (Path("/srv/df365-channel"), "df365")


def test_resolve_playlist_capture_raises_when_only_env_root_present(monkeypatch):
    """Given env に root だけある（prefix は CLI 引数・env とも不在）
    When _resolve_playlist_capture を呼ぶ
    Then ConfigError で fail-loud する（env 経由でも片方欠落は許さない）。
    """
    monkeypatch.setenv("PLAYLIST_CAPTURE_ROOT", "/srv/df365-channel")
    monkeypatch.delenv("PLAYLIST_CAPTURE_PREFIX", raising=False)

    with pytest.raises(ConfigError):
        _resolve_playlist_capture(None, None)


def test_resolve_playlist_capture_cli_arg_overrides_env(monkeypatch):
    """Given CLI 引数と env の両方が設定されている
    When _resolve_playlist_capture を呼ぶ
    Then CLI 引数が env より優先される。
    """
    monkeypatch.setenv("PLAYLIST_CAPTURE_ROOT", "/env/root")
    monkeypatch.setenv("PLAYLIST_CAPTURE_PREFIX", "envprefix")

    assert _resolve_playlist_capture("/cli/root", "cliprefix") == (Path("/cli/root"), "cliprefix")


# ---------------------------------------------------------------------------
# write_suno_playlists: atomic merge write（後勝ち・破損再作成・dir 自動作成）
# ---------------------------------------------------------------------------


def _read_output(root: Path) -> dict:
    return json.loads((root / _OUTPUT_RELPATH).read_text(encoding="utf-8"))


def test_write_suno_playlists_creates_config_dir_and_file(tmp_path):
    """Given config/ が存在しない root
    When write_suno_playlists を呼ぶ
    Then `<root>/config/suno-playlists.json` を新規作成し、slug を key に持つ。
    """
    root = tmp_path / "channel"
    payload = [{"title": "df365 | Deep Focus", "url": "https://suno.com/playlist/u1"}]

    written = write_suno_playlists(root, payload, prefix="df365")

    assert written == 1
    data = _read_output(root)
    assert "df365-deep-focus" in data
    assert data["df365-deep-focus"]["url"] == "https://suno.com/playlist/u1"


def test_write_suno_playlists_skips_prefix_mismatch_items(tmp_path):
    """Given prefix 一致 1 件 + 不一致 1 件
    When write_suno_playlists を呼ぶ
    Then 一致分のみ書き込み、書込件数 1 を返す（フィルタはサーバー側に閉じる）。
    """
    root = tmp_path / "channel"
    payload = [
        {"title": "df365 | Deep Focus", "url": "https://suno.com/playlist/u1"},
        {"title": "other | Ignore Me", "url": "https://suno.com/playlist/u2"},
    ]

    written = write_suno_playlists(root, payload, prefix="df365")

    assert written == 1
    data = _read_output(root)
    assert set(data.keys()) == {"df365-deep-focus"}


def test_write_suno_playlists_merges_with_existing_other_slugs(tmp_path):
    """Given 既に slug A を書き込んだ root
    When 別 slug B を write_suno_playlists で追記する
    Then A を残したまま B を加える（merge であり全置換でない）。
    """
    root = tmp_path / "channel"
    write_suno_playlists(root, [{"title": "df365 | Alpha", "url": "https://suno.com/playlist/a"}], prefix="df365")

    write_suno_playlists(root, [{"title": "df365 | Beta", "url": "https://suno.com/playlist/b"}], prefix="df365")

    data = _read_output(root)
    assert set(data.keys()) == {"df365-alpha", "df365-beta"}


def test_write_suno_playlists_same_slug_is_overwritten_last_wins(tmp_path):
    """Given 既に slug A を url=a で書き込んだ root
    When 同 slug を url=a2 で再度 write する
    Then 後勝ちで url=a2 に上書きされる（captured_at 後勝ち）。
    """
    root = tmp_path / "channel"
    write_suno_playlists(root, [{"title": "df365 | Alpha", "url": "https://suno.com/playlist/a"}], prefix="df365")

    write_suno_playlists(root, [{"title": "df365 | Alpha", "url": "https://suno.com/playlist/a2"}], prefix="df365")

    data = _read_output(root)
    assert set(data.keys()) == {"df365-alpha"}
    assert data["df365-alpha"]["url"] == "https://suno.com/playlist/a2"


def test_write_suno_playlists_recreates_when_existing_json_is_corrupt(tmp_path):
    """Given 破損した既存 `config/suno-playlists.json`
    When write_suno_playlists を呼ぶ
    Then 例外を投げず上書きで新規作成する（破損は空 dict 扱い）。
    """
    root = tmp_path / "channel"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "suno-playlists.json").write_text("{ this is : not json", encoding="utf-8")

    written = write_suno_playlists(
        root, [{"title": "df365 | Deep Focus", "url": "https://suno.com/playlist/u1"}], prefix="df365"
    )

    assert written == 1
    data = _read_output(root)
    assert "df365-deep-focus" in data


def test_write_suno_playlists_leaves_no_temp_file_behind(tmp_path):
    """Given write_suno_playlists の atomic write（tempfile→os.replace）
    When 書き込み後の config/ を列挙する
    Then 中間 temp ファイルが残らず最終 JSON のみが存在する。
    """
    root = tmp_path / "channel"
    write_suno_playlists(root, [{"title": "df365 | Deep Focus", "url": "https://suno.com/playlist/u1"}], prefix="df365")

    files = sorted(p.name for p in (root / "config").iterdir())

    assert files == ["suno-playlists.json"]


# ---------------------------------------------------------------------------
# read_mapped_slugs: 既存 JSON の slug 集合（不在・破損は空集合）
# ---------------------------------------------------------------------------


def test_read_mapped_slugs_returns_empty_set_when_file_absent(tmp_path):
    """Given config/suno-playlists.json が存在しない root
    When read_mapped_slugs を呼ぶ
    Then 空集合を返す（fail-loud せず未マッピング扱い）。
    """
    assert read_mapped_slugs(tmp_path / "channel") == set()


def test_read_mapped_slugs_returns_empty_set_when_file_corrupt(tmp_path):
    """Given 破損した config/suno-playlists.json
    When read_mapped_slugs を呼ぶ
    Then 空集合を返す（破損は空集合扱い）。
    """
    root = tmp_path / "channel"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "suno-playlists.json").write_text("<broken>", encoding="utf-8")

    assert read_mapped_slugs(root) == set()


def test_read_mapped_slugs_reads_legacy_list_schema(tmp_path):
    """Given 旧 wf-batch list スキーマ `[{slug, suno_url, suno_title, captured_at}]` の既存ファイル
    When read_mapped_slugs を呼ぶ
    Then slug 集合を返す（破損扱いで空集合にしない、#976）。
    """
    target = tmp_path / _OUTPUT_RELPATH
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            [
                {
                    "slug": "rjn-graphite-hour",
                    "suno_url": "https://suno.com/playlist/x",
                    "suno_title": "RJN | Graphite Hour",
                    "captured_at": "2026-06-09T02:08:37Z",
                },
                {"slug": "", "suno_url": "https://suno.com/playlist/y"},
                "not-a-dict",
            ]
        ),
        encoding="utf-8",
    )

    assert read_mapped_slugs(tmp_path) == {"rjn-graphite-hour"}


def test_write_suno_playlists_migrates_legacy_list_schema_without_data_loss(tmp_path):
    """Given 旧 list スキーマの既存ファイル
    When 別 slug を write_suno_playlists で merge write する
    Then 既存 entry は dict スキーマ（title/url 正準キー）へ移行され、消失しない（#976）。

    旧実装は list を「破損」とみなし新規 dict で上書きしていたため、wf-batch 用の
    既存マッピングが capture 実行で消えるデータロスがあった。
    """
    target = tmp_path / _OUTPUT_RELPATH
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            [
                {
                    "slug": "rjn-graphite-hour",
                    "suno_url": "https://suno.com/playlist/x",
                    "suno_title": "RJN | Graphite Hour",
                    "captured_at": "2026-06-09T02:08:37Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    written = write_suno_playlists(
        tmp_path,
        [{"title": "RJN | Honey Hour", "url": "https://suno.com/playlist/z"}],
        prefix="rjn",
    )

    assert written == 1
    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data["rjn-graphite-hour"]["url"] == "https://suno.com/playlist/x"
    assert data["rjn-graphite-hour"]["title"] == "RJN | Graphite Hour"
    assert data["rjn-graphite-hour"]["captured_at"] == "2026-06-09T02:08:37Z"
    assert data["rjn-honey-hour"]["url"] == "https://suno.com/playlist/z"


def test_read_mapped_slugs_returns_written_slugs(tmp_path):
    """Given write_suno_playlists で 2 slug を書き込んだ root
    When read_mapped_slugs を呼ぶ
    Then 書き込んだ slug 集合を返す（write との round-trip）。
    """
    root = tmp_path / "channel"
    write_suno_playlists(
        root,
        [
            {"title": "df365 | Alpha", "url": "https://suno.com/playlist/a"},
            {"title": "df365 | Beta", "url": "https://suno.com/playlist/b"},
        ],
        prefix="df365",
    )

    assert read_mapped_slugs(root) == {"df365-alpha", "df365-beta"}


# ---------------------------------------------------------------------------
# build_collections_index: mapped 判定（追加要件 B）
# ---------------------------------------------------------------------------


def _make_collection(planning: Path, dir_name: str, entries=None) -> Path:
    """planning dir 配下に `<dir_name>/20-documentation/suno-prompts.json` を作る。"""
    coll = planning / dir_name
    docs = coll / "20-documentation"
    docs.mkdir(parents=True)
    if entries is not None:
        (docs / "suno-prompts.json").write_text(json.dumps(entries), encoding="utf-8")
    return coll


def test_build_collections_index_marks_mapped_true_for_captured_slug(tmp_path):
    """Given derive_collection_slug が mapped_slugs に含まれる collection
    When build_collections_index(prefix=, mapped_slugs=) を呼ぶ
    Then その entry の mapped が True になる。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning, "20260601-rjn-graphite-hour-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}]
    )

    rows = {r["id"]: r for r in build_collections_index(planning, mapped_slugs={"rjn-graphite-hour"}, prefix="rjn")}

    assert rows["20260601-rjn-graphite-hour-collection"]["mapped"] is True


def test_build_collections_index_marks_mapped_false_for_uncaptured_slug(tmp_path):
    """Given derive_collection_slug が mapped_slugs に含まれない collection
    When build_collections_index(prefix=, mapped_slugs=) を呼ぶ
    Then その entry の mapped が False になる。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning, "20260602-rjn-other-theme-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}]
    )

    rows = {r["id"]: r for r in build_collections_index(planning, mapped_slugs={"rjn-graphite-hour"}, prefix="rjn")}

    assert rows["20260602-rjn-other-theme-collection"]["mapped"] is False


def test_build_collections_index_defaults_to_unmapped_when_prefix_absent(tmp_path):
    """Given prefix を渡さないデフォルト呼び出し（後方互換）
    When build_collections_index を呼ぶ
    Then 全 entry の mapped が False になる（mapped_slugs があっても prefix 無は素通し）。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning, "20260601-rjn-graphite-hour-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}]
    )

    rows = build_collections_index(planning)

    assert all(r["mapped"] is False for r in rows)


def test_build_collections_index_returns_playlist_name_with_prefix(tmp_path):
    """Given prefix 付きで build_collections_index を呼ぶ
    When 結果を取得
    Then playlist_name にサーバー側で導出した正しい playlist 名が含まれる。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-rjn-dawn-fold-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])

    rows = {r["id"]: r for r in build_collections_index(planning, prefix="rjn")}

    assert rows["20260601-rjn-dawn-fold-collection"]["playlist_name"] == "rjn | dawn-fold"


def test_build_collections_index_returns_playlist_name_multi_word_prefix(tmp_path):
    """Given マルチワード prefix で build_collections_index を呼ぶ
    Then playlist_name が正しい境界で分割される。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning, "20260601-soulful-grooves-wah-groove-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}]
    )

    rows = {r["id"]: r for r in build_collections_index(planning, prefix="soulful-grooves")}

    assert rows["20260601-soulful-grooves-wah-groove-collection"]["playlist_name"] == "soulful-grooves | wah-groove"


def test_build_collections_index_playlist_name_none_without_prefix(tmp_path):
    """Given prefix なし（後方互換）
    Then playlist_name は None。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-rjn-dawn-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])

    rows = build_collections_index(planning)

    assert all(r["playlist_name"] is None for r in rows)


# ---------------------------------------------------------------------------
# HTTP 統合: POST /suno/playlists（200 / 403 / 404 / 400）+ OPTIONS
# ---------------------------------------------------------------------------


@pytest.fixture
def serve_capture(tmp_path):
    """playlist_capture を渡してサーバーを起動し base URL を返すファクトリ.

    capture_root=None なら playlist_capture 無効（root 未設定 = POST が 404 になる）モード。
    GET 側は単一ファイル mode（空 prompts）で起動する（POST 検証には無関係）。
    """
    started = []

    def _start(*, capture_root=None, prefix="df365", allow_origin=None):
        json_path = tmp_path / "suno-prompts.json"
        json_path.write_text("[]", encoding="utf-8")
        playlist_capture = (capture_root, prefix) if capture_root is not None else None
        server = create_server(
            0,
            allow_origin,
            prompts_path=json_path,
            collection_dir=tmp_path,
            distrokid=None,
            playlist_capture=playlist_capture,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        port = server.server_address[1]
        return f"http://localhost:{port}"

    yield _start

    for server, thread in started:
        server.shutdown()
        thread.join(timeout=5)


def _post(url: str, body, *, headers=None):
    """JSON body を POST する。body は dict/list なら JSON 直列化、bytes はそのまま送る。"""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    return urllib.request.urlopen(req)


def _assert_json_error(err: urllib.error.HTTPError, *, status: int, message: str, expected_origin: str | None) -> None:
    assert err.code == status
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == expected_origin
    assert json.loads(err.read().decode("utf-8")) == {"error": message}


def test_post_suno_playlists_writes_file_and_returns_written_and_path(tmp_path, serve_capture):
    """Given 許可 Origin からの POST /suno/playlists
    When prefix 一致 1 件を送る
    Then 200 + `{written, path}` を返し、`<root>/config/suno-playlists.json` を更新する。
    """
    capture_root = tmp_path / "out"
    base = serve_capture(capture_root=capture_root, prefix="df365")
    payload = [{"title": "df365 | smoke", "url": "https://suno.com/playlist/u1"}]

    with _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN}) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))

    assert result["written"] == 1
    assert str(result["path"]).endswith(str(_OUTPUT_RELPATH))
    written_file = json.loads((capture_root / _OUTPUT_RELPATH).read_text(encoding="utf-8"))
    assert written_file["df365-smoke"]["url"] == "https://suno.com/playlist/u1"


def test_post_suno_playlists_echoes_cors_header_for_allowed_origin(tmp_path, serve_capture):
    """Given 許可 Origin からの POST
    When レスポンスヘッダを読む
    Then Access-Control-Allow-Origin がその Origin を echo する。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")
    payload = [{"title": "df365 | smoke", "url": "https://suno.com/playlist/u1"}]

    with _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN}) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_post_suno_playlists_returns_written_zero_for_prefix_mismatch(tmp_path, serve_capture):
    """Given prefix 不一致のみの POST body
    When POST する
    Then 200 で written=0 を返す（サーバー側フィルタが弾く）。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")
    payload = [{"title": "other | nope", "url": "https://suno.com/playlist/u9"}]

    with _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN}) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))

    assert result["written"] == 0


def test_post_suno_playlists_without_origin_returns_403(tmp_path, serve_capture):
    """Given Origin ヘッダ無しの POST
    When POST する
    Then 403 を返す（GET と異なり POST は Origin 必須）。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")
    payload = [{"title": "df365 | smoke", "url": "https://suno.com/playlist/u1"}]

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload)

    _assert_json_error(exc_info.value, status=403, message="Forbidden", expected_origin=None)


def test_post_suno_playlists_with_disallowed_origin_returns_403(tmp_path, serve_capture):
    """Given 許可リスト外 Origin からの POST
    When POST する
    Then 403 を返す。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")
    payload = [{"title": "df365 | smoke", "url": "https://suno.com/playlist/u1"}]

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload, headers={"Origin": "https://evil.com"})

    _assert_json_error(exc_info.value, status=403, message="Forbidden", expected_origin=None)


def test_post_suno_playlists_returns_404_when_capture_disabled(serve_capture):
    """Given playlist_capture 未設定（--playlist-capture-root 無し）で起動したサーバー
    When 許可 Origin から POST する
    Then 404 を返す（capture 無効時は endpoint 自体が無い）。
    """
    base = serve_capture(capture_root=None)
    payload = [{"title": "df365 | smoke", "url": "https://suno.com/playlist/u1"}]

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=404, message="Not Found", expected_origin=_EXTENSION_ORIGIN)


def test_post_unknown_path_returns_404(tmp_path, serve_capture):
    """Given capture 有効サーバー
    When 許可 Origin から /suno/playlists 以外へ POST する
    Then 404 を返す（POST は capture route のみハンドルする）。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}/suno/unknown", [], headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=404, message="Not Found", expected_origin=_EXTENSION_ORIGIN)


def test_post_suno_playlists_non_list_body_returns_400(tmp_path, serve_capture):
    """Given JSON list でない body（オブジェクト）
    When 許可 Origin から POST する
    Then 400 を返す（body は配列契約のまま受ける、envelope 流用を弾く）。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", {"title": "df365 | x"}, headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)


def test_post_suno_playlists_invalid_json_body_returns_400(tmp_path, serve_capture):
    """Given JSON として解釈できない body
    When 許可 Origin から POST する
    Then CORS 付き JSON 400 を返す（fail-loud、silent に空書き込みしない）。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_SUNO_PLAYLISTS_ROUTE}", b"{not json", headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)


def test_options_preflight_allows_post_method(tmp_path, serve_capture):
    """Given 許可 Origin からの preflight
    When `OPTIONS /suno/playlists`
    Then Access-Control-Allow-Methods に POST を含める。
    """
    base = serve_capture(capture_root=tmp_path / "out", prefix="df365")
    req = urllib.request.Request(
        f"{base}{_SUNO_PLAYLISTS_ROUTE}",
        method="OPTIONS",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 204)
        assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")
