"""metadata_audit のリモート監査ロジックの回帰テスト.

YouTube Data API v3 公式コード `zh-CN` / `zh-TW` への期待値判定を検証する。
issue #82 の再発防止として、旧コード (`zh-Hans` / `zh-Hant`) を期待値に戻さないことを保証する。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers.video_description import write_video_description_pair
from youtube_automation.commands.metadata.metadata_audit import audit_local, audit_remote

_ZH_ISSUE_TOKEN = "zh codes"  # `metadata_audit.py` のエラー文言 "YT zh codes are ..." に対応


def _yt_response(video_id: str, locs: dict[str, dict]) -> dict:
    """`videos.list()` レスポンスを最小構成で組み立てる."""
    return {
        "items": [
            {
                "id": video_id,
                "snippet": {"title": "test title", "description": "test description"},
                "localizations": locs,
            }
        ]
    }


def _patched_yt(response: dict) -> MagicMock:
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = response
    return yt


def _audit_config(
    supported_languages: list[str],
    *,
    target_duration_min: float | None = None,
    target_duration_max: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(
            chapter_max=12,
            target_duration_min=target_duration_min,
            target_duration_max=target_duration_max,
        ),
        content=SimpleNamespace(
            tags=SimpleNamespace(
                min_count=None,
                for_collection=lambda _name: ["fallback"],
            )
        ),
        localizations=SimpleNamespace(supported_languages=supported_languages),
    )


def _write_local_collection(
    tmp_path: Path,
    *,
    scene_phrases: dict[str, str],
    description: str,
    title_heading: str = "タイトル案",
    write_workflow_state: bool = True,
) -> Path:
    collection_dir = tmp_path / "20260622-test-collection"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    source = write_video_description_pair(
        docs_dir,
        title="Continuous Focus Mix",
        description=description,
        tags=["fallback"],
    )
    if title_heading != "タイトル案":
        document = json.loads(source.read_text(encoding="utf-8"))
        document["title"] = ""
        source.write_text(json.dumps(document), encoding="utf-8")
    if write_workflow_state:
        (collection_dir / "workflow-state.json").write_text(
            json.dumps({"scene_phrases": scene_phrases}, ensure_ascii=False),
            encoding="utf-8",
        )
    return collection_dir


class TestAuditLocalPreflightContract:
    def test_duration_targets_are_converted_from_minutes_to_seconds(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={"en": "continuous focus mix"},
            description="A continuous BGM mix without chapter markers.",
        )
        master = collection_dir / "01-master" / "Complete-Collection-Master.mp4"
        master.parent.mkdir()
        master.touch()

        with patch("youtube_automation.commands.metadata.metadata_audit.probe_duration", return_value=50 * 60):
            issues = audit_local(
                collection_dir,
                _audit_config(
                    ["en"],
                    target_duration_min=60,
                    target_duration_max=90,
                ),
            )

        assert issues == ["duration: 50m (target 1h00m〜1h30m)"]

    def test_duration_check_remains_disabled_without_targets(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={"en": "continuous focus mix"},
            description="A continuous BGM mix without chapter markers.",
        )
        master = collection_dir / "01-master" / "Complete-Collection-Master.mp4"
        master.parent.mkdir()
        master.touch()

        with patch("youtube_automation.commands.metadata.metadata_audit.probe_duration") as probe:
            assert audit_local(collection_dir, _audit_config(["en"])) == []

        probe.assert_not_called()

    def test_en_only_channel_without_timestamps_passes(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={"en": "continuous focus mix"},
            description="A continuous BGM mix without chapter markers.",
        )

        assert audit_local(collection_dir, _audit_config(["en"])) == []

    def test_scene_phrases_require_only_supported_languages(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={"ja": "連続作業用ミックス"},
            description="A continuous BGM mix without chapter markers.",
        )

        assert audit_local(collection_dir, _audit_config(["ja"])) == []

    def test_single_language_channel_without_scene_phrases_passes(self, tmp_path: Path) -> None:
        """単一言語チャンネルは populate が no-op のため scene_phrases 無しでも audit が通る (#1470)."""
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={},
            description="A continuous BGM mix without chapter markers.",
        )

        assert audit_local(collection_dir, _audit_config(["en"])) == []

    def test_single_language_channel_malformed_workflow_state_is_reported(self, tmp_path: Path) -> None:
        """破損した workflow-state.json は素の JSONDecodeError を漏らさず監査結果へ載せる."""
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={},
            description="A continuous BGM mix without chapter markers.",
        )
        (collection_dir / "workflow-state.json").write_text("{not json", encoding="utf-8")

        issues = audit_local(collection_dir, _audit_config(["en"]))

        assert any("workflow-state.json invalid" in issue for issue in issues)

    def test_invalid_description_pair_reports_schema_diagnostic(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={"en": "continuous focus mix"},
            description="A continuous BGM mix without chapter markers.",
            title_heading="タイトル",
        )

        issues = audit_local(collection_dir, _audit_config(["en"]))

        assert len(issues) == 1
        message = issues[0]
        assert "descriptions.json invalid" in message
        assert "pointer=/title" in message

    def test_invalid_description_pair_stops_metadata_audit_fail_closed(self, tmp_path: Path) -> None:
        collection_dir = _write_local_collection(
            tmp_path,
            scene_phrases={},
            description="A continuous BGM mix without chapter markers.",
            title_heading="タイトル",
            write_workflow_state=False,
        )
        cfg = _audit_config(["en"])
        cfg.content.tags.min_count = 2

        issues = audit_local(collection_dir, cfg)

        assert len(issues) == 1
        assert "descriptions.json invalid" in issues[0]


