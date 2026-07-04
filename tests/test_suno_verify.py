"""yt-suno-verify CLI の artifact 検証テスト."""

from __future__ import annotations

import inspect
import json

import pytest
import yaml

from tests.helpers.suno_verify import (
    docs_dir,
    prompt_names,
    run_verify,
    write_lyrics,
    write_patterns,
    write_prompts,
    write_suno_override,
    write_video_analysis_suno_preset,
)
from youtube_automation.utils import skill_config


@pytest.fixture
def channel_dir(tmp_path, monkeypatch):
    """skill_config が参照する CHANNEL_DIR を一時ディレクトリへ向ける."""
    ch = tmp_path / "channel"
    (ch / "config" / "skills").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))
    skill_config.reset()
    yield ch
    skill_config.reset()


def test_instrumental_valid_collection_returns_zero_and_summary(channel_dir, tmp_path, monkeypatch, capsys):
    """Given tracks=4 と 2 prompt entries が一致する instrumental collection
    When yt-suno-verify を collection directory に対して実行する
    Then exit 0 と曲数 summary を返す。
    """
    write_suno_override(channel_dir, genre_line="lo-fi jazz")
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one", "scene two"], tracks=4)
    write_prompts(docs, prompt_names(mode="instrumental", scenes_count=2))

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 0
    assert "OK" in output
    assert "mode=instrumental" in output
    assert "prompt_entries=2" in output
    assert "tracks_per_collection=4" in output


