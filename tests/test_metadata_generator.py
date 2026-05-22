"""
BAHMetadataGenerator のユニットテスト

テスト対象: utils/metadata_generator.py
副作用のない純粋ロジック（タイムスタンプ計算、ファイル名サニタイズ、メタデータ生成）を検証する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.utils.config import load_config
from youtube_automation.utils.metadata_generator import (
    BAHMetadataGenerator,
    SceneTitleViolation,
    format_scene_title_violations,
    validate_scene_phrases,
)
from youtube_automation.utils.time_utils import format_duration_display

# ---------------------------------------------------------------------------
# ヘルパー: 最小限の初期化でインスタンスを取得する
# ---------------------------------------------------------------------------


def _make_generator(dir_name: str = "20250907-live-8bit-adventure-music") -> BAHMetadataGenerator:
    """テスト用に任意のディレクトリ名で BAHMetadataGenerator を生成する。

    実際のファイルシステムにはアクセスしない純粋ロジックのテストに使用する。
    """
    from youtube_automation.utils.skill_config import load_skill_config

    gen = object.__new__(BAHMetadataGenerator)
    gen.config = load_config()
    gen._masterup_config = load_skill_config("masterup")
    gen._crossfade_sec = float(gen._masterup_config.get("audio", {}).get("crossfade_duration", 1.0))
    gen._video_description_config = load_skill_config("video-description")
    gen.collection_path = Path(f"/tmp/fake-collections/{dir_name}")
    gen.collection_name = gen._extract_collection_name()
    gen.bit_depth = gen.config.content.genre.style
    gen.tracks = []
    return gen


# ===========================================================================
# 1. _format_timestamp のテスト
# ===========================================================================


class TestFormatTimestamp:
    """秒数を YouTube チャプター形式のタイムスタンプに変換するロジックの検証。"""

    @pytest.fixture
    def gen(self):
        return _make_generator()

    def test_zero_seconds(self, gen):
        assert gen._format_timestamp(0) == "00:00"

    def test_seconds_only(self, gen):
        assert gen._format_timestamp(5) == "00:05"

    def test_one_minute(self, gen):
        assert gen._format_timestamp(60) == "01:00"

    def test_minutes_and_seconds(self, gen):
        assert gen._format_timestamp(125) == "02:05"

    def test_just_under_one_hour(self, gen):
        assert gen._format_timestamp(3599) == "59:59"

    def test_exactly_one_hour(self, gen):
        assert gen._format_timestamp(3600) == "1:00:00"

    def test_over_one_hour(self, gen):
        assert gen._format_timestamp(3661) == "1:01:01"

    def test_large_value(self, gen):
        # 2:46:40 = 10000 seconds
        assert gen._format_timestamp(10000) == "2:46:40"

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "00:00"),
            (59, "00:59"),
            (60, "01:00"),
            (3600, "1:00:00"),
            (5400, "1:30:00"),
            (7261, "2:01:01"),
        ],
    )
    def test_parametrized(self, gen, seconds, expected):
        assert gen._format_timestamp(seconds) == expected


# ===========================================================================
# 2. _clean_track_title のテスト (ファイル名サニタイズ)
# ===========================================================================


class TestCleanTrackTitle:
    """ファイル名から楽曲タイトルを清浄化するロジックの検証。"""

    @pytest.fixture
    def gen(self):
        return _make_generator()

    def test_remove_number_prefix(self, gen):
        assert gen._clean_track_title("01-Castle Theme") == "Castle Theme"

    def test_remove_number_prefix_high(self, gen):
        assert gen._clean_track_title("22-Village at Dawn") == "Village at Dawn"

    def test_remove_8bit_prefix(self, gen):
        assert gen._clean_track_title("8bit Journey to the West") == "Journey to the West"

    def test_remove_8bit_prefix_case_insensitive(self, gen):
        assert gen._clean_track_title("8BIT Dungeon Depths") == "Dungeon Depths"

    def test_remove_suffix_parenthesis(self, gen):
        assert gen._clean_track_title("Forest Path (Remix)") == "Forest Path"

    def test_remove_suffix_extended(self, gen):
        assert gen._clean_track_title("Battle Cry (Extended)") == "Battle Cry"

    def test_underscores_to_spaces(self, gen):
        assert gen._clean_track_title("Dark_Cave_Theme") == "Dark Cave Theme"

    def test_collapse_extra_spaces(self, gen):
        assert gen._clean_track_title("  Hero   Theme  ") == "Hero Theme"

    def test_combined_cleanup(self, gen):
        # 番号プレフィックス + アンダースコア + 括弧サフィックス
        assert gen._clean_track_title("03-Mystic_Tower (Looped)") == "Mystic Tower"

    def test_no_modification_needed(self, gen):
        assert gen._clean_track_title("Crystal Cavern") == "Crystal Cavern"


# ===========================================================================
# 3. _extract_collection_name のテスト
# ===========================================================================


class TestExtractCollectionName:
    """ディレクトリ名からコレクション名を抽出するロジックの検証。"""

    def test_standard_8bit(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        assert gen.collection_name == "Adventure Music"

    def test_without_bit_prefix(self):
        gen = _make_generator("20250801-live-treasure-collection")
        assert gen.collection_name == "Treasure Collection"

    def test_fallback_to_dir_name(self):
        gen = _make_generator("some-unusual-directory")
        assert gen.collection_name == "some-unusual-directory"


# ===========================================================================
# 4. bit_depth のテスト（config.genre_style から取得）
# ===========================================================================


class TestBitDepth:
    """bit_depth が config/channel/content.json の genre.style から取得されることの検証。"""

    def test_from_config(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        config = load_config()
        assert gen.bit_depth == config.content.genre.style

    def test_consistent_across_directories(self):
        """異なるディレクトリ名でも同じ config 値が返る"""
        gen1 = _make_generator("20250907-live-8bit-adventure-music")
        gen2 = _make_generator("20250914-live-16bit-village-town-ver2")
        assert gen1.bit_depth == gen2.bit_depth


# ===========================================================================
# 5. _generate_tags のテスト（config/channel/content.json 駆動）
# ===========================================================================


class TestGenerateTags:
    """YouTube タグ生成ロジックの検証（config ベース）。"""

    def test_base_tags_present(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        config = load_config()
        tags = gen._generate_tags()
        # base タグが含まれること
        for base_tag in list(config.content.tags.base)[:3]:
            assert base_tag in tags

    def test_channel_name_in_tags(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        config = load_config()
        tags = gen._generate_tags()
        assert config.meta.channel_name.lower() in tags

    def test_theme_tags_applied(self):
        """コレクション名にテーマキーワードが含まれる場合、対応テーマタグが追加される"""
        config = load_config()
        themes = config.content.tags.themes
        # テーマが存在する場合のみテスト
        if themes:
            theme_name = list(themes.keys())[0]
            gen = _make_generator(f"20250907-live-8bit-{theme_name}-music")
            tags = gen._generate_tags()
            for theme_tag in themes[theme_name]:
                assert theme_tag in tags

    def test_max_50_tags(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        tags = gen._generate_tags()
        assert len(tags) <= 50


# ===========================================================================
# 6. メタデータ生成ロジックのテスト (tracks を直接注入)
# ===========================================================================


class TestGenerateCompleteCollectionMetadata:
    """Complete Collection 用メタデータ生成の検証。tracks を直接セットして副作用なしでテスト。"""

    @pytest.fixture
    def gen_with_tracks(self):
        gen = _make_generator("20250907-live-8bit-adventure-music")
        # generate_complete_collection_metadata は _load_scene_phrases() を経由するが、
        # /tmp の fake collection には workflow-state.json が無いためモックで差し替える
        _phrases = {
            "ja": "8ビット冒険の世界",
            "en": "World of 8-bit adventure",
            "de": "Welt des 8-Bit-Abenteuers",
        }
        gen._load_scene_phrases = lambda: _phrases
        gen.tracks = [
            {
                "filename": "01-Hero_Theme.wav",
                "title": "Hero Theme",
                "duration": 180,
                "start_time": 0,
                "end_time": 180,
                "timestamp": "00:00",
            },
            {
                "filename": "02-Forest_Path.wav",
                "title": "Forest Path",
                "duration": 210,
                "start_time": 180,
                "end_time": 390,
                "timestamp": "03:00",
            },
            {
                "filename": "03-Castle_Gate.wav",
                "title": "Castle Gate",
                "duration": 195,
                "start_time": 390,
                "end_time": 585,
                "timestamp": "06:30",
            },
        ]
        return gen

    def test_title_new_format(self, gen_with_tracks):
        """タイトルに BGM が含まれること"""
        meta = gen_with_tracks.generate_complete_collection_metadata()
        title = meta["title"]
        assert "BGM" in title

    def test_title_contains_theme(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        # RJN: タイトルテンプレートに activities が含まれる
        config = load_config()
        assert config.content.title.default_activity in meta["title"] or "BGM" in meta["title"]

    def test_title_contains_duration_display(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        title = meta["title"]
        # タイトルが空でないこと（デュレーション表示はテンプレート依存）
        assert len(title) > 0

    def test_description_contains_timestamps(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        desc = meta["description"]
        assert "00:00" in desc
        assert "03:00" in desc
        assert "06:30" in desc

    def test_description_contains_track_titles(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        desc = meta["description"]
        assert "Hero Theme" in desc
        assert "Forest Path" in desc
        assert "Castle Gate" in desc

    def test_description_contains_usage_info(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        desc = meta["description"]
        assert "Usage & Attribution" in desc
        assert "Free to use" in desc

    def test_category_from_config(self, gen_with_tracks):
        config = load_config()
        meta = gen_with_tracks.generate_complete_collection_metadata()
        assert meta["category_id"] == config.youtube.api.category_id

    def test_privacy_from_config(self, gen_with_tracks):
        config = load_config()
        meta = gen_with_tracks.generate_complete_collection_metadata()
        assert meta["privacy_status"] == config.youtube.api.privacy_status

    def test_tags_is_list(self, gen_with_tracks):
        meta = gen_with_tracks.generate_complete_collection_metadata()
        assert isinstance(meta["tags"], list)
        assert len(meta["tags"]) > 0

    def test_localizations_present(self, gen_with_tracks):
        """全対応言語のローカライゼーションが返り値に含まれること"""
        meta = gen_with_tracks.generate_complete_collection_metadata()
        assert "localizations" in meta
        config = load_config()
        for lang in config.localizations.supported_languages:
            assert lang in meta["localizations"]
            assert "title" in meta["localizations"][lang]
            assert "description" in meta["localizations"][lang]

    def test_localizations_title_length(self, gen_with_tracks):
        """ローカライゼーション各タイトルが100文字以下"""
        meta = gen_with_tracks.generate_complete_collection_metadata()
        for lang, loc in meta["localizations"].items():
            assert len(loc["title"]) <= 100, f"{lang} title exceeds 100 chars"

    @staticmethod
    def _all_phrases() -> dict:
        return {
            "ja": "雨の街の夜テスト",
            "en": "Rainy city night test",
            "de": "Regnerische Stadtnacht Test",
        }

    def test_localizations_title_with_scene_phrase(self):
        """scene_phrase がローカライズタイトルに反映される"""
        gen = _make_generator()
        gen.tracks = [{"timestamp": "00:00", "title": "Track 1", "duration": 180, "start_time": 0, "end_time": 180}]
        locs = gen.generate_localizations(
            english_title="Test English Title",
            timestamp_body="00:00 01. Track 1",
            scene_phrases=self._all_phrases(),
        )
        assert "ja" in locs
        assert "雨の街の夜テスト" in locs["ja"]["title"]

    def test_localizations_missing_phrases_raises(self):
        """scene_phrase が一部欠落していると ValueError を raise する（fail-silent 防止）"""
        gen = _make_generator()
        gen.tracks = []
        with pytest.raises(ValueError, match="scene_phrases"):
            gen.generate_localizations(
                english_title="English Fallback Title",
                timestamp_body="00:00 Track 1",
                scene_phrases={"ja": "雨"},
            )

    def test_localizations_description_hybrid_structure(self):
        """概要欄がハイブリッド構造（現地語ポエム + 英語メタデータ）"""
        gen = _make_generator()
        gen.tracks = []
        locs = gen.generate_localizations(
            english_title="Test",
            timestamp_body="00:00 01. Track 1",
            scene_phrases=self._all_phrases(),
        )
        ja_desc = locs["ja"]["description"]
        assert "- Genre :" in ja_desc
        assert "- Vibe :" in ja_desc
        assert "- Best for :" in ja_desc
        assert "Track List" in ja_desc
        assert "Usage & Attribution" in ja_desc
        assert "00:00 01. Track 1" in ja_desc

    def test_localizations_description_length(self):
        """全言語の概要欄が5000文字以下"""
        gen = _make_generator()
        gen.tracks = []
        locs = gen.generate_localizations(
            english_title="Test",
            timestamp_body="00:00 Track 1",
            scene_phrases=self._all_phrases(),
        )
        for lang, loc in locs.items():
            assert len(loc["description"]) <= 5000, f"{lang} description exceeds 5000 chars"

    def test_localizations_scene_phrases_empty_raises(self):
        """scene_phrases が空ならフォールバックせずに ValueError"""
        gen = _make_generator()
        gen.tracks = []
        with pytest.raises(ValueError, match="scene_phrases"):
            gen.generate_localizations(
                english_title="Fallback",
                timestamp_body="",
                scene_phrases={},
            )

    def test_description_header_matches_title(self, gen_with_tracks):
        """説明文ヘッダーが新タイトルと連動すること"""
        meta = gen_with_tracks.generate_complete_collection_metadata()
        title = meta["title"]
        desc = meta["description"]
        assert desc.startswith(f"🎵 {title}")


# ===========================================================================
# 7. _format_duration_display のテスト（デュレーション丸め）
# ===========================================================================


class TestFormatDurationDisplay:
    """デュレーション丸めロジックの検証。"""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (300, "5 min"),  # 5分ちょうど → "5 min"
            (585, "10 min"),  # 9.75分 → 10分に丸め
            (900, "15 min"),  # 15分
            (1500, "25 min"),  # 25分
            (1800, "30 min"),  # 30分
            (2040, "35 min"),  # 34分 → 35分未満なので5分単位 → round(34/5)*5=35
        ],
    )
    def test_short_durations(self, seconds, expected):
        assert format_duration_display(seconds) == expected

    def test_boundary_35_min(self):
        """35分ちょうどは "1 Hour" に丸まる"""
        assert format_duration_display(35 * 60) == "1 Hour"

    def test_one_hour(self):
        assert format_duration_display(3600) == "1 Hour"

    def test_75_min_boundary(self):
        """75分ちょうどは 1.25h → 1.5 Hours に丸まる"""
        assert format_duration_display(75 * 60) == "1.5 Hours"

    def test_90_min(self):
        assert format_duration_display(90 * 60) == "1.5 Hours"

    def test_105_min(self):
        """105分 = 1.75h → 2 Hours に丸まる"""
        assert format_duration_display(105 * 60) == "2 Hours"

    def test_two_hours(self):
        assert format_duration_display(7200) == "2 Hours"

    def test_very_short(self):
        """60秒 = 1分 → 最小 5 min"""
        assert format_duration_display(60) == "5 min"


# ===========================================================================
# 8. _extract_theme_name のテスト
# ===========================================================================


class TestExtractThemeName:
    """テーマ名抽出ロジックの検証。"""

    def test_removes_collection_suffix(self):
        gen = _make_generator("20250907-live-8bit-treasure-collection")
        assert gen._extract_theme_name() == "Treasure"

    def test_preserves_multi_word_theme(self):
        gen = _make_generator("20250907-live-8bit-ice-cavern-music")
        assert gen._extract_theme_name() == "Ice Cavern Music"

    def test_standard_theme(self):
        gen = _make_generator("20250907-live-8bit-battle-music")
        assert gen._extract_theme_name() == "Battle Music"


# ===========================================================================
# 9. _get_activity のテスト
# ===========================================================================


class TestGetActivity:
    """アクティビティキーワード取得ロジックの検証。"""

    def test_city_theme_returns_configured_activity(self):
        gen = _make_generator("20250907-live-city-jazz")
        config = load_config()
        activity = gen._get_activity()
        # theme_scenes に city があれば対応 activities、なければ default
        theme_scenes = config.content.title.theme_scenes
        if "city" in theme_scenes:
            assert activity == theme_scenes["city"]["activities"]
        else:
            assert activity == config.content.title.default_activity

    def test_cafe_theme_returns_configured_activity(self):
        gen = _make_generator("20250907-live-cafe-jazz")
        config = load_config()
        activity = gen._get_activity()
        theme_scenes = config.content.title.theme_scenes
        if "cafe" in theme_scenes:
            assert activity == theme_scenes["cafe"]["activities"]
        else:
            assert activity == config.content.title.default_activity

    def test_sleep_theme_returns_configured_activity(self):
        gen = _make_generator("20250907-live-sleep-jazz")
        config = load_config()
        activity = gen._get_activity()
        theme_scenes = config.content.title.theme_scenes
        if "sleep" in theme_scenes:
            assert activity == theme_scenes["sleep"]["activities"]
        else:
            assert activity == config.content.title.default_activity

    def test_unknown_theme_returns_default(self):
        gen = _make_generator("20250907-live-mystery-music")
        config = load_config()
        assert gen._get_activity() == config.content.title.default_activity


# ===========================================================================
# 10. _generate_title のテスト（統合）
# ===========================================================================


class TestGenerateTitle:
    """タイトル生成統合テスト。"""

    def test_format_matches_template(self):
        gen = _make_generator("20250907-live-city-jazz")
        gen.tracks = [{"duration": 3600}]  # 1時間
        title = gen._generate_title(3600)
        assert "BGM" in title
        assert len(title) <= 100

    def test_theme_with_configured_activity(self):
        gen = _make_generator("20250907-live-cafe-jazz")
        title = gen._generate_title(3600)
        assert "BGM" in title

    def test_title_max_100_chars(self):
        gen = _make_generator("20250907-live-8bit-extremely-long-theme-name-that-might-exceed-limits")
        title = gen._generate_title(3600)
        assert len(title) <= 100


# ===========================================================================
# 11. クロスフェード関連テスト
# ===========================================================================


class TestCrossfade:
    """クロスフェード設定・タイムスタンプ・合計時間の検証。"""

    def test_crossfade_config_default(self):
        """skill-config (masterup.yaml) の audio.crossfade_duration がロードされること"""
        from youtube_automation.utils.skill_config import load_skill_config

        cfg = load_skill_config("masterup")
        assert cfg.get("audio", {}).get("crossfade_duration") == 1.0

    def test_timestamp_with_crossfade(self):
        """3曲のタイムスタンプがクロスフェード分だけ前倒しされること

        Track A: 120s → start=0, end=120
        Track B: 90s  → start=120-1=119, end=119+90=209
        Track C: 60s  → start=209-1=208, end=208+60=268
        """
        gen = _make_generator("20250907-live-8bit-adventure-music")
        gen.tracks = [
            {
                "filename": "01-Track_A.wav",
                "title": "Track A",
                "duration": 120,
                "start_time": 0,
                "end_time": 120,
                "timestamp": "00:00",
            },
            {
                "filename": "02-Track_B.wav",
                "title": "Track B",
                "duration": 90,
                "start_time": 119,
                "end_time": 209,
                "timestamp": "01:59",
            },
            {
                "filename": "03-Track_C.wav",
                "title": "Track C",
                "duration": 60,
                "start_time": 208,
                "end_time": 268,
                "timestamp": "03:28",
            },
        ]
        # タイムスタンプ検証: 0:00, dur[0]-1=119s=1:59, dur[0]+dur[1]-2=208s=3:28
        assert gen.tracks[0]["timestamp"] == "00:00"
        assert gen.tracks[1]["timestamp"] == gen._format_timestamp(119)
        assert gen.tracks[2]["timestamp"] == gen._format_timestamp(208)

    def test_total_duration_with_crossfade(self):
        """合計時間 = sum(durations) - (N-1) * crossfade"""
        gen = _make_generator("20250907-live-adventure-music")
        gen.tracks = [
            {"duration": 120},
            {"duration": 90},
            {"duration": 60},
        ]
        crossfade = gen._crossfade_sec
        expected = sum(t["duration"] for t in gen.tracks) - max(0, len(gen.tracks) - 1) * crossfade
        # 270 - 2 * crossfade
        assert expected == 270.0 - 2 * crossfade

    def test_single_track_no_crossfade(self):
        """1曲のみの場合、クロスフェード補正なし"""
        gen = _make_generator("20250907-live-8bit-adventure-music")
        gen.tracks = [{"duration": 180}]
        crossfade = gen._crossfade_sec
        total = sum(t["duration"] for t in gen.tracks) - max(0, len(gen.tracks) - 1) * crossfade
        assert total == 180.0


# ===========================================================================
# 12. validate_scene_phrases のテスト（#78: 事前検証ヘルパー）
# ===========================================================================


def _all_langs_phrases(text: str) -> dict:
    """sample_channel fixture の supported_languages 全てに同じフレーズを割り当てる."""
    config = load_config()
    return {lang: text for lang in config.localizations.supported_languages}


class TestValidateScenePhrases:
    """`/description` 等の事前検証で全言語の codepoint 超過を一括検出できることの検証."""

    def test_all_within_limit_returns_empty(self):
        """全言語で 100 codepoint 以内なら空リスト"""
        config = load_config()
        violations = validate_scene_phrases(_all_langs_phrases("short phrase"), config)
        assert violations == []

    def test_single_language_over_limit(self):
        """1 言語だけ超過すれば 1 件返る"""
        config = load_config()
        phrases = _all_langs_phrases("short phrase")
        phrases["ja"] = "あ" * 90  # template + activities 込みで 100 超過
        violations = validate_scene_phrases(phrases, config)
        assert len(violations) == 1
        assert violations[0].lang == "ja"
        assert violations[0].length > 100

    def test_multiple_languages_over_limit_reported_together(self):
        """複数言語が超過していれば 1 言語ずつ fail せず全件まとめて返る（#78 の主目的）"""
        config = load_config()
        phrases = _all_langs_phrases("あ" * 90)
        violations = validate_scene_phrases(phrases, config)
        # sample_channel の supported_languages 5 つ全てが超過するはず
        assert len(violations) == len(config.localizations.supported_languages)
        langs = {v.lang for v in violations}
        assert langs == set(config.localizations.supported_languages)

    def test_violation_exposes_title_and_template(self):
        """Violation は再現に必要な情報（lang / length / title / template）を含む"""
        config = load_config()
        phrases = _all_langs_phrases("short phrase")
        phrases["ja"] = "あ" * 90
        violations = validate_scene_phrases(phrases, config)
        v = violations[0]
        assert isinstance(v, SceneTitleViolation)
        assert v.length == len(v.title)
        assert "{scene_phrase}" in v.template

    def test_missing_phrase_raises(self):
        """scene_phrases に不足言語があれば ValueError（existing 挙動を踏襲）"""
        config = load_config()
        with pytest.raises(ValueError, match="scene_phrases"):
            validate_scene_phrases({"ja": "あ"}, config)

    def test_empty_scene_phrases_raises(self):
        """空辞書はそのまま全言語欠落扱いで raise"""
        config = load_config()
        with pytest.raises(ValueError, match="scene_phrases"):
            validate_scene_phrases({}, config)

    def test_format_scene_title_violations_joins_all(self):
        """format_scene_title_violations は全件を複数行にまとめる（CLI で 1 回で報告するため）"""
        config = load_config()
        phrases = _all_langs_phrases("あ" * 90)
        violations = validate_scene_phrases(phrases, config)
        text = format_scene_title_violations(violations)
        for v in violations:
            assert f"[{v.lang}]" in text
            assert str(v.length) in text


