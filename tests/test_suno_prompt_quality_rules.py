"""品質ルール (#904, #899) の回帰テスト.

suno-bgm ベースの品質ガード関数と auto_lyrics_structure の動作を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from youtube_automation.scripts.generate_suno_prompts import (
    QualityReport,
    apply_auto_lyrics_structure,
    build_prompt_entries,
    validate_5_element_order,
    validate_banned_artists,
    validate_style_char_limit,
)
from youtube_automation.utils import skill_config

_DEFAULT_YAML = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "config.default.yaml"


@pytest.fixture
def channel_dir(tmp_path, monkeypatch):
    """skill_config が参照する CHANNEL_DIR を一時ディレクトリへ向ける."""
    ch = tmp_path / "channel"
    (ch / "config" / "skills").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))
    skill_config.reset()
    yield ch
    skill_config.reset()


def _write_suno_override(channel: Path, **overrides) -> None:
    (channel / "config" / "skills" / "suno.yaml").write_text(yaml.safe_dump(overrides), encoding="utf-8")


def _write_minimal_patterns(dir_: Path, **extra_top) -> Path:
    payload: dict = {
        "title": "Test Collection",
        "mode": "instrumental",
        "tracks": 2,
        "patterns": [
            {
                "name_jp": "テスト",
                "name_en": "Test",
                "tempo": "slow",
                "scenes": ["a quiet scene description"],
            }
        ],
    }
    payload.update(extra_top)
    path = dir_ / "patterns.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate_style_char_limit
# ---------------------------------------------------------------------------


def test_style_char_limit_under_limit():
    """120 文字以内なら警告なし."""
    result = validate_style_char_limit("a" * 120, limit=120)
    assert result == []


def test_style_char_limit_over_limit():
    """120 文字超で警告."""
    result = validate_style_char_limit("a" * 121, limit=120)
    assert len(result) == 1
    assert "121 chars" in result[0]


def test_style_char_limit_exact_boundary():
    """ちょうど上限は OK."""
    result = validate_style_char_limit("x" * 120, limit=120)
    assert result == []


# ---------------------------------------------------------------------------
# validate_banned_artists
# ---------------------------------------------------------------------------


def test_banned_artists_no_match():
    """禁止アーティスト名がなければエラーなし."""
    result = validate_banned_artists("lo-fi jazz, soft piano", ["Drake", "Taylor Swift"])
    assert result == []


def test_banned_artists_match():
    """禁止アーティスト名が含まれていればエラー."""
    result = validate_banned_artists("lo-fi jazz like Drake", ["Drake", "Taylor Swift"])
    assert len(result) == 1
    assert "Drake" in result[0]


def test_banned_artists_case_insensitive():
    """大文字小文字を区別しない."""
    result = validate_banned_artists("lo-fi jazz like drake", ["Drake"])
    assert len(result) == 1


def test_banned_artists_multiple_matches():
    """複数のアーティスト名が含まれていれば複数エラー."""
    result = validate_banned_artists(
        "like Drake and Taylor Swift vibes",
        ["Drake", "Taylor Swift", "Beyonce"],
    )
    assert len(result) == 2


# ---------------------------------------------------------------------------
# validate_5_element_order
# ---------------------------------------------------------------------------


def test_5_element_order_tempo_at_end():
    """テンポ語が末尾付近なら警告なし."""
    result = validate_5_element_order("lo-fi jazz, soft piano, warm rhodes, mellow drums, slow")
    assert result == []


def test_5_element_order_tempo_at_start():
    """テンポ語が先頭にあると警告."""
    result = validate_5_element_order("slow, lo-fi jazz, soft piano")
    assert len(result) == 1
    assert "5-element order" in result[0]


def test_5_element_order_no_tempo():
    """テンポ語がなければ警告なし."""
    result = validate_5_element_order("lo-fi jazz, soft piano, warm rhodes")
    assert result == []


# ---------------------------------------------------------------------------
# apply_auto_lyrics_structure
# ---------------------------------------------------------------------------


def test_auto_lyrics_instrumental_empty():
    """インストモード + 空歌詞 → [Instrumental] + [Extended Outro]."""
    result = apply_auto_lyrics_structure("", is_vocal=False)
    assert "[Instrumental]" in result
    assert "[Extended Outro]" in result


def test_auto_lyrics_instrumental_already_tagged():
    """インストモード + 既に [Instrumental] がある → 重複追加しない."""
    lyrics = "[Instrumental]\n\nsome notes"
    result = apply_auto_lyrics_structure(lyrics, is_vocal=False)
    assert result.count("[Instrumental]") == 1
    assert "[Extended Outro]" in result


def test_auto_lyrics_instrumental_prepend_and_append():
    """インストモード + タグなし歌詞 → 前後にタグ追加."""
    lyrics = "[Mixing Notes]\nKeep bass warm"
    result = apply_auto_lyrics_structure(lyrics, is_vocal=False)
    assert result.startswith("[Instrumental]")
    assert result.endswith("[Extended Outro]")


def test_auto_lyrics_vocal_no_outro():
    """ボーカルモード + [Outro] がない → [Extended Outro] 追加."""
    lyrics = "[Verse 1]\nla la la\n\n[Chorus]\noh oh oh"
    result = apply_auto_lyrics_structure(lyrics, is_vocal=True)
    assert "[Extended Outro]" in result


def test_auto_lyrics_vocal_has_outro():
    """ボーカルモード + 既に [Outro] がある → 追加しない."""
    lyrics = "[Verse 1]\nla la la\n\n[Outro]"
    result = apply_auto_lyrics_structure(lyrics, is_vocal=True)
    assert result.count("[Outro]") == 1
    assert "[Extended Outro]" not in result


def test_auto_lyrics_vocal_empty():
    """ボーカルモード + 空歌詞 → そのまま空を返す."""
    result = apply_auto_lyrics_structure("", is_vocal=True)
    assert result == ""


# ---------------------------------------------------------------------------
# QualityReport
# ---------------------------------------------------------------------------


def test_quality_report_empty():
    """空レポートは has_errors / has_warnings とも False."""
    report = QualityReport()
    assert not report.has_errors
    assert not report.has_warnings


def test_quality_report_with_errors():
    report = QualityReport(errors=["error1"])
    assert report.has_errors
    assert not report.has_warnings


def test_quality_report_with_warnings():
    report = QualityReport(warnings=["warn1"])
    assert not report.has_errors
    assert report.has_warnings


# ---------------------------------------------------------------------------
# build_prompt_entries: 品質ルール統合テスト
# ---------------------------------------------------------------------------


def test_build_prompt_entries_banned_artist_fails_loud(channel_dir, tmp_path):
    """Given banned_artists に Drake + Style に Drake を含む
    When build_prompt_entries を呼ぶ
    Then ConfigError で fail-loud する。
    """
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz like Drake",
        banned_artists=["Drake"],
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert "Drake" in str(exc_info.value)


def test_build_prompt_entries_style_char_limit_warns(channel_dir, tmp_path, capsys):
    """Given style_char_limit: 50 + genre_line が長い
    When build_prompt_entries を呼ぶ
    Then 警告が stderr に出力される（エラーにはならない）。
    """
    long_genre = "lo-fi jazz, " * 10
    _write_suno_override(
        channel_dir,
        genre_line=long_genre,
        style_char_limit=50,
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 1
    captured = capsys.readouterr()
    assert "[WARN]" in captured.err


def test_build_prompt_entries_auto_lyrics_instrumental(channel_dir, tmp_path):
    """Given auto_lyrics_structure: true + インストモード
    When build_prompt_entries を呼ぶ
    Then lyrics に [Instrumental] と [Extended Outro] が含まれる。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz, soft piano",
        auto_lyrics_structure=True,
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert "[Instrumental]" in entries[0]["lyrics"]
    assert "[Extended Outro]" in entries[0]["lyrics"]


