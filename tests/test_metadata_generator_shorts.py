"""
BAHMetadataGenerator.generate_shorts_metadata のユニットテスト

テスト対象: `src/youtube_automation/domains/metadata/service.py::BAHMetadataGenerator.generate_shorts_metadata`
plan 要件 #2〜#5 / #4-a〜#4-d / 補足設計判断 §152-153 を検証する。

副作用のない純粋ロジック（タイトル・タグ・説明文・ローカライズ生成）を検証する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.configuration import load_config, reset
from youtube_automation.domains.metadata import (
    BAHMetadataGenerator,
    build_short_localizations,
)

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_generator(
    dir_name: str = "20250907-live-8bit-adventure-music",
    *,
    collection_path: Path | None = None,
    target_duration_min: float | None = None,
) -> BAHMetadataGenerator:
    """test_metadata_generator.py と同形式で I/O を回避したインスタンスを生成する.

    test-design L112 シグネチャ `_make_generator(dir_name, *, target_duration_min=None)` 準拠。

    Args:
        dir_name: コレクションディレクトリ名（`/tmp/fake-collections/{dir_name}`）
        collection_path: 指定時はそのパスを採用（workflow-state.json を読み込ませたい場合）
        target_duration_min: 指定時は `gen.config.audio.target_duration_min` を上書きする。
            `None`（default）なら sample_channel の audio.json 不在状態をそのまま使い、
            `BAHMetadataGenerator.generate_shorts_metadata` の "Full collection" fallback を発火させる。
    """
    from dataclasses import replace

    from youtube_automation.utils.skill_config import load_skill_config

    gen = object.__new__(BAHMetadataGenerator)
    gen.config = load_config()
    gen._masterup_config = load_skill_config("masterup")
    gen._crossfade_sec = float(gen._masterup_config.get("audio", {}).get("crossfade_duration", 1.0))
    gen._video_description_config = load_skill_config("video-description")
    gen.collection_path = collection_path or Path(f"/tmp/fake-collections/{dir_name}")
    gen.collection_name = gen._extract_collection_name()
    gen.bit_depth = gen.config.content.genre.style
    gen.tracks = []
    if target_duration_min is not None:
        # config.audio.target_duration_min を override（dataclass は frozen=True なので replace）
        new_audio = replace(gen.config.audio, target_duration_min=target_duration_min)
        gen.config = replace(gen.config, audio=new_audio)
    return gen


def _make_collection(tmp_path: Path, dir_name: str, *, theme: str | None = None) -> Path:
    """tmp_path 配下に workflow-state.json を持つコレクションを作る."""
    col = tmp_path / dir_name
    col.mkdir(parents=True)
    ws = {"collection_name": dir_name}
    if theme is not None:
        ws["theme"] = theme
    (col / "workflow-state.json").write_text(json.dumps(ws, ensure_ascii=False), encoding="utf-8")
    return col


def _write_localizations(ch: Path, data: dict) -> None:
    loc_path = ch / "config" / "localizations.json"
    loc_path.parent.mkdir(parents=True, exist_ok=True)
    loc_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _short_localizations_full() -> dict:
    """short_title_template / short_description_template を全言語に持つ localizations 設定."""
    return {
        "supported_languages": ["ja", "en"],
        "default_language": "ja",
        "languages": {
            "ja": {
                "title_template": "{scene_phrase} | RPG BGM ({activities})",
                "activities": "ゲーム · 勉強",
                "short_title_template": "{theme} | {channel_name} #Shorts",
                "short_description_template": (
                    "{collection_name} | {channel_name}\n\n♫ Full → {cc_video_url}\n\n{tagline}"
                ),
                "description": {
                    "opening_poem": "夜の旋律",
                    "cta_subscribe": "チャンネル登録",
                    "tagline": "JP tagline",
                    "hashtags": "#shorts",
                },
            },
            "en": {
                "title_template": "{scene_phrase} | RPG BGM ({activities})",
                "activities": "Gaming · Study",
                "short_title_template": "{theme} ✦ {channel_name} #Shorts",
                "short_description_template": (
                    "{collection_name} | {channel_name}\n\n♫ Full → {cc_video_url}\n\n{tagline}"
                ),
                "description": {
                    "opening_poem": "Night melody",
                    "cta_subscribe": "Subscribe",
                    "tagline": "EN tagline",
                    "hashtags": "#shorts",
                },
            },
        },
    }


def _short_localizations_partial() -> dict:
    """ja のみ short_title_template を持ち、en は持たない構成（en は skip される想定）."""
    data = _short_localizations_full()
    del data["languages"]["en"]["short_title_template"]
    del data["languages"]["en"]["short_description_template"]
    return data


def _short_localizations_no_desc_template() -> dict:
    """ja は title_template はあるが description_template が無い（description フォールバック検証）."""
    data = _short_localizations_full()
    del data["languages"]["ja"]["short_description_template"]
    return data


def _setup_channel_with_localizations(tmp_path: Path, loc_data: dict) -> Path:
    """sample_channel をベースに localizations.json を上書きしたチャンネルディレクトリを作る."""
    import shutil

    src = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
    dst = tmp_path / "channel"
    shutil.copytree(src, dst)
    # localizations を上書き
    _write_localizations(dst, loc_data)
    # content_model.languages を localizations.supported_languages にあわせて緩める
    yt_path = dst / "config" / "channel" / "youtube.json"
    with open(yt_path, "r", encoding="utf-8") as f:
        yt = json.load(f)
    yt.setdefault("content_model", {})["languages"] = list(loc_data.get("supported_languages", ["ja"]))
    yt_path.write_text(json.dumps(yt, ensure_ascii=False), encoding="utf-8")
    return dst


# ===========================================================================
# 1. CC リンク行の有無 (plan 要件 #2 / #3)
# ===========================================================================


class TestCCLink:
    """`cc_video_url` の有無による description の差分検証."""

    def test_cc_video_url_present_includes_link_line(self):
        # Given: 有効な CC URL
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/dQw4w9WgXcQ")

        # Then: ♫ で始まる CC リンク行が含まれる（旧版踏襲）
        assert "♫" in meta["description"]
        assert "https://youtu.be/dQw4w9WgXcQ" in meta["description"]

    def test_cc_video_url_empty_skips_link_line(self):
        """plan 要件 #3 / アンチパターン #5: 空文字なら CC 行を skip、例外は投げない."""
        # Given
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When: 例外を投げず metadata を返せる
        meta = gen.generate_shorts_metadata("")

        # Then: ♫ 行を含まない
        assert "♫" not in meta["description"]
        # description 自体は空ではない
        assert len(meta["description"]) > 0