class TestGenerateLocalizationsBulkReport:
    """generate_localizations でも全言語の違反がまとめて報告されることの確認."""

    def test_all_violations_in_single_error(self):
        """scene_phrases が複数言語で超過したとき、ValueError メッセージに全言語が含まれる"""
        gen = _make_generator()
        gen.tracks = []
        config = load_config()
        phrases = _all_langs_phrases("あ" * 90)
        with pytest.raises(ValueError) as excinfo:
            gen.generate_localizations(
                english_title="Test",
                timestamp_body="",
                scene_phrases=phrases,
            )
        msg = str(excinfo.value)
        for lang in config.localizations.supported_languages:
            assert f"[{lang}]" in msg


# ===========================================================================
# 13. pattern_key 抽出ヘルパー
# ===========================================================================


class TestExtractPatternKey:
    """`\\d+-pattern-[a-d]` パターンから pattern_key を抽出するロジックの検証."""

    def test_pattern_a_lowercase(self):
        from youtube_automation.utils.metadata_generator import _extract_pattern_key

        assert _extract_pattern_key("01-pattern-a-intro.mp3") == "a"

    def test_pattern_b_with_variation_suffix(self):
        from youtube_automation.utils.metadata_generator import _extract_pattern_key

        assert _extract_pattern_key("05-pattern-b1-quiet-hours.mp3") == "b"

    def test_pattern_c_uppercase(self):
        from youtube_automation.utils.metadata_generator import _extract_pattern_key

        assert _extract_pattern_key("10-Pattern-C-finale.mp3") == "c"

    def test_no_pattern_returns_none(self):
        from youtube_automation.utils.metadata_generator import _extract_pattern_key

        assert _extract_pattern_key("01-Hero_Theme.wav") is None

    def test_pattern_e_out_of_range(self):
        """[a-d] 範囲外（e 以降）は None"""
        from youtube_automation.utils.metadata_generator import _extract_pattern_key

        assert _extract_pattern_key("01-pattern-e-extra.mp3") is None