def test_build_prompt_entries_auto_lyrics_disabled(channel_dir, tmp_path):
    """Given auto_lyrics_structure: false + インストモード
    When build_prompt_entries を呼ぶ
    Then lyrics は空文字のまま（自動付加されない）。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz, soft piano",
        auto_lyrics_structure=False,
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["lyrics"] == ""


def test_build_prompt_entries_no_banned_artists_passes(channel_dir, tmp_path):
    """Given banned_artists が空 + 通常の genre_line
    When build_prompt_entries を呼ぶ
    Then エラーなく完了する。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz, soft piano",
        banned_artists=[],
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 1


# ---------------------------------------------------------------------------
# config.default.yaml: 新規キーの存在検証
# ---------------------------------------------------------------------------


def test_default_yaml_has_quality_rule_keys():
    """config.default.yaml に #904 で追加した品質ルール関連キーが存在すること."""
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))

    assert data["style_influence"] == 50, "style_influence の既定値は 50"
    assert data["weirdness"] == 50, "weirdness の既定値は 50"
    assert data["auto_lyrics_structure"] is True, "auto_lyrics_structure: true が追加されるべき"
    assert data["style_char_limit"] == 120, "style_char_limit: 120 が追加されるべき"
    assert isinstance(data["banned_artists"], list), "banned_artists はリスト型であるべき"
    assert len(data["banned_artists"]) >= 25, "banned_artists は 25 件以上であるべき"


# ---------------------------------------------------------------------------
# SKILL.md: 品質ルールセクションの存在検証
# ---------------------------------------------------------------------------

_SKILL_MD = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "SKILL.md"
_SUNO_LYRIC_SKILL_MD = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno-lyric" / "SKILL.md"


def test_skill_md_has_quality_rules_section():
    """SKILL.md に品質ルールセクションが存在すること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "Quality Rules" in text or "品質ルール" in text


def test_skill_md_has_5_element_order():
    """SKILL.md に 5 要素順序の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "5-Element" in text or "5 要素" in text or "5要素" in text


def test_skill_md_has_120_char_limit():
    """SKILL.md に 120 文字制限の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "120" in text


def test_skill_md_has_banned_artists():
    """SKILL.md に禁止アーティスト名の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "banned_artists" in text


def test_skill_md_has_instrument_adjectives():
    """SKILL.md に楽器形容詞要件の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "adjective" in text.lower() or "形容詞" in text


def test_skill_md_has_hiragana_guide():
    """/suno-lyric の SKILL.md にひらがな歌詞ガイドの記述があること."""
    text = _SUNO_LYRIC_SKILL_MD.read_text(encoding="utf-8")
    assert "hiragana" in text.lower() or "ひらがな" in text


def test_skill_md_has_auto_lyrics_structure():
    """SKILL.md に auto_lyrics_structure の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "auto_lyrics_structure" in text


def test_skill_md_has_track_title_generation():
    """SKILL.md に Track Title Generation (#899) の記述があること."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "Track Title" in text or "タイトル自動生成" in text or "name_en" in text