# ===========================================================================
# 2. tags 構築 (plan 要件 #4-a / #4-b / #4-c / #4-d)
# ===========================================================================


class TestTagsComposition:
    """tags の構成順序とスライス境界の検証."""

    def test_tags_first_element_is_shorts_literal(self):
        """plan 要件 #4-a: tags[0] == "Shorts" 先頭固定."""
        # Given
        gen = _make_generator("20250907-live-8bit-battle-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: 位置 index で確認（リファクタリング耐性）
        assert meta["tags"][0] == "Shorts"

    def test_tags_includes_base_tags(self):
        """plan 要件 #4-b: config.content.tags.base が連結される."""
        # Given
        gen = _make_generator("20250907-live-8bit-village-music")
        config = load_config()

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: base tags が含まれる
        for base in config.content.tags.base:
            assert base in meta["tags"]

    def test_tags_includes_theme_tags_when_theme_matches(self, tmp_path):
        """plan 要件 #4-c: config.content.tags.themes.get(theme, []) が連結される.

        workflow-state.json の `theme` を読み、`tags.themes` から該当テーマのタグを連結する。
        """
        # Given: collection_name "battle" / workflow-state.theme="battle"
        col = _make_collection(tmp_path, "20250907-live-8bit-battle-music", theme="battle")
        gen = _make_generator(collection_path=col)
        config = load_config()
        battle_tags = config.content.tags.themes.get("battle", [])

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: battle テーマのタグがすべて含まれる
        for t in battle_tags:
            assert t in meta["tags"]

    def test_tags_unknown_theme_does_not_add_theme_tags(self, tmp_path):
        """plan 要件 #4-c の境界: workflow-state.theme が tags.themes に無ければ追加なし."""
        # Given
        col = _make_collection(tmp_path, "20250907-live-8bit-mystery-music", theme="no-such-theme")
        gen = _make_generator(collection_path=col)
        config = load_config()
        all_theme_tags = {t for vals in config.content.tags.themes.values() for t in vals}

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: テーマ別タグはひとつも入らない（"Shorts" + base のみ）
        for theme_tag in all_theme_tags:
            assert theme_tag not in meta["tags"]

    def test_tags_sliced_to_50(self, tmp_path):
        """plan 要件 #4-d / 補足設計判断 §154: 合成後 [:50] で末尾 slice."""
        # Given: base/themes を膨らませた gen
        col = _make_collection(tmp_path, "20250907-live-8bit-battle-music", theme="battle")
        gen = _make_generator(collection_path=col)
        # config を差し替えて 60 件の base タグを持たせる
        from dataclasses import replace

        big_base = [f"tag-{i}" for i in range(60)]
        new_tags = replace(gen.config.content.tags, base=big_base)
        new_content = replace(gen.config.content, tags=new_tags)
        gen.config = replace(gen.config, content=new_content)

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        assert len(meta["tags"]) <= 50

    def test_tags_quoted_values_are_normalized(self, tmp_path):
        """回帰 #1096: config のタグにダブルクォートが含まれていても除去される."""
        from dataclasses import replace as dreplace

        col = _make_collection(tmp_path, "20250907-live-8bit-battle-music", theme="battle")
        gen = _make_generator(collection_path=col)
        # base タグにダブルクォートを混入させる
        quoted_base = ['"chiptune music"', '"8-bit music"', "RPG music"]
        new_tags = dreplace(gen.config.content.tags, base=quoted_base)
        new_content = dreplace(gen.config.content, tags=new_tags)
        gen.config = dreplace(gen.config, content=new_content)

        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # ダブルクォートが含まれないことを全タグで検証
        for tag in meta["tags"]:
            assert not tag.startswith('"'), f"tag starts with quote: {tag!r}"
            assert not tag.endswith('"'), f"tag ends with quote: {tag!r}"

    def test_tags_order_preserved_shorts_first_then_base_then_themes(self, tmp_path):
        """plan 要件 #4-a/b/c 合成順序: ["Shorts"] + base + themes.get(theme, [])."""
        # Given
        col = _make_collection(tmp_path, "20250907-live-8bit-battle-music", theme="battle")
        gen = _make_generator(collection_path=col)
        config = load_config()
        base = list(config.content.tags.base)
        battle = list(config.content.tags.themes.get("battle", []))

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")
        tags = meta["tags"]

        # Then: 期待される順序が [:50] 内で維持される
        expected = ["Shorts", *base, *battle][:50]
        assert tags == expected


# ===========================================================================
# 3. localizations (plan 要件 #5)
# ===========================================================================


class TestShortsLocalizations:
    """localizations 生成のルール検証（short_title_template / short_description_template）."""

    def test_localization_uses_short_title_template_per_language(self, tmp_path, monkeypatch):
        """plan 要件 #5: short_title_template があれば各言語で展開."""
        # Given
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_full())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: ja / en の両方に title / description が入る
        loc = meta["localizations"]
        assert "ja" in loc and "en" in loc
        # ja の short_title_template に "#Shorts" が含まれる
        assert "#Shorts" in loc["ja"]["title"]
        assert loc["ja"]["title"].endswith("#Shorts")

    def test_localization_skips_languages_without_short_title_template(self, tmp_path, monkeypatch):
        """plan 要件 #5: short_title_template の無い言語は skip."""
        # Given: en は short_title_template を持たない
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_partial())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: ja は含まれ、en は含まれない
        loc = meta["localizations"]
        assert "ja" in loc
        assert "en" not in loc

    def test_localization_description_template_fills_placeholders(self, tmp_path, monkeypatch):
        """plan 要件 #5: short_description_template の placeholder が展開される."""
        # Given
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_full())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/SAMPLE")

        # Then: cc_video_url placeholder が展開されている
        ja_desc = meta["localizations"]["ja"]["description"]
        assert "https://youtu.be/SAMPLE" in ja_desc

    def test_localization_description_template_missing_uses_fallback(self, tmp_path, monkeypatch):
        """補足設計判断: short_description_template が無い言語は default 説明文にフォールバック."""
        # Given: ja は short_description_template を持たない（short_title_template はある）
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_no_desc_template())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/SAMPLE2")

        # Then: ja は localizations に残るが、description は default fallback で組み立てられる
        ja_loc = meta["localizations"]["ja"]
        assert "title" in ja_loc and "description" in ja_loc
        # fallback description にも channel_name / cc URL は出る
        assert "https://youtu.be/SAMPLE2" in ja_loc["description"]

    def test_bulk_update_parity_with_generate_shorts_metadata(self, tmp_path, monkeypatch):
        """AI-NEW-bulk-update-loc-L161 回帰: bulk_update 経路と初回 upload 経路が同一出力.

        `BAHMetadataGenerator.generate_shorts_metadata` が出す `localizations` と、
        bulk_update が呼ぶ共通 helper `build_short_localizations` の出力が、同じ
        (collection_name, theme, cc_video_url) に対して bit-identical であることを保証する。
        これにより bulk_update 実行で初回 upload のタイトル/説明が破壊されない不変条件を回帰させる。
        """
        # Given: workflow-state.json に theme を持つコレクション
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_full())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        col = _make_collection(tmp_path, "20250907-live-8bit-adventure-music", theme="battle")
        gen = _make_generator("20250907-live-8bit-adventure-music", collection_path=col)

        # When: 初回 upload 経路
        meta = gen.generate_shorts_metadata("https://youtu.be/PARITY")
        # When: bulk_update 経路（gen と同じ collection_name / theme を渡す）
        config = load_config()
        bulk_locs = build_short_localizations(
            config,
            collection_name=gen.collection_name,
            theme="battle",
            cc_video_url="https://youtu.be/PARITY",
        )

        # Then: 完全一致
        assert meta["localizations"] == bulk_locs

    def test_localization_description_within_5000_codepoints(self, tmp_path, monkeypatch):
        """localizations の description は YouTube 上限 5000 文字以下."""
        # Given
        ch = _setup_channel_with_localizations(tmp_path, _short_localizations_full())
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        for lang, loc in meta["localizations"].items():
            assert len(loc["description"]) <= 5000, f"{lang} description exceeds 5000"


