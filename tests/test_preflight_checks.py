"""preflight_checks の各 check_* 関数の挙動検証."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.utils.preflight_checks import (
    check_chapter_count,
    check_chapter_variation_suffix,
    check_descriptions_md_parseability,
    check_duration,
    check_low_cpm_localization_languages,
    check_required_localization_languages,
    check_suno_genre_line_char_limit,
    check_tags_count,
    check_tags_yt_chars,
    check_thumbnail_skill_config,
    check_title_duplicate_warnings,
    check_title_template_compliance,
    extract_descriptions_md_tags,
)


class TestCheckTagsCount:
    def test_none_skips_check(self) -> None:
        assert check_tags_count(["a"], None) is None

    def test_under_min_returns_message(self) -> None:
        msg = check_tags_count(["a", "b"], 5)
        assert msg == "tags count: 2 (min 5)"

    def test_at_min_passes(self) -> None:
        assert check_tags_count(["a", "b", "c"], 3) is None

    def test_over_min_passes(self) -> None:
        assert check_tags_count(["a"] * 50, 10) is None


class TestCheckTagsYtChars:
    def test_below_limit_passes(self) -> None:
        assert check_tags_yt_chars(["short"]) is None

    def test_exactly_at_limit_passes(self) -> None:
        # 9 文字 × 50 + カンマ 49 = 499 → 500 制限内
        tags = ["123456789"] * 50
        assert check_tags_yt_chars(tags) is None

    def test_over_limit_returns_message(self) -> None:
        # スペース付き 11 文字 → quotation 込み 13、× 50 + カンマ 49 = 699
        tags = ["lofi  beats"] * 50
        msg = check_tags_yt_chars(tags)
        assert msg is not None
        assert msg.startswith("tags YT chars (quoted):")
        assert "/ 500" in msg

    def test_custom_limit(self) -> None:
        assert check_tags_yt_chars(["abc"], limit=2) == "tags YT chars (quoted): 3 / 2"


class TestCheckDuration:
    def test_both_none_skips(self) -> None:
        assert check_duration(123.0, None, None) is None

    def test_within_range_passes(self) -> None:
        # 2h30m
        assert check_duration(9000, 8520, 9240) is None

    def test_under_min_fails(self) -> None:
        # 1h17m vs target 2h22m〜2h34m
        msg = check_duration(4620, 8520, 9240)
        assert msg is not None
        assert "1h17m" in msg
        assert "2h22m〜2h34m" in msg

    def test_over_max_fails(self) -> None:
        # 2h46m vs target 2h22m〜2h34m
        msg = check_duration(9960, 8520, 9240)
        assert msg is not None
        assert "2h46m" in msg
        assert "2h22m〜2h34m" in msg

    def test_only_min_set(self) -> None:
        # min のみ。下回るときは fail、上回るときは pass
        assert check_duration(60, 100, None) is not None
        assert check_duration(200, 100, None) is None

    def test_only_max_set(self) -> None:
        assert check_duration(200, None, 100) is not None
        assert check_duration(50, None, 100) is None


class TestCheckChapterCount:
    def test_within_limit_passes(self) -> None:
        assert check_chapter_count(14, 100) is None

    def test_at_limit_passes(self) -> None:
        assert check_chapter_count(100, 100) is None

    def test_over_limit_returns_message(self) -> None:
        msg = check_chapter_count(120, 100)
        assert msg is not None
        assert "120" in msg
        assert "chapter_max=100" in msg

    def test_small_chapter_max(self) -> None:
        # チャンネルごとに小さい chapter_max を設定したケース
        msg = check_chapter_count(14, 10)
        assert msg is not None
        assert "14" in msg
        assert "chapter_max=10" in msg


class TestCheckChapterVariationSuffix:
    def test_per_track_names_pass(self) -> None:
        # 個別トラックの曲名は v 末尾を含まないので通過する
        lines = [
            "00:00 After the Last Visitor",
            "06:45 Rainy Studio Loop",
            "13:20 Dorm Window Dawn",
            "20:00 Library After Hours",
            "26:35 Rain Nest Reverie",
        ]
        assert check_chapter_variation_suffix(lines) is None


class TestInitialSetupChecks:
    def test_suno_genre_line_over_style_limit_warns(self) -> None:
        msg = check_suno_genre_line_char_limit({"genre_line": "x" * 121, "style_char_limit": 120})

        assert msg is not None
        assert "121 / 120" in msg
        assert "config/skills/suno.yaml::genre_line" in msg

    def test_suno_genre_line_at_style_limit_passes(self) -> None:
        assert check_suno_genre_line_char_limit({"genre_line": "x" * 120, "style_char_limit": 120}) is None

    def test_thumbnail_config_detects_empty_refs_and_tbd_composition(self, tmp_path: Path) -> None:
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": [], "path_base": "channel_dir"},
                    "composition_rules": {
                        "environment": "TBD",
                        "character_size": "TBD",
                        "character_pose": "TBD",
                        "allowed_actions": "TBD",
                        "ng_actions": "TBD",
                        "background": "TBD",
                    },
                }
            }
        }

        issues = check_thumbnail_skill_config(tmp_path, cfg)

        assert any("reference_images.default" in issue for issue in issues)
        assert any("composition_rules" in issue and "environment" in issue for issue in issues)

    def test_thumbnail_config_detects_tbd_reference(self, tmp_path: Path) -> None:
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": "TBD"},
                    "composition_rules": {
                        "environment": "desk",
                        "character_size": "medium",
                        "character_pose": "sitting",
                        "allowed_actions": "reading",
                        "ng_actions": "no text",
                        "background": "warm room",
                    },
                }
            }
        }

        issues = check_thumbnail_skill_config(tmp_path, cfg)

        assert any("reference_images.default" in issue and "TBD" in issue for issue in issues)

    def test_thumbnail_config_detects_unexpanded_template_composition(self, tmp_path: Path) -> None:
        ref = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "alpha.jpg"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"jpg")
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": ["data/thumbnail_compare/benchmark/alpha.jpg"]},
                    "composition_rules": {
                        "environment": "{{ENVIRONMENT}}",
                        "character_size": "medium",
                        "character_pose": "sitting",
                        "allowed_actions": "reading",
                        "ng_actions": "no text",
                        "background": "warm room",
                    },
                }
            }
        }

        issues = check_thumbnail_skill_config(tmp_path, cfg)

        assert any("composition_rules" in issue and "environment" in issue for issue in issues)

    def test_thumbnail_config_detects_missing_reference_path(self, tmp_path: Path) -> None:
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": ["data/thumbnail_compare/benchmark/missing.jpg"]},
                    "composition_rules": {
                        "environment": "desk",
                        "character_size": "medium",
                        "character_pose": "sitting",
                        "allowed_actions": "reading",
                        "ng_actions": "no text",
                        "background": "warm room",
                    },
                }
            }
        }

        issues = check_thumbnail_skill_config(tmp_path, cfg)

        assert len(issues) == 1
        assert "存在しない参照画像" in issues[0]

    def test_thumbnail_config_detects_refs_below_max_attempts(self, tmp_path: Path) -> None:
        ref = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "alpha.jpg"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"jpg")
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "single_step": {"max_attempts": 2},
                    "reference_images": {"default": ["data/thumbnail_compare/benchmark/alpha.jpg"]},
                    "composition_rules": {
                        "environment": "desk",
                        "character_size": "medium",
                        "character_pose": "sitting",
                        "allowed_actions": "reading",
                        "ng_actions": "no text",
                        "background": "warm room",
                    },
                }
            }
        }

        issues = check_thumbnail_skill_config(tmp_path, cfg)

        assert len(issues) == 1
        assert "必要枚数未満" in issues[0]
        assert "max_attempts=2" in issues[0]
        assert "unique_references=1" in issues[0]

    def test_thumbnail_config_valid_setup_passes(self, tmp_path: Path) -> None:
        ref = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "alpha.jpg"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"jpg")
        cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "single_step": {"max_attempts": 1},
                    "reference_images": {"default": ["data/thumbnail_compare/benchmark/alpha.jpg"]},
                    "composition_rules": {
                        "environment": "desk",
                        "character_size": "medium",
                        "character_pose": "sitting",
                        "allowed_actions": "reading",
                        "ng_actions": "no text",
                        "background": "warm room",
                    },
                }
            }
        }

        assert check_thumbnail_skill_config(tmp_path, cfg) == []

    def test_descriptions_md_parseability_detects_heading_body_annotation(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タイトル案\n"
            "<!-- code comment -->\n"
            "```\n"
            "Title\n"
            "```\n"
            "## Complete Collection 概要欄\n"
            "```\n"
            "Body\n"
            "```\n"
            "## タグ（YouTube タグ欄）\n"
            "```\n"
            "tag\n"
            "```\n",
            encoding="utf-8",
        )

        msg = check_descriptions_md_parseability(p)

        assert msg is not None
        assert "descriptions.md parse failed" in msg
        assert "タイトル案" in msg

    def test_v_suffix_detected(self) -> None:
        lines = [
            "00:00 Pattern A v1",
            "10:00 Pattern A v2",
            "20:00 Pattern A v3",
        ]
        msg = check_chapter_variation_suffix(lines)
        assert msg is not None
        assert "3 lines" in msg

    def test_roman_suffix_detected(self) -> None:
        lines = [
            "00:00 Pattern I",
            "10:00 Pattern II",
            "20:00 Pattern III",
            "30:00 Pattern VIII",
        ]
        msg = check_chapter_variation_suffix(lines)
        assert msg is not None
        assert "4 lines" in msg

    def test_mixed_per_track_with_one_variation_detected(self) -> None:
        # ほとんど per-track でも 1 件でも v 末尾が混じれば検出
        lines = [
            "00:00 After the Last Visitor",
            "06:45 Rainy Studio Loop",
            "13:20 Pattern v1",
        ]
        msg = check_chapter_variation_suffix(lines)
        assert msg is not None
        assert "1 lines" in msg

    def test_word_ending_in_v_not_detected(self) -> None:
        # 単語末尾の v は単独の v[1-9] パターンには合致しないため誤検知しない
        lines = [
            "00:00 Cinematic Move",
            "10:00 Smooth Groove",
        ]
        assert check_chapter_variation_suffix(lines) is None

    def test_track_titles_with_capital_letters_not_detected(self) -> None:
        # 末尾が普通の単語末尾なら通過すること（誤検知防止のサンプル）
        lines = [
            "00:00 After Midnight",
            "10:00 Empty Gallery",
            "20:00 Last Train Home",
        ]
        assert check_chapter_variation_suffix(lines) is None


class TestCheckRequiredLocalizationLanguages:
    def test_passes_when_high_cpm_languages_are_present(self) -> None:
        assert check_required_localization_languages(["ja", "en", "de"]) is None

    def test_passes_when_extra_languages_are_present(self) -> None:
        assert check_required_localization_languages(["ja", "en", "de", "ko"]) is None

    def test_returns_message_when_one_high_cpm_language_is_missing(self) -> None:
        msg = check_required_localization_languages(["ja", "en"])

        assert msg is not None
        assert "de" in msg

    def test_returns_message_when_all_high_cpm_languages_are_missing(self) -> None:
        msg = check_required_localization_languages([])

        assert msg is not None
        assert "de" in msg
        assert "en" in msg
        assert "ja" in msg


class TestCheckLowCpmLocalizationLanguages:
    def test_passes_without_low_cpm_languages(self) -> None:
        assert check_low_cpm_localization_languages(["ja", "en", "de"]) is None

    def test_returns_message_for_low_cpm_languages(self) -> None:
        msg = check_low_cpm_localization_languages(["ja", "en", "de", "ko", "zh-CN"])

        assert msg is not None
        assert "ko" in msg
        assert "zh-CN" in msg

    def test_ignores_languages_outside_low_cpm_set(self) -> None:
        assert check_low_cpm_localization_languages(["ja", "en", "de", "fr"]) is None


class TestExtractDescriptionsMdTags:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert extract_descriptions_md_tags(tmp_path / "missing.md") is None

    def test_returns_none_when_section_missing(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text("## タイトル案\n```\nFoo\n```\n", encoding="utf-8")
        assert extract_descriptions_md_tags(p) is None

    def test_extracts_comma_separated_tags(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タグ（YouTube タグ欄）\n```\nlofi beats, jazz, study music\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) == ["lofi beats", "jazz", "study music"]

    def test_extracts_newline_separated_tags(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タグ（YouTube タグ欄）\n```\nlofi beats\njazz\nstudy\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) == ["lofi beats", "jazz", "study"]

    def test_strips_double_quotes_from_tags(self, tmp_path: Path) -> None:
        """ダブルクォートで囲まれたタグから引用符を除去する (#1096)."""
        p = tmp_path / "descriptions.md"
        p.write_text(
            '## タグ（YouTube タグ欄）\n```\n"lofi beats", "jazz", "study music"\n```\n',
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) == ["lofi beats", "jazz", "study music"]

    def test_returns_none_for_empty_section(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text("## タグ（YouTube タグ欄）\n```\n\n```\n", encoding="utf-8")
        assert extract_descriptions_md_tags(p) is None

    def test_returns_none_for_level3_tag_heading(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "### タグ（YouTube タグ欄）\n```\nlofi beats, jazz\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) is None

    def test_returns_none_for_tag_heading_typo(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タグ\n```\nlofi beats, jazz\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) is None


class TestCheckTitleTemplateCompliance:
    """`check_title_template_compliance` の鋳型逸脱・巻数表記・RHS 重複検出 (#602)."""

    # soulful-grooves チャンネルを想定した鋳型設定
    CFG = {
        "template": "{adjective} Soul/Funk {noun} | {hours} Hours of {mood}",
        "core_vocabulary": ["Soul", "Funk"],
    }
    EXISTING = [
        "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves",
        "Golden Hour Soul Flow | 4 Hours of Smooth City Funk",
    ]

    def test_compliant_title_passes(self) -> None:
        title = "Bright Funk & Soul Spirit | 3 Hours of Feel-Good Retro Grooves"
        assert check_title_template_compliance(title, self.EXISTING, self.CFG) is None

    def test_volume_notation_rejected(self) -> None:
        title = "Funky Soul Spirit Vol.2 | 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "巻数表記" in msg

    def test_part_notation_rejected(self) -> None:
        title = "Funky Soul Spirit Part 3 | 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "巻数表記" in msg

    def test_hash_number_rejected(self) -> None:
        title = "Funky Soul Spirit #2 | 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "巻数表記" in msg

    def test_trailing_roman_numeral_rejected(self) -> None:
        title = "Funky Soul Spirit III | 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "巻数表記" in msg

    def test_rhs_duplicate_allowed_when_lhs_differs(self) -> None:
        # LHS が違えば RHS が同じでも OK（タイトル全体が一意であれば許可）
        title = "Brand New Soul Funk Energy | 3 Hours of Soulful Retro Funk Grooves"
        msg = check_title_template_compliance(title, self.EXISTING, self.CFG)
        assert msg is None

    def test_full_title_duplicate_rejected(self) -> None:
        # タイトル全体が既存と完全一致する場合は弾く
        title = "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves"
        msg = check_title_template_compliance(title, self.EXISTING, self.CFG)
        assert msg is not None
        assert "タイトル全体が既存 live タイトルと完全重複" in msg

    def test_volume_notation_with_existing_rejected(self) -> None:
        # 巻数表記は RHS 重複とは独立して検出される
        title = "Funky Spirit Vol.2 | 3 Hours of Soulful Retro Funk Grooves"
        msg = check_title_template_compliance(title, self.EXISTING, self.CFG)
        assert msg is not None
        assert "巻数表記" in msg

    def test_rhs_not_matching_template_rejected(self) -> None:
        title = "Bright Funk & Soul Spirit | A Cozy Funk Mix"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "RHS が鋳型に一致しません" in msg

    def test_missing_separator_rejected(self) -> None:
        title = "Bright Funk & Soul Spirit 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "鋳型形式逸脱" in msg

    def test_missing_core_vocabulary_rejected(self) -> None:
        title = "Bright Mellow Spirit | 3 Hours of Feel-Good Retro Grooves"
        msg = check_title_template_compliance(title, [], self.CFG)
        assert msg is not None
        assert "鋳型語彙" in msg

    def test_skips_when_template_has_no_separator(self) -> None:
        # ` | ` 鋳型を使わないチャンネル（例: RPG BGM）は自動スキップ
        cfg = {"template": "{style} {theme} RPG Music - {activity} BGM [{duration_display}]"}
        title = "Epic Battle RPG Music - Gaming BGM [3:00:00]"
        assert check_title_template_compliance(title, [], cfg) is None

    def test_no_config_uses_defaults(self) -> None:
        # config 未指定でも既定鋳型（N Hours of ...）で検証できる
        title = "Bright Funk & Soul Spirit | 3 Hours of Feel-Good Retro Grooves"
        assert check_title_template_compliance(title) is None

    def test_existing_live_titles_pass(self) -> None:
        # 既存 live タイトルは自分自身を比較対象に含めなければ全て pass（回帰確認）
        for i, title in enumerate(self.EXISTING):
            others = [t for j, t in enumerate(self.EXISTING) if j != i]
            assert check_title_template_compliance(title, others, self.CFG) is None


class TestCheckTitleDuplicateWarnings:
    """企画/タイトル決定段階の早期 warning。upload preflight の fail 判定とは分離する。"""

    CFG = {
        "template": "{adjective} Soul/Funk {noun} | {hours} Hours of {mood}",
        "separator": " | ",
    }
    EXISTING = [
        "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves",
        "Golden Hour Soul Flow | 4 Hours of Smooth City Funk",
    ]

    def test_full_duplicate_warns(self) -> None:
        warnings = check_title_duplicate_warnings(
            "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves",
            self.EXISTING,
            self.CFG,
        )
        assert len(warnings) == 1
        assert "完全一致" in warnings[0]

    def test_rhs_duplicate_warns_even_when_preflight_allows_it(self) -> None:
        title = "Brand New Soul Funk Energy | 3 Hours of Soulful Retro Funk Grooves"
        assert check_title_template_compliance(title, self.EXISTING, self.CFG) is None

        warnings = check_title_duplicate_warnings(title, self.EXISTING, self.CFG)

        assert len(warnings) == 1
        assert "タイトル後半" in warnings[0]
        assert "3 Hours of Soulful Retro Funk Grooves" in warnings[0]

    def test_long_suffix_duplicate_without_separator_warns(self) -> None:
        warnings = check_title_duplicate_warnings(
            "Rainy Cafe Jazz for Work and Deep Focus",
            ["Night Cafe Piano for Work and Deep Focus"],
            {"template": "{theme} BGM"},
        )
        assert len(warnings) == 1
        assert "タイトル末尾" in warnings[0]
        assert "for Work and Deep Focus" in warnings[0]

    def test_short_suffix_overlap_is_ignored(self) -> None:
        warnings = check_title_duplicate_warnings("Rain Jazz BGM", ["Cafe Jazz BGM"], {}, min_suffix_chars=16)
        assert warnings == []