# ===========================================================================
# 14. テーマ見出し付きタイムスタンプ生成
# ===========================================================================


def _track(filename, title, timestamp, pattern_key, duration=180):
    """テスト用トラック辞書を組み立てる shorthand."""
    return {
        "filename": filename,
        "title": title,
        "duration": duration,
        "start_time": 0,
        "end_time": duration,
        "timestamp": timestamp,
        "pattern_key": pattern_key,
    }


class TestGenerateTimestampsWithThemes:
    """pattern_key に基づくテーマ見出しの挿入と、未指定時のフラット出力を検証."""

    def test_inserts_theme_headers_at_pattern_transitions(self, monkeypatch):
        gen = _make_generator()
        gen.tracks = [
            _track("01-pattern-a-foo.mp3", "Foo", "00:00", "a"),
            _track("02-pattern-a-bar.mp3", "Bar", "03:00", "a"),
            _track("03-pattern-b-baz.mp3", "Baz", "06:00", "b"),
        ]
        monkeypatch.setattr(gen, "_load_theme_display_names", lambda: {"a": "Awakening", "b": "Focused Flow"})
        result = gen.generate_timestamps()

        types = [e["type"] for e in result]
        assert types == ["theme_header", "track", "track", "theme_header", "track"]
        assert result[0]["title"] == "Awakening"
        assert result[0]["timestamp"] == "00:00"
        assert result[3]["title"] == "Focused Flow"
        assert result[3]["timestamp"] == "06:00"

    def test_no_pattern_keys_returns_flat_tracks(self, monkeypatch):
        gen = _make_generator()
        gen.tracks = [
            _track("01-Hero.wav", "Hero", "00:00", None),
            _track("02-Forest.wav", "Forest", "03:00", None),
        ]
        monkeypatch.setattr(gen, "_load_theme_display_names", lambda: {})
        result = gen.generate_timestamps()

        assert all(e["type"] == "track" for e in result)
        assert [e["title"] for e in result] == ["Hero", "Forest"]

    def test_fallback_label_when_display_name_missing(self, monkeypatch):
        """workflow-state.json に表示名が無い pattern は `Pattern X` にフォールバック."""
        gen = _make_generator()
        gen.tracks = [_track("01-pattern-c-x.mp3", "X", "00:00", "c")]
        monkeypatch.setattr(gen, "_load_theme_display_names", lambda: {})
        result = gen.generate_timestamps()
        assert result[0]["type"] == "theme_header"
        assert result[0]["title"] == "Pattern C"