# ===========================================================================
# 4. メタデータ全般のプロパティ (plan 要件 #2 / 補足設計判断)
# ===========================================================================


class TestShortsMetadataProperties:
    """category_id / privacy_status / language / description 内容の整合性."""

    def test_category_id_from_config(self):
        # Given
        gen = _make_generator("20250907-live-8bit-adventure-music")
        config = load_config()

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        assert meta["category_id"] == config.youtube.api.category_id

    def test_privacy_status_is_public(self):
        """補足設計判断: Shorts は privacy_status = 'public' で公開."""
        # Given
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        assert meta["privacy_status"] == "public"

    def test_description_contains_shorts_hashtag(self):
        """補足設計判断: description に '#Shorts' が含まれる（YouTube 検出最適化）."""
        # Given
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        assert "#Shorts" in meta["description"]

    def test_title_contains_shorts_hashtag(self):
        """補足設計判断 §153: default title は `#Shorts` を含む（旧版踏襲）."""
        # Given
        gen = _make_generator("20250907-live-8bit-adventure-music")

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then
        assert "#Shorts" in meta["title"]

    def test_title_within_100_codepoints(self):
        """補足設計判断 §153: title 100 codepoint 制限を超えるなら ValueError（silent slice 禁止）."""
        # Given: collection_name が極端に長い
        gen = _make_generator("20250907-live-8bit-" + "extra-" * 30 + "long")

        # When/Then: silent slice せず ValueError を投げる
        with pytest.raises(ValueError, match="100"):
            gen.generate_shorts_metadata("https://youtu.be/abc")

    def test_description_uses_full_collection_when_target_duration_missing(self):
        """plan 補足設計判断 §152: `config.audio.target_duration_min is None` のとき
        description は "Full collection" にフォールバックする。

        `hours = round(min / 60)` で `None` を割ってしまうと TypeError になるため、
        この fallback が無いと回帰検出できない（test-design.md §44 高優先度ケース）。
        """
        # Given: sample_channel に audio.json が無いため target_duration_min は None
        gen = _make_generator("20250907-live-8bit-adventure-music")
        assert gen.config.audio.target_duration_min is None

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: "Full collection" 文字列が description に含まれる（時間表記でない）
        assert "Full collection" in meta["description"]

    def test_description_uses_hours_when_target_duration_present(self):
        """plan 補足設計判断 §152: `target_duration_min` が設定されているときは
        `round(min / 60)` で時間表記になる（"Full collection" には fallback しない）.

        `target_duration_min=120` → 2 hours の対称ケース。書き手・読み手両側で fallback 経路を検証する。
        """
        # Given: target_duration_min = 120.0 分（= 2 hours）
        gen = _make_generator(
            "20250907-live-8bit-adventure-music",
            target_duration_min=120.0,
        )
        assert gen.config.audio.target_duration_min == 120.0

        # When
        meta = gen.generate_shorts_metadata("https://youtu.be/abc")

        # Then: "Full collection" には fallback せず、"2 hours" 表記が含まれる
        assert "Full collection" not in meta["description"]
        # `round(120 / 60) = 2` の時間表記が description に登場する
        assert "2 hour" in meta["description"]
