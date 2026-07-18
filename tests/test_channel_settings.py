"""channel_settings ドメインロジック + yt-channel-settings CLI のテスト。"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from youtube_automation.scripts import channel_settings_cli
from youtube_automation.utils.channel_settings import (
    KEYWORDS_MAX_LENGTH,
    build_update_body,
    build_upload_status_flags,
    diff_settings,
    fetch_channel,
    normalize_locale_to_api,
    normalize_locale_to_short,
    parse_api_response,
    verify_channel_id,
)
from youtube_automation.utils.config.youtube import YoutubeApi
from youtube_automation.utils.exceptions import ConfigError, YouTubeAPIError

# ---------------------------------------------------------------------------
# build_upload_status_flags (#605)
# ---------------------------------------------------------------------------


class TestBuildUploadStatusFlags:
    def test_defaults_preserve_current_behavior(self):
        """未設定時のデフォルトは現行の振る舞い（synthetic=True / made_for_kids=False）。"""
        api = YoutubeApi(category_id="10", privacy_status="public", language="ja")
        flags = build_upload_status_flags(api)
        assert flags == {
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        }

    def test_config_override(self):
        """config で上書きした値が status フラグへ反映される。"""
        api = YoutubeApi(
            category_id="10",
            privacy_status="public",
            language="ja",
            contains_synthetic_media=False,
            self_declared_made_for_kids=True,
        )
        flags = build_upload_status_flags(api)
        assert flags == {
            "selfDeclaredMadeForKids": True,
            "containsSyntheticMedia": False,
        }


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
        # #562: 短縮 BCP-47 (`ja`) を YouTube 内部形 `ja_JP` に正規化して送る。
        assert body["brandingSettings"]["channel"]["defaultLanguage"] == "ja_JP"
        assert body["brandingSettings"]["channel"]["unsubscribedTrailer"] == "VID"
        assert body["status"]["selfDeclaredMadeForKids"] is False
        # #562: localizations のキーも `ja` / `en` → `ja_JP` / `en_US` に正規化する。
        assert body["localizations"]["ja_JP"]["title"] == "タイトル"
        assert body["localizations"]["en_US"]["description"] == "Desc"

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

    def test_keywords_at_limit_passes(self):
        """#563: 500 文字ちょうどはバリデーションを通過する（境界値）。"""
        # スペースを含まないタグは quote されないため api 形式 = タグそのもの。
        keywords = ["a" * KEYWORDS_MAX_LENGTH]  # 単一タグで 500 文字ちょうど
        api_keywords = "a" * KEYWORDS_MAX_LENGTH
        body = build_update_body({"keywords": keywords}, None, "UC1")
        assert body["brandingSettings"]["channel"]["keywords"] == api_keywords

    def test_keywords_over_limit_raises(self):
        """#563: 500 文字超過は push 前に YouTubeAPIError で止める。"""
        keywords = ["a" * (KEYWORDS_MAX_LENGTH + 10)]  # 510 文字
        with pytest.raises(YouTubeAPIError) as excinfo:
            build_update_body({"keywords": keywords}, None, "UC1")
        msg = str(excinfo.value)
        assert "keywords exceeds 500 chars" in msg
        assert "got 510" in msg
        assert "over by 10" in msg

    def test_keywords_over_limit_includes_shortening_hint(self):
        """#563: エラーメッセージに長い順の短縮候補タグを含める。"""
        keywords = ["short"] * 90 + ["this is a very long tag candidate"]
        with pytest.raises(YouTubeAPIError) as excinfo:
            build_update_body({"keywords": keywords}, None, "UC1")
        assert "this is a very long tag candidate" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Locale normalization (#562)
# ---------------------------------------------------------------------------


class TestNormalizeLocaleToApi:
    """#562: 任意形式 → YouTube 内部形 `xx_YY` への正規化。"""

    @pytest.mark.parametrize(
        ("input_code", "expected"),
        [
            ("ja", "ja_JP"),
            ("ja-JP", "ja_JP"),
            ("ja_JP", "ja_JP"),
            ("en", "en_US"),
            ("en-US", "en_US"),
            ("en_US", "en_US"),
            ("de", "de_DE"),
            ("fr", "fr_FR"),
            ("pt", "pt_PT"),
            ("pt-BR", "pt_BR"),
            ("pt_BR", "pt_BR"),
            ("zh", "zh_CN"),
            ("zh-TW", "zh_TW"),
        ],
    )
    def test_known_codes(self, input_code, expected):
        assert normalize_locale_to_api(input_code) == expected

    def test_unknown_with_region_passes_through_with_underscore(self):
        # マッピング表外の言語でも `xx-YY` → `xx_YY` の best-effort 変換は通す
        assert normalize_locale_to_api("xx-ZZ") == "xx_ZZ"
        assert normalize_locale_to_api("xx_ZZ") == "xx_ZZ"

    def test_empty_returns_empty(self):
        assert normalize_locale_to_api("") == ""


class TestNormalizeLocaleToShort:
    """#562: YouTube 内部形 `xx_YY` → 短縮 / BCP-47 ハイフン形への正規化。"""

    @pytest.mark.parametrize(
        ("input_code", "expected"),
        [
            ("ja_JP", "ja"),
            ("ja-JP", "ja"),
            ("ja", "ja"),
            ("en_US", "en"),
            ("en-US", "en"),
            ("en", "en"),
            ("de_DE", "de"),
            # region 必須言語は `xx-YY` を保持
            ("pt_BR", "pt-BR"),
            ("pt-BR", "pt-BR"),
            ("zh_TW", "zh-TW"),
            ("zh_HK", "zh-HK"),
        ],
    )
    def test_known_codes(self, input_code, expected):
        assert normalize_locale_to_short(input_code) == expected

    def test_round_trip(self):
        # short → api → short が冪等であること（pull 後に再 push しても diff が出ない）
        for short in ("ja", "en", "de", "fr", "pt-BR", "zh-TW"):
            assert normalize_locale_to_short(normalize_locale_to_api(short)) == short


class TestBuildUpdateBodyLocaleNormalization:
    """#562: build_update_body 側の正規化を build_update_body の通常テストとは別に検証。"""

    def test_short_locale_normalized_to_api_form(self):
        local = {"default_language": "ja"}
        localizations = {
            "supported_languages": ["ja", "en", "de"],
            "ja": {"title": "T-ja", "description": "D-ja"},
            "en": {"title": "T-en", "description": "D-en"},
            "de": {"title": "T-de", "description": "D-de"},
        }
        body = build_update_body(local, localizations, "UC1")
        assert body["brandingSettings"]["channel"]["defaultLanguage"] == "ja_JP"
        assert set(body["localizations"].keys()) == {"ja_JP", "en_US", "de_DE"}
        assert body["localizations"]["de_DE"] == {"title": "T-de", "description": "D-de"}

    def test_hyphen_locale_normalized_to_api_form(self):
        local = {"default_language": "ja-JP"}
        localizations = {
            "supported_languages": ["ja-JP", "en-US"],
            "ja-JP": {"title": "T-ja", "description": "D-ja"},
            "en-US": {"title": "T-en", "description": "D-en"},
        }
        body = build_update_body(local, localizations, "UC1")
        assert body["brandingSettings"]["channel"]["defaultLanguage"] == "ja_JP"
        assert set(body["localizations"].keys()) == {"ja_JP", "en_US"}

    def test_underscore_locale_passes_through_unchanged(self):
        local = {"default_language": "ja_JP"}
        localizations = {
            "supported_languages": ["ja_JP", "en_US"],
            "ja_JP": {"title": "T-ja", "description": "D-ja"},
            "en_US": {"title": "T-en", "description": "D-en"},
        }
        body = build_update_body(local, localizations, "UC1")
        assert body["brandingSettings"]["channel"]["defaultLanguage"] == "ja_JP"
        assert set(body["localizations"].keys()) == {"ja_JP", "en_US"}


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

    def test_underscore_form_normalized_to_short(self):
        """#562: YouTube が `ja_JP` を返してもローカル persistence は短縮形 `ja`。"""
        resp = {
            "brandingSettings": {"channel": {"defaultLanguage": "ja_JP"}},
            "localizations": {
                "ja_JP": {"title": "タ", "description": "説"},
                "en_US": {"title": "T", "description": "D"},
                "pt_BR": {"title": "Tp", "description": "Dp"},
            },
        }
        channel, loc = parse_api_response(resp)
        assert channel["default_language"] == "ja"
        assert loc["supported_languages"] == ["en", "ja", "pt-BR"]
        assert loc["ja"] == {"title": "タ", "description": "説"}
        assert loc["pt-BR"] == {"title": "Tp", "description": "Dp"}

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

    def test_locale_form_diff_absorbed(self):
        """#562: local `ja` ↔ remote `ja_JP` は実質同一なので diff にしない。"""
        local_ch = {"default_language": "ja"}
        remote_ch = {"default_language": "ja_JP"}
        assert diff_settings(local_ch, {}, remote_ch, {}) == []

    def test_locale_form_diff_absorbed_localizations(self):
        """#562: localizations のキー揺れも吸収する。"""
        local_loc = {
            "supported_languages": ["ja", "en"],
            "ja": {"title": "T", "description": "D"},
            "en": {"title": "Te", "description": "De"},
        }
        remote_loc = {
            "supported_languages": ["ja_JP", "en_US"],
            "ja_JP": {"title": "T", "description": "D"},
            "en_US": {"title": "Te", "description": "De"},
        }
        # 内容が同じならキー形式違いだけで diff にしない
        assert diff_settings({}, local_loc, {}, remote_loc) == []


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


class TestFetchChannelLocalizationsFreshness:
    """#564: localizations を combined fetch のキャッシュ層から切り離して取り直す。"""

    @staticmethod
    def _youtube_with_split(combined: dict, localizations: dict) -> MagicMock:
        """part に応じて combined / localizations 別レスポンスを返す youtube モック。"""
        youtube = MagicMock()

        def _list(**kwargs):
            req = MagicMock()
            if kwargs.get("part") == "localizations":
                req.execute.return_value = localizations
            else:
                req.execute.return_value = combined
            return req

        youtube.channels.return_value.list.side_effect = _list
        return youtube

    def test_localizations_taken_from_separate_fetch(self):
        # Given: combined fetch は旧版 localizations、単独 part は新版を返す
        combined = {
            "items": [
                {
                    "id": "UCx",
                    "brandingSettings": {"channel": {"description": "branding desc"}},
                    "localizations": {"ja": {"title": "T", "description": "OLD (cached)"}},
                }
            ]
        }
        fresh = {"items": [{"id": "UCx", "localizations": {"ja": {"title": "T", "description": "NEW"}}}]}
        youtube = self._youtube_with_split(combined, fresh)

        # When
        result = fetch_channel(youtube)

        # Then: localizations は単独 fetch の新版で上書きされる
        assert result["localizations"]["ja"]["description"] == "NEW"
        # brandingSettings は combined fetch 由来
        assert result["brandingSettings"]["channel"]["description"] == "branding desc"

    def test_combined_fetch_omits_localizations_part(self):
        # Given
        combined = {"items": [{"id": "UCx", "brandingSettings": {"channel": {}}}]}
        fresh = {"items": [{"id": "UCx", "localizations": {"en": {"title": "t", "description": "d"}}}]}
        youtube = self._youtube_with_split(combined, fresh)

        # When
        fetch_channel(youtube)

        # Then: combined call は localizations を part に含めず、別途 localizations 単独 fetch する
        parts_used = [c.kwargs.get("part") for c in youtube.channels.return_value.list.call_args_list]
        assert "brandingSettings,status,snippet" in parts_used
        assert "localizations" in parts_used
        assert not any("brandingSettings" in p and "localizations" in p for p in parts_used if p)

    def test_no_localizations_results_in_empty_dict(self):
        # Given: チャンネルに localizations が無い（単独 fetch も localizations キー無し）
        combined = {"items": [{"id": "UCx", "brandingSettings": {"channel": {}}}]}
        no_loc = {"items": [{"id": "UCx"}]}
        youtube = self._youtube_with_split(combined, no_loc)

        # When
        result = fetch_channel(youtube)

        # Then: 空辞書（parse_api_response 側が安全に処理できる）
        assert result["localizations"] == {}

    def test_localizations_fetch_failure_wrapped(self):
        # Given: combined は成功するが localizations 単独 fetch が API エラー
        combined = {"items": [{"id": "UCx", "brandingSettings": {"channel": {}}}]}
        youtube = MagicMock()

        def _list(**kwargs):
            req = MagicMock()
            if kwargs.get("part") == "localizations":
                req.execute.side_effect = RuntimeError("loc boom")
            else:
                req.execute.return_value = combined
            return req

        youtube.channels.return_value.list.side_effect = _list

        # When / Then: 生 Exception ではなくドメイン例外に変換
        with pytest.raises(YouTubeAPIError, match="localizations"):
            fetch_channel(youtube)


# ---------------------------------------------------------------------------
# verify_channel_id (#561)
# ---------------------------------------------------------------------------


class TestVerifyChannelId:
    def test_match_passes(self):
        assert verify_channel_id("UCabc", "UCabc") is None

    def test_mismatch_raises(self):
        with pytest.raises(ConfigError, match="channel_id mismatch"):
            verify_channel_id("UCmine", "UCother")

    def test_unset_skips(self):
        # 未設定（後方互換）: remote が何であれ通す
        assert verify_channel_id("", "UCother") is None
        assert verify_channel_id(None, "UCother") is None


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

    def test_no_localizations_hides_remote_localization_diff(self, capsys):
        youtube = MagicMock()
        remote = _mock_remote_response(description="Test channel description for sync.")
        remote["brandingSettings"]["channel"]["keywords"] = "chiptune 8-bit 'rpg music'"
        remote["brandingSettings"]["channel"]["defaultLanguage"] = "ja"
        remote["brandingSettings"]["channel"]["unsubscribedTrailer"] = "dQw4w9WgXcQ"
        remote["localizations"] = {"ja_JP": {"title": "Remote title", "description": "Remote desc"}}
        youtube.channels().list().execute.return_value = {"items": [remote]}

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["diff", "--no-localizations"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "no diff" in out
        assert "localizations." not in out


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

    def test_apply_no_localizations_ignores_remote_localization_diff_and_skips_update(self, capsys):
        youtube = MagicMock()
        remote = _mock_remote_response(description="Test channel description for sync.")
        remote["brandingSettings"]["channel"]["keywords"] = "chiptune 8-bit 'rpg music'"
        remote["brandingSettings"]["channel"]["defaultLanguage"] = "ja"
        remote["brandingSettings"]["channel"]["unsubscribedTrailer"] = "dQw4w9WgXcQ"
        remote["localizations"] = {"ja_JP": {"title": "Remote title", "description": "Remote desc"}}
        youtube.channels().list().execute.return_value = {"items": [remote]}

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["push", "--apply", "--no-localizations"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "no diff" in out
        assert "localizations." not in out
        youtube.channels().update.assert_not_called()

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


class TestCLIPushQuota:
    """#2060: push の apply 経路が channels.update quota を part ごとに記録する。"""

    def _patch_youtube(self, youtube):
        return patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        )

    def test_dry_run_does_not_record_quota(self, capsys):
        """Given diff あり When push（dry-run） Then channels.update quota は記録されない。"""
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        with (
            self._patch_youtube(youtube),
            patch("youtube_automation.utils.cost_tracker.log_quota") as log_quota,
        ):
            rc = channel_settings_cli.main(["push"])
        assert rc == 0
        assert "dry-run" in capsys.readouterr().out
        log_quota.assert_not_called()

    def test_apply_records_quota_once_per_part(self, capsys):
        """Given diff あり When push --apply Then 実 request ごとに 50 units が 1 回記録される。"""
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        with (
            self._patch_youtube(youtube),
            patch("youtube_automation.utils.cost_tracker.log_quota") as log_quota,
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        assert rc == 0
        update_calls = youtube.channels().update.call_args_list
        assert len(update_calls) >= 1
        assert log_quota.call_count == len(update_calls)
        parts_called = [call.kwargs["part"] for call in update_calls]
        for quota_call, part in zip(log_quota.call_args_list, parts_called, strict=True):
            assert quota_call.args == ("youtube-data-api", "channels.update", 50)
            assert quota_call.kwargs["metadata"] == {"part": part, "channel_id": "UCfixture"}

    def test_apply_multiple_parts_records_match_request_count(self, capsys):
        """Given brandingSettings + status の複数 part When push --apply Then request 数と記録件数が一致する。"""
        youtube = MagicMock()
        remote = _mock_remote_response(description="old remote")
        remote["status"] = {"selfDeclaredMadeForKids": True}  # local fixture は False
        youtube.channels().list().execute.return_value = {"items": [remote]}
        with (
            self._patch_youtube(youtube),
            patch("youtube_automation.utils.cost_tracker.log_quota") as log_quota,
        ):
            rc = channel_settings_cli.main(["push", "--apply", "--no-localizations"])
        assert rc == 0
        update_calls = youtube.channels().update.call_args_list
        parts_called = [call.kwargs["part"] for call in update_calls]
        assert {"brandingSettings", "status"} <= set(parts_called)
        assert log_quota.call_count == len(update_calls)
        recorded_parts = [call.kwargs["metadata"]["part"] for call in log_quota.call_args_list]
        assert recorded_parts == parts_called

    def test_update_failure_records_quota_then_raises_api_error(self, capsys):
        """Given update が失敗 When push --apply Then quota 記録後に YouTubeAPIError（rc=1）が維持される。"""
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        youtube.channels().update().execute.side_effect = RuntimeError("boom")
        with (
            self._patch_youtube(youtube),
            patch("youtube_automation.utils.cost_tracker.log_quota") as log_quota,
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "channels().update" in err and "failed" in err
        # 実 request を発行済みのため、失敗した call の分も quota が記録される
        assert log_quota.call_count == 1

    def test_quota_record_failure_does_not_break_push(self, capsys):
        """Given log_quota が例外を投げる When push --apply Then push は成功のまま完了する。"""
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="old remote")]}
        with (
            self._patch_youtube(youtube),
            patch(
                "youtube_automation.utils.cost_tracker.log_quota",
                side_effect=RuntimeError("tracker down"),
            ),
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        assert rc == 0
        assert "pushed" in capsys.readouterr().out


def _fake_config(channel_id: str):
    """channel_id 照合テスト用の軽量 config スタブ（_cmd_push が触る属性のみ）。"""
    branding = SimpleNamespace(as_api_dict=lambda: {})
    localizations = SimpleNamespace(exists=False, data={})
    meta = SimpleNamespace(channel_id=channel_id, branding=branding)
    return SimpleNamespace(meta=meta, localizations=localizations)


class TestCLIPushChannelIdSafety:
    """#561: channel_id mismatch 時に push を拒否する。"""

    def test_mismatch_refuses_and_does_not_update(self, capsys):
        youtube = MagicMock()
        # remote の id は UCfixture
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response()]}
        with (
            patch("youtube_automation.scripts.channel_settings_cli.get_youtube", return_value=youtube),
            patch(
                "youtube_automation.scripts.channel_settings_cli.load_config",
                return_value=_fake_config("UCdifferent"),
            ),
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "channel_id mismatch" in err
        youtube.channels().update.assert_not_called()

    def test_match_proceeds(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response()]}
        with (
            patch("youtube_automation.scripts.channel_settings_cli.get_youtube", return_value=youtube),
            patch(
                "youtube_automation.scripts.channel_settings_cli.load_config",
                return_value=_fake_config("UCfixture"),
            ),
        ):
            rc = channel_settings_cli.main(["push", "--apply"])
        # id 一致 → mismatch エラーで止まらず通常フローへ進む
        assert rc == 0
        captured = capsys.readouterr()
        assert "channel_id mismatch" not in captured.out
        assert "channel_id mismatch" not in captured.err

    def test_unset_channel_id_warns_but_proceeds(self, capsys):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response()]}
        with (
            patch("youtube_automation.scripts.channel_settings_cli.get_youtube", return_value=youtube),
            patch(
                "youtube_automation.scripts.channel_settings_cli.load_config",
                return_value=_fake_config(""),
            ),
        ):
            rc = channel_settings_cli.main(["push"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "channel.channel_id が未設定" in out


class TestCLIPull:
    def test_no_localizations_hides_remote_localization_diff(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        remote = _mock_remote_response(description="Test channel description for sync.")
        remote["brandingSettings"]["channel"]["keywords"] = "chiptune 8-bit 'rpg music'"
        remote["brandingSettings"]["channel"]["defaultLanguage"] = "ja"
        remote["brandingSettings"]["channel"]["unsubscribedTrailer"] = "dQw4w9WgXcQ"
        remote["localizations"] = {"ja_JP": {"title": "Remote title", "description": "Remote desc"}}
        youtube.channels().list().execute.return_value = {"items": [remote]}

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull", "--no-localizations"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "no diff" in out
        assert "localizations." not in out

    def test_apply_no_localizations_skips_file_writes_for_localization_only_diff(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        remote = _mock_remote_response(description="Test channel description for sync.")
        remote["brandingSettings"]["channel"]["keywords"] = "chiptune 8-bit 'rpg music'"
        remote["brandingSettings"]["channel"]["defaultLanguage"] = "ja"
        remote["brandingSettings"]["channel"]["unsubscribedTrailer"] = "dQw4w9WgXcQ"
        remote["localizations"] = {"ja_JP": {"title": "Remote title", "description": "Remote desc"}}
        youtube.channels().list().execute.return_value = {"items": [remote]}
        config_path = tmp_path / "config" / "channel" / "meta.json"
        loc_path = tmp_path / "config" / "localizations.json"
        before_config = config_path.read_text(encoding="utf-8")
        before_loc = loc_path.read_text(encoding="utf-8")

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull", "--apply", "--no-localizations"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "no diff" in out
        assert "localizations." not in out
        assert config_path.read_text(encoding="utf-8") == before_config
        assert loc_path.read_text(encoding="utf-8") == before_loc

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

    def test_apply_writes_channel_id_and_youtube_channel_only(self, tmp_path, monkeypatch, capsys):
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
        assert after_data["channel"]["channel_id"] == "UCfixture"
        before_channel = dict(before_data["channel"])
        after_channel = dict(after_data["channel"])
        after_channel.pop("channel_id")
        assert after_channel == before_channel
        # sections other than channel / youtube_channel are untouched
        for key in before_data:
            if key in ("channel", "youtube_channel"):
                continue
            assert after_data[key] == before_data[key]

    def test_channel_id_only_dry_run_does_not_modify_meta_json(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response()]}
        config_path = tmp_path / "config" / "channel" / "meta.json"
        before = config_path.read_text(encoding="utf-8")

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull", "--channel-id-only"])
        assert rc == 0
        after = config_path.read_text(encoding="utf-8")
        assert before == after  # meta.json unchanged
        assert "dry-run" in capsys.readouterr().out

    def test_channel_id_only_apply_preserves_local_branding(self, tmp_path, monkeypatch, capsys):
        _prepare_channel_dir(tmp_path, monkeypatch)
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [_mock_remote_response(description="remote desc")]}
        config_path = tmp_path / "config" / "channel" / "meta.json"
        before_data = json.loads(config_path.read_text(encoding="utf-8"))

        with patch(
            "youtube_automation.scripts.channel_settings_cli.get_youtube",
            return_value=youtube,
        ):
            rc = channel_settings_cli.main(["pull", "--channel-id-only", "--apply"])
        assert rc == 0
        after_data = json.loads(config_path.read_text(encoding="utf-8"))

        assert after_data["channel"]["channel_id"] == "UCfixture"
        assert after_data["youtube_channel"] == before_data["youtube_channel"]


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