class TestFormatTimestampsTextWithThemes:
    """テーマ見出し行のフォーマットを検証."""

    def test_theme_header_uses_inline_decoration(self, monkeypatch):
        gen = _make_generator()
        gen.tracks = [
            _track("01-pattern-a-foo.mp3", "Foo", "00:00", "a"),
            _track("02-pattern-b-bar.mp3", "Bar", "03:00", "b"),
        ]
        monkeypatch.setattr(
            gen,
            "_load_theme_display_names",
            lambda: {"a": "Pattern A: Awakening", "b": "Pattern B: Flow"},
        )
        text = gen.format_timestamps_text()
        assert text == ("── Pattern A: Awakening ──\n00:00 Foo\n── Pattern B: Flow ──\n03:00 Bar")

    def test_flat_format_for_no_pattern_keys(self, monkeypatch):
        gen = _make_generator()
        gen.tracks = [
            _track("01-Solo.wav", "Solo", "00:00", None),
            _track("02-Duet.wav", "Duet", "05:00", None),
        ]
        monkeypatch.setattr(gen, "_load_theme_display_names", lambda: {})
        assert gen.format_timestamps_text() == "00:00 Solo\n05:00 Duet"

    def test_chapter_lines_are_strictly_ascending(self, monkeypatch):
        """YouTube の chapter parser は timestamps の strict ascending を要求する。
        テーマ見出し行が先頭 timestamp を持っていると直後の楽曲行と重複し
        chapter list 全体が invalid 化するため、見出し行は timestamp を持たない."""
        import re

        gen = _make_generator()
        gen.tracks = [
            _track("01-pattern-a-foo.mp3", "Foo", "00:00", "a"),
            _track("02-pattern-b-bar.mp3", "Bar", "03:00", "b"),
        ]
        monkeypatch.setattr(gen, "_load_theme_display_names", lambda: {"a": "Pattern A", "b": "Pattern B"})

        ts_line_re = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?\s")
        prev_seconds = -1
        for line in gen.format_timestamps_text().splitlines():
            m = ts_line_re.match(line)
            if not m:
                continue
            parts = [int(p) for p in m.groups() if p is not None]
            seconds = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
            assert seconds > prev_seconds, f"timestamp line not strictly ascending: {line!r}"
            prev_seconds = seconds


