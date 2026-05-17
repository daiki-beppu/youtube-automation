"""channel_settings ドメインロジック + yt-channel-settings CLI のテスト。"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from youtube_automation.scripts import channel_settings_cli
from youtube_automation.utils.channel_settings import (
    build_update_body,
    diff_settings,
    fetch_channel,
    parse_api_response,
)
from youtube_automation.utils.exceptions import YouTubeAPIError

# ---------------------------------------------------------------------------
# build_update_body
# ---------------------------------------------------------------------------


class TestBuildUpdateBody:
    def test_all_fields(self):
        local = {
            "description": "desc",
            "keywords": ["bgm", "lo fi"],
            "country": "JP",
            "default_language": "ja",
            "unsubscribed_trailer": "VID",
            "made_for_kids": False,
        }
        localizations = {
            "supported_languages": ["ja", "en"],
            "ja": {"title": "タイトル", "description": "説明"},
            "en": {"title": "Title", "description": "Desc"},
        }
        body = build_update_body(local, localizations, channel_id="UCabc")
        assert body["id"] == "UCabc"
        assert body["brandingSettings"]["channel"]["description"] == "desc"
        assert body["brandingSettings"]["channel"]["country"] == "JP"
        assert body["brandingSettings"]["channel"]["defaultLanguage"] == "ja"
        assert body["brandingSettings"]["channel"]["unsubscribedTrailer"] == "VID"
        assert body["status"]["selfDeclaredMadeForKids"] is False
        assert body["localizations"]["ja"]["title"] == "タイトル"
        assert body["localizations"]["en"]["description"] == "Desc"

    def test_keywords_with_space_are_quoted(self):
        body = build_update_body({"keywords": ["lo fi", "bgm"]}, None, "UC1")
        kw = body["brandingSettings"]["channel"]["keywords"]
        assert "'lo fi'" in kw
        assert "bgm" in kw

    def test_missing_keys_are_excluded(self):
        body = build_update_body({"description": "only desc"}, None, "UC1")
        assert body == {
            "id": "UC1",
            "brandingSettings": {"channel": {"description": "only desc"}},
        }

    def test_empty_local(self):
        body = build_update_body({}, None, "UC1")
        assert body == {"id": "UC1"}

    def test_localizations_none_skips_section(self):
        body = build_update_body({"description": "x"}, None, "UC1")
        assert "localizations" not in body

    def test_localizations_without_supported_languages(self):
        body = build_update_body({}, {"supported_languages": []}, "UC1")
        assert "localizations" not in body


# ---------------------------------------------------------------------------
# parse_api_response
# ---------------------------------------------------------------------------


class TestParseApiResponse:
    def test_full_response(self):
        resp = {
            "id": "UCabc",
            "brandingSettings": {
                "channel": {
                    "description": "desc",
                    "keywords": 'bgm "lo fi"',
                    "country": "JP",
                    "defaultLanguage": "ja",
                    "unsubscribedTrailer": "VID",
                }
            },
            "status": {"selfDeclaredMadeForKids": True},
            "localizations": {
                "ja": {"title": "タ", "description": "説"},
                "en": {"title": "T", "description": "D"},
            },
        }
        channel, loc = parse_api_response(resp)
        assert channel["description"] == "desc"
        assert channel["keywords"] == ["bgm", "lo fi"]
        assert channel["country"] == "JP"
        assert channel["default_language"] == "ja"
        assert channel["unsubscribed_trailer"] == "VID"
        assert channel["made_for_kids"] is True
        assert loc["supported_languages"] == ["en", "ja"]
        assert loc["ja"] == {"title": "タ", "description": "説"}

    def test_empty_response(self):
        channel, loc = parse_api_response({})
        assert channel == {}
        assert loc == {}

    def test_empty_keywords(self):
        resp = {"brandingSettings": {"channel": {"keywords": ""}}}
        channel, _ = parse_api_response(resp)
        assert channel["keywords"] == []


# ---------------------------------------------------------------------------
# diff_settings
# ---------------------------------------------------------------------------


class TestDiffSettings:
    def test_no_diff(self):
        local = {"description": "x", "keywords": ["a"]}
        lines = diff_settings(local, {}, local, {})
        assert lines == []

    def test_description_diff(self):
        lines = diff_settings({"description": "new"}, {}, {"description": "old"}, {})
        joined = "\n".join(lines)
        assert "description" in joined
        assert "'old'" in joined
        assert "'new'" in joined

    def test_localizations_diff(self):
        local_loc = {"supported_languages": ["ja"], "ja": {"title": "新", "description": "d"}}
        remote_loc = {"supported_languages": ["ja"], "ja": {"title": "旧", "description": "d"}}
        lines = diff_settings({}, local_loc, {}, remote_loc)
        joined = "\n".join(lines)
        assert "localizations.ja.title" in joined
        assert "localizations.ja.description" not in joined  # 同一

    def test_missing_on_one_side(self):
        lines = diff_settings({"country": "JP"}, {}, {}, {})
        joined = "\n".join(lines)
        assert "country" in joined
        assert "<unset>" in joined


# ---------------------------------------------------------------------------
# fetch_channel
# ---------------------------------------------------------------------------


class TestFetchChannel:
    def test_returns_first_item(self):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [{"id": "UCabc", "brandingSettings": {}}]}
        result = fetch_channel(youtube)
        assert result["id"] == "UCabc"

    def test_empty_items_raises(self):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": []}
        with pytest.raises(YouTubeAPIError, match="no YouTube channel"):
            fetch_channel(youtube)

    def test_api_exception_wrapped(self):
        youtube = MagicMock()
        youtube.channels().list().execute.side_effect = RuntimeError("boom")
        with pytest.raises(YouTubeAPIError, match="channels\\(\\).list"):
            fetch_channel(youtube)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _mock_remote_response(description="remote desc", lang="ja"):
    return {
        "id": "UCfixture",
        "brandingSettings": {
            "channel": {
                "description": description,
                "keywords": "chiptune 8-bit",
                "country": "JP",
                "defaultLanguage": lang,
            }
        },
        "status": {"selfDeclaredMadeForKids": False},
        "localizations": {},
    }


class TestCLIDiff:
    def test_diff_shows_description_mismatch(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="different")]}
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["diff"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "description" in out
        assert "Test channel description for sync." in out


class TestCLIPushDryRun:
    def test_dry_run_does_not_call_update(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["push"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "dry-run" in out
        youtube.channels().update.assert_not_called()

    def test_apply_calls_update(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "pushed" in out

        # `brandingSettings` を他 part と混在させると YouTube API が 400 を返すため (#230)、
        # part 単位で個別に channels().update() を呼ぶ。
        update_calls = youtube.channels().update.call_args_list
        parts_called = [call.kwargs["part"] for call in update_calls]
        assert len(update_calls) >= 1
        for part in parts_called:
            assert "," not in part, f"part must be a single value, got: {part!r}"
        assert "brandingSettings" in parts_called

        branding_call = next(call for call in update_calls if call.kwargs["part"] == "brandingSettings")
        body = branding_call.kwargs["body"]
        assert body["id"] == "UCfixture"
        assert body["brandingSettings"]["channel"]["description"] == "Test channel description for sync."
        assert "status" not in body and "localizations" not in body, (
            "branding push body must contain only brandingSettings"
        )

    def test_apply_splits_branding_and_status(self, capsys):
        """`brandingSettings` と `status` が同時に変更されても、個別の API call として発火する。"""
        youtube = MagicMock()
        remote = _mock_remote_response(description="old remote")
        remote["status"] = {"selfDeclaredMadeForKids": True}  # local fixture は False
        youtube.channels().list().execute.return_value = {"items": [remote]}
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["push", "--apply", "--no-localizations"])
        assert rc == 0
        update_calls = youtube.channels().update.call_args_list
        parts_called = [call.kwargs["part"] for call in update_calls]
        assert "brandingSettings" in parts_called
        assert "status" in parts_called
        # 1 つの part 文字列に複数 part が混在しないこと
        for part in parts_called:
            assert part in ("brandingSettings", "localizations", "status")

        status_call = next(call for call in update_calls if call.kwargs["part"] == "status")
        assert status_call.kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False
        assert "brandingSettings" not in status_call.kwargs["body"]

    def test_no_diff_skips_update(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCfixture",
                    "brandingSettings": {
                        "channel": {
                            "description": "Test channel description for sync.",
                            "keywords": "chiptune 8-bit 'rpg music'",
                            "country": "JP",
                            "defaultLanguage": "ja",
                            "unsubscribedTrailer": "dQw4w9WgXcQ",
                        }
                    },
                    "status": {"selfDeclaredMadeForKids": False},
                    "localizations": {},
                }
            ]
        }
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["push", "--apply", "--no-localizations"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no diff" in out
        youtube.channels().update.assert_not_called()


class TestCLIPull:
    def test_dry_run_does_not_write(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="pulled desc")]}
        config_path = tmp_path / "config" / "channel" / "meta.json"
        before = config_path.read_text(encoding="utf-8")
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull"])
        after = config_path.read_text(encoding="utf-8")
        assert rc == 0
        assert before == after  # not modified
        assert "dry-run" in capsys.readouterr().out

    def test_apply_writes_youtube_channel_only(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="pulled desc")]}
        config_path = tmp_path / "config" / "channel" / "meta.json"
        before_data = json.loads(config_path.read_text(encoding="utf-8"))
        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull", "--apply"])
        assert rc == 0
        after_data = json.loads(config_path.read_text(encoding="utf-8"))

        # youtube_channel is updated
        assert after_data["youtube_channel"]["description"] == "pulled desc"
        # other sections untouched
        for key in before_data:
            if key == "youtube_channel":
                continue
            assert after_data[key] == before_data[key]


def _prepare_channel_dir(tmp_path: Path, monkeypatch) -> None:
    """テスト用 channel/*.json を tmp_path にコピーし CHANNEL_DIR を向ける。"""
    fixture_root = Path(__file__).parent / "fixtures" / "sample_channel"
    src_channel = fixture_root / "config" / "channel"
    dst_channel = tmp_path / "config" / "channel"
    dst_channel.mkdir(parents=True, exist_ok=True)
    for src in src_channel.glob("*.json"):
        (dst_channel / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    # localizations.json も実体化してコピー
    loc_src = (fixture_root / "config" / "localizations.json").resolve()
    (tmp_path / "config" / "localizations.json").write_text(
        loc_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