def test_instrumental_track_count_mismatch_returns_one(channel_dir, tmp_path, monkeypatch, capsys):
    """Given tracks=10 に対して 2 prompt entries しかない collection
    When yt-suno-verify を実行する
    Then ceil(10/2)=5 との不一致を列挙して exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="lo-fi jazz")
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one", "scene two"], tracks=10)
    write_prompts(docs, prompt_names(mode="instrumental", scenes_count=2))

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "tracks_per_collection=10" in output
    assert "5" in output
    assert "2" in output


def test_duplicate_prompt_entry_names_are_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given suno-prompts.json に重複 name がある
    When yt-suno-verify を実行する
    Then 重複名を含む issue を列挙して exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="lo-fi jazz")
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one", "scene two"], tracks=4)
    duplicate_name = "静かな雨 — Quiet Rain (Variation 1)"
    write_prompts(docs, [duplicate_name, duplicate_name])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "duplicate" in output.lower() or "duplicated" in output.lower()
    assert duplicate_name in output


def test_vocal_valid_collection_reports_prompt_entries_and_expected_clips(
    channel_dir,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Given 2 scene variations と tracks_per_pattern=3 の vocal collection
    When yt-suno-verify を実行する
    Then prompt entry 数と期待 clip 数を summary に出す。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=3)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    names = prompt_names(mode="vocal", scenes_count=2)
    write_patterns(docs, mode="vocal", scenes=["scene one", "scene two"])
    write_prompts(docs, names, lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": name, "lyrics": "[Verse]\nla la"} for name in names])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 0
    assert "mode=vocal" in output
    assert "prompt_entries=2" in output
    assert "tracks_per_pattern=3" in output
    assert "expected_clips=6" in output


def test_vocal_lyrics_can_be_verified_before_prompts_are_generated(
    channel_dir,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Given /suno-lyric 直後で prompts は未生成だが lyrics が patterns と一致する
    When yt-suno-verify を実行する
    Then pattern-derived name を期待値として検証し exit 0 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=2)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    names = prompt_names(mode="vocal", scenes_count=1)
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_lyrics(docs, [{"name": names[0], "lyrics": "[Verse]\nla la"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 0
    assert "mode=vocal" in output
    assert "prompt_entries=1" in output
    assert "tracks_per_pattern=2" in output
    assert "expected_clips=2" in output


def test_mode_omission_uses_video_analysis_fallback_genre_line_for_vocal(
    channel_dir,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Given config genre_line 空 + video_analysis fallback が vocal を示す
    When mode 省略 collection を検証する
    Then generator と同じ effective genre_line で vocal として検証する。
    """
    write_suno_override(channel_dir, genre_line="", tracks_per_pattern=2)
    write_video_analysis_suno_preset(channel_dir, genre_line="dream pop vocals")
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    names = prompt_names(mode="instrumental", scenes_count=1)
    write_patterns(docs, mode=None, scenes=["scene one"])
    write_prompts(docs, names, lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": names[0], "lyrics": "[Verse]\nla la"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 0
    assert "mode=vocal" in output
    assert "tracks_per_pattern=2" in output


def test_vocal_prompt_entry_count_uses_scene_variations(channel_dir, tmp_path, monkeypatch, capsys):
    """Given patterns は 2 scene variations だが prompts は 1 entry
    When yt-suno-verify を実行する
    Then vocal の期待 prompt entry 数不一致として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=3)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    names = prompt_names(mode="vocal", scenes_count=2)
    write_patterns(docs, mode="vocal", scenes=["scene one", "scene two"])
    write_prompts(docs, [names[0]], lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": names[0], "lyrics": "[Verse]\nla la"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "mode=vocal" in output
    assert "expected" in output
    assert "2" in output
    assert "1" in output


def test_vocal_lyrics_missing_extra_and_empty_are_all_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given lyrics JSON に missing / extra / empty lyrics が同時にある
    When yt-suno-verify を実行する
    Then 1件目で停止せず全 issue を列挙する。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    expected_name = "歌もの — Vocal"
    extra_name = "別名 — Extra"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [expected_name], lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": extra_name, "lyrics": ""}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert f"missing: {expected_name}" in output
    assert f"extra: {extra_name}" in output
    assert "lyrics" in output.lower()
    assert "empty" in output.lower() or "non-empty" in output.lower()


def test_vocal_prompt_and_lyric_names_are_compared_without_stripping(channel_dir, tmp_path, monkeypatch, capsys):
    """Given prompt name に外側 whitespace がある
    When yt-suno-verify を実行する
    Then lyric name と strip 後に一致しても完全一致扱いにしない。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    expected_name = "歌もの — Vocal"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [f" {expected_name} "], lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": expected_name, "lyrics": "[Verse]\nla la"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "suno-prompts.json entry 1.name must not have leading or trailing whitespace" in output
    assert f"missing: {expected_name}" in output
    assert f"extra:  {expected_name} " in output


def test_pattern_names_with_surrounding_whitespace_are_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given suno-patterns.yaml の name_jp に外側 whitespace がある
    When yt-suno-verify を実行する
    Then generator と同じ entry name 契約違反として列挙する。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    expected_name = "歌もの — Vocal"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    patterns_path = docs / "suno-patterns.yaml"
    payload = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    payload["patterns"][0]["name_jp"] = " 歌もの "
    patterns_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    write_prompts(docs, [expected_name], lyrics="[Verse]\nla la")
    write_lyrics(docs, [{"name": expected_name, "lyrics": "[Verse]\nla la"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "suno-patterns.yaml patterns[1].name_jp must not have leading or trailing whitespace" in output


def test_vocal_lyrics_without_section_tag_is_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given vocal lyrics に section tag が無い
    When yt-suno-verify を実行する
    Then section tag 不足として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    name = "歌もの — Vocal"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [name], lyrics="plain lyric")
    write_lyrics(docs, [{"name": name, "lyrics": "plain lyric"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "section tag" in output.lower()
    assert name in output


def test_vocal_prompt_lyrics_structure_is_reported_even_when_lyrics_json_is_valid(
    channel_dir,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Given prompts 側 lyrics が空で lyrics JSON は valid
    When yt-suno-verify を実行する
    Then 実投入 artifact の prompts 側 lyrics 違反として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    name = "歌もの — Vocal"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [name], lyrics="")
    write_lyrics(docs, [{"name": name, "lyrics": "[Verse]\nvalid lyric"}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert f"suno-prompts.json entry '{name}' lyrics must be non-empty" in output


def test_vocal_lyrics_accept_numbered_section_tags(channel_dir, tmp_path, monkeypatch, capsys):
    """Given lyrics に公開例と同じ [Verse 1] section tag がある
    When yt-suno-verify を実行する
    Then section tag として認識し exit 0 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    name = "歌もの — Vocal"
    lyrics = "[Verse 1]\nla la"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [name], lyrics=lyrics)
    write_lyrics(docs, [{"name": name, "lyrics": lyrics}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 0
    assert "OK" in output


def test_vocal_lyrics_reject_instrumental_tag(channel_dir, tmp_path, monkeypatch, capsys):
    """Given vocal lyrics に [Instrumental] が混入している
    When yt-suno-verify を実行する
    Then vocal 契約違反として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="dream pop vocals", tracks_per_pattern=1)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    name = "歌もの — Vocal"
    lyrics = "[Verse]\nla la\n\n[Instrumental]"
    write_patterns(docs, mode="vocal", scenes=["scene one"])
    write_prompts(docs, [name], lyrics=lyrics)
    write_lyrics(docs, [{"name": name, "lyrics": lyrics}])

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "[Instrumental]" in output
    assert name in output


def test_genre_line_char_limit_uses_preflight_check(channel_dir, tmp_path, monkeypatch, capsys):
    """Given genre_line が 121 文字
    When yt-suno-verify を実行する
    Then 既存 preflight と同じ 120 文字上限違反として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="x" * 121)
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one"], tracks=2)
    write_prompts(docs, prompt_names(mode="instrumental", scenes_count=1))

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "genre_line" in output
    assert "121 / 120" in output


def test_used_style_variant_genre_line_char_limit_is_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given pattern が 121 文字 genre_line の style variant を使用する
    When yt-suno-verify を実行する
    Then 使用中 variant の Style 上限違反として exit 1 にする。
    """
    write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz",
        style_variants={
            "long": {
                "name": "Long",
                "genre_line": "x" * 121,
            }
        },
    )
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one"], tracks=2, style="long")
    write_prompts(docs, prompt_names(mode="instrumental", scenes_count=1))

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "style_variants.long.genre_line" in output
    assert "121 / 120" in output


def test_invalid_prompts_json_shape_is_reported(channel_dir, tmp_path, monkeypatch, capsys):
    """Given suno-prompts.json root が公開契約外 shape
    When yt-suno-verify を実行する
    Then envelope 誤用を通さず shape issue として exit 1 にする。
    """
    write_suno_override(channel_dir, genre_line="lo-fi jazz")
    collection = tmp_path / "collection"
    docs = docs_dir(collection)
    write_patterns(docs, mode="instrumental", scenes=["scene one"], tracks=2)
    (docs / "suno-prompts.json").write_text(json.dumps({"data": []}), encoding="utf-8")

    code = run_verify(monkeypatch, collection)
    output = capsys.readouterr().out

    assert code == 1
    assert "suno-prompts.json" in output
    assert "root" in output
    assert "entries" in output


def test_verify_artifact_helpers_do_not_accept_mutable_issue_accumulators():
    """検証 helper は呼び出し元 list を引数で受け取らず、issue を戻り値で返す。"""
    from youtube_automation.utils import suno_verify_artifacts

    for helper_name in ("_validate_prompts", "_verify_vocal_artifacts"):
        signature = inspect.signature(getattr(suno_verify_artifacts, helper_name))
        assert "issues" not in signature.parameters


def test_verify_reader_helpers_do_not_accept_mutable_accumulators():
    """reader helper は呼び出し元 list/dict を引数で受け取らず、parse 結果を戻り値で返す。"""
    from youtube_automation.utils import suno_verify_readers

    for old_helper_name in ("_append_prompt_entry", "_append_lyric_entry"):
        assert not hasattr(suno_verify_readers, old_helper_name)

    for helper_name in ("_entry_names_from_pattern", "_prompt_entry_from_mapping", "_lyric_entry_from_mapping"):
        signature = inspect.signature(getattr(suno_verify_readers, helper_name))
        assert "issues" not in signature.parameters
        assert "names" not in signature.parameters
        assert "lyrics_by_name" not in signature.parameters