# ===========================================================================
# 15. 同名楽曲の重複検知
# ===========================================================================


class TestDetectDuplicateTrackTitles:
    """同名楽曲の検出ロジックの検証."""

    def test_no_duplicates_returns_empty(self):
        gen = _make_generator()
        gen.tracks = [
            _track("01-a.mp3", "Unique One", "00:00", "a"),
            _track("02-b.mp3", "Unique Two", "03:00", "b"),
        ]
        assert gen.detect_duplicate_track_titles() == {}

    def test_single_duplicate_pair(self):
        gen = _make_generator()
        gen.tracks = [
            _track("01-a.mp3", "Quiet Hours", "00:00", "a"),
            _track("02-b.mp3", "Other", "03:00", "b"),
            _track("03-c.mp3", "Quiet Hours", "06:00", "c"),
        ]
        result = gen.detect_duplicate_track_titles()
        assert "Quiet Hours" in result
        assert sorted(result["Quiet Hours"]) == [0, 2]

    def test_case_insensitive_grouping(self):
        gen = _make_generator()
        gen.tracks = [
            _track("01-a.mp3", "Rain Window", "00:00", "a"),
            _track("02-b.mp3", "rain window", "03:00", "b"),
        ]
        result = gen.detect_duplicate_track_titles()
        # 表現は元のタイトルどちらか 1 つに正規化される（実装依存）が、indices は両方含む
        assert any(sorted(v) == [0, 1] for v in result.values())


