"""Suno artifact route contract tests."""

from __future__ import annotations

from youtube_automation.domains.suno.downloaded.models import collection_downloaded_route


def test_collection_downloaded_route_encodes_collection_id_path_segment():
    """Given スペース入り collection id
    When downloaded route を組み立てる
    Then collection id を path segment encode する。
    """
    assert (
        collection_downloaded_route("20260601-clm-rainy jazz-collection")
        == "/collections/20260601-clm-rainy%20jazz-collection/downloaded"
    )


def test_prompt_and_lyric_readers_preserve_distinct_whitespace_policies():
    from youtube_automation.domains.suno.downloaded.validation import (
        _lyric_entries_from_json_list,
        _prompt_entries_from_json_list,
    )

    raw = [{"name": "Track", "style": "jazz", "lyrics": "  verse \n\t"}]
    prompt, prompt_issues = _prompt_entries_from_json_list(raw)
    lyric, lyric_issues = _lyric_entries_from_json_list(raw)
    assert prompt.lyrics_by_name == {"Track": "  verse \n\t"}
    assert lyric.lyrics_by_name == {"Track": "  verse"}
    assert prompt.lyrics_entries[0].lyrics == prompt.lyrics_by_name["Track"]
    assert lyric.lyrics_entries[0].lyrics == lyric.lyrics_by_name["Track"]
    assert prompt_issues == lyric_issues == []
    assert raw[0]["lyrics"] == "  verse \n\t"


def test_artifact_validation_keeps_issue_order_and_invalid_name_short_circuit():
    from youtube_automation.domains.suno.downloaded.validation import (
        _lyric_entries_from_json_list,
        _prompt_entries_from_json_list,
    )

    prompt, prompt_issues = _prompt_entries_from_json_list(
        [
            {"name": "", "style": None, "lyrics": None},
            {"name": "Track", "style": " ", "lyrics": None},
        ]
    )
    lyric, lyric_issues = _lyric_entries_from_json_list(
        [
            {"name": "", "lyrics": None},
            {"name": "Track", "lyrics": None},
        ]
    )
    assert prompt.names == lyric.names == ["Track"]
    assert prompt.lyrics_by_name == lyric.lyrics_by_name == {}
    assert prompt.lyrics_entries == lyric.lyrics_entries == []
    assert prompt_issues == [
        "suno-prompts.json entry 1.name must be a non-empty string",
        "suno-prompts.json entry 'Track' style must be a non-empty string",
        "suno-prompts.json entry 'Track' lyrics must be a string",
    ]
    assert lyric_issues == [
        "suno-lyrics.json entry 1.name must be a non-empty string",
        "suno-lyrics.json entry 'Track' lyrics must be a string",
    ]