class TestAuditRemoteZhCodes:
    """audit_remote の zh-codes 期待値判定."""

    @pytest.mark.parametrize(
        "locs, expected_count, must_contain",
        [
            pytest.param(
                {
                    "zh-CN": {"title": "标题", "description": "desc"},
                    "zh-TW": {"title": "標題", "description": "desc"},
                },
                0,
                [],
                id="canonical_codes_pass",
            ),
            pytest.param(
                {
                    "zh-Hans": {"title": "标题", "description": "desc"},
                    "zh-Hant": {"title": "標題", "description": "desc"},
                },
                1,
                ["zh-CN", "zh-TW"],
                id="legacy_codes_flagged",
            ),
            pytest.param(
                {"zh-CN": {"title": "标题", "description": "desc"}},
                1,
                [],
                id="partial_codes_flagged",
            ),
        ],
    )
    def test_zh_codes(self, locs: dict[str, dict], expected_count: int, must_contain: list[str]) -> None:
        video_id = "VID"
        with patch(
            "youtube_automation.infrastructure.google.youtube.YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=_patched_yt(_yt_response(video_id, locs))),
        ):
            result = audit_remote({video_id: "test-collection"})
        zh_issues = [i for i in result[video_id] if _ZH_ISSUE_TOKEN in i]
        assert len(zh_issues) == expected_count
        for token in must_contain:
            assert token in zh_issues[0]


class TestRemoteChapterMaxSkillConfig:
    """REMOTE チェックのチャプター上限が skill-config で上書き可能なこと (#1669)."""

    @pytest.fixture(autouse=True)
    def _reset_skill_config_cache(self):
        from youtube_automation.configuration import skills as skill_config

        skill_config.reset("audit.metadata")
        yield
        skill_config.reset("audit.metadata")

    def test_default_remote_chapter_max_is_12(self) -> None:
        from youtube_automation.commands.metadata.metadata_audit import _remote_chapter_max

        assert _remote_chapter_max() == 12

    def test_channel_override_changes_remote_chapter_max(self, tmp_path: Path, monkeypatch) -> None:
        from youtube_automation.commands.metadata.metadata_audit import _remote_chapter_max

        channel = tmp_path / "ch"
        (channel / "config" / "skills").mkdir(parents=True)
        (channel / "config" / "skills" / "metadata-audit.yaml").write_text(
            "chapters:\n  remote_max: 20\n", encoding="utf-8"
        )
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        assert _remote_chapter_max() == 20

    def test_audit_remote_flags_chapters_over_default_limit(self) -> None:
        video_id = "VID"
        desc = "\n".join(f"{i:02d}:00 Track {i}" for i in range(13))
        response = {
            "items": [
                {
                    "id": video_id,
                    "snippet": {"title": "test title", "description": desc},
                    "localizations": {},
                }
            ]
        }
        with patch(
            "youtube_automation.infrastructure.google.youtube.YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=_patched_yt(response)),
        ):
            result = audit_remote({video_id: "test-collection"})
        assert any("chapters (>12)" in issue for issue in result[video_id])

    def test_audit_remote_continues_when_quota_recording_fails(self) -> None:
        """REQ-2791-01: quota 台帳失敗は remote audit を停止させない."""
        video_id = "VID"
        response = _yt_response(video_id, {})
        with (
            patch(
                "youtube_automation.infrastructure.google.youtube.YouTubeClients",
                return_value=SimpleNamespace(youtube_readonly=_patched_yt(response)),
            ),
            patch(
                "youtube_automation.commands.metadata.metadata_audit.cost_tracker.log_quota",
                side_effect=OSError("quota ledger unavailable"),
            ),
        ):
            result = audit_remote({video_id: "test-collection"})

        assert result == {video_id: []}

    @pytest.mark.parametrize("snippet", [None, [], "invalid"])
    def test_audit_remote_reports_non_object_snippet_without_stopping(self, snippet: object) -> None:
        """REQ-2791-02: snippet 非 object を診断して次動画へ継続する."""
        response = {
            "items": [
                {"id": "BROKEN", "snippet": snippet, "localizations": {}},
                {
                    "id": "VALID",
                    "snippet": {"title": "valid", "description": ""},
                    "localizations": {},
                },
            ]
        }
        with patch(
            "youtube_automation.infrastructure.google.youtube.YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=_patched_yt(response)),
        ):
            result = audit_remote({"BROKEN": "broken", "VALID": "valid"})

        assert result["BROKEN"] == ["YT snippet missing or not an object"]
        assert result["VALID"] == []

    def test_audit_remote_reports_missing_snippet_without_stopping(self) -> None:
        response = {
            "items": [
                {"id": "BROKEN", "localizations": {}},
                {
                    "id": "VALID",
                    "snippet": {"title": "valid", "description": ""},
                    "localizations": {},
                },
            ]
        }
        with patch(
            "youtube_automation.infrastructure.google.youtube.YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=_patched_yt(response)),
        ):
            result = audit_remote({"BROKEN": "broken", "VALID": "valid"})

        assert result["BROKEN"] == ["YT snippet missing or not an object"]
        assert result["VALID"] == []