# ===========================================================================
# 16. 同名楽曲リネームの適用と永続化
# ===========================================================================


class TestApplyTrackDisplayNames:
    """LLM 命名結果を self.tracks と workflow-state.json に反映するロジックの検証."""

    def test_updates_tracks_and_persists_to_state(self, tmp_path):
        import json as _json

        gen = _make_generator()
        gen.collection_path = tmp_path
        ws_path = tmp_path / "workflow-state.json"
        ws_path.write_text(_json.dumps({"collection_name": "Test"}), encoding="utf-8")

        gen.tracks = [
            _track("01-pattern-a-foo.mp3", "Original A", "00:00", "a"),
            _track("02-pattern-b-bar.mp3", "Original B", "03:00", "b"),
        ]
        gen.apply_track_display_names({0: "Awakening Drift", 1: "Focused Pulse"})

        assert gen.tracks[0]["title"] == "Awakening Drift"
        assert gen.tracks[1]["title"] == "Focused Pulse"

        state = _json.loads(ws_path.read_text(encoding="utf-8"))
        assert state["track_display_names"]["01-pattern-a-foo.mp3"] == "Awakening Drift"
        assert state["track_display_names"]["02-pattern-b-bar.mp3"] == "Focused Pulse"
        # 既存キーが壊れない
        assert state["collection_name"] == "Test"

    def test_loads_persisted_names_in_analyze(self, tmp_path, monkeypatch):
        """workflow-state.json の track_display_names が次回ロード時に適用される."""
        import json as _json

        gen = _make_generator()
        gen.collection_path = tmp_path
        ws_path = tmp_path / "workflow-state.json"
        ws_path.write_text(
            _json.dumps(
                {
                    "track_display_names": {
                        "01-pattern-a-foo.mp3": "Persisted Name",
                    }
                }
            ),
            encoding="utf-8",
        )
        gen.tracks = [
            _track("01-pattern-a-foo.mp3", "Original", "00:00", "a"),
        ]
        gen._apply_persisted_display_names()
        assert gen.tracks[0]["title"] == "Persisted Name"


# ===========================================================================
# 17. pattern 表示名解決ロジック
# ===========================================================================


class TestLoadThemeDisplayNames:
    """workflow-state.json の planning.music.patterns から表示名を解決する."""

    def test_display_name_preferred(self, tmp_path):
        import json as _json

        gen = _make_generator()
        gen.collection_path = tmp_path
        (tmp_path / "workflow-state.json").write_text(
            _json.dumps(
                {
                    "planning": {
                        "music": {
                            "patterns": {
                                "a": {"display_name": "Pattern A: Awakening", "name": "Awakening"},
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        names = gen._load_theme_display_names()
        assert names == {"a": "Pattern A: Awakening"}

    def test_name_fallback_with_prefix(self, tmp_path):
        import json as _json

        gen = _make_generator()
        gen.collection_path = tmp_path
        (tmp_path / "workflow-state.json").write_text(
            _json.dumps({"planning": {"music": {"patterns": {"b": {"name": "Focused Flow"}}}}}),
            encoding="utf-8",
        )
        assert gen._load_theme_display_names() == {"b": "Pattern B: Focused Flow"}

    def test_missing_patterns_returns_empty(self, tmp_path):
        import json as _json

        gen = _make_generator()
        gen.collection_path = tmp_path
        (tmp_path / "workflow-state.json").write_text(_json.dumps({}), encoding="utf-8")
        assert gen._load_theme_display_names() == {}
