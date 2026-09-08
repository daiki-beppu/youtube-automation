import json
from pathlib import Path

import pytest

from youtube_automation.application.channel_readiness.readiness import (
    _read_json_mapping,
    _read_yaml_mapping,
    evaluate_ttp_wf_new_readiness,
)
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document


def _publish_persona(tmp_path, *, status: str = "hypothesis", scene_ids: list[str] | None = None) -> None:
    path = tmp_path / "docs/channel/personas/persona-definition.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "document_type": "persona",
                "updated_at": "2026-08-24T00:00:00Z",
                "status": status,
                "persona": {"id": "primary", "name": "Primary", "desires": ["focus"]},
                "scene_ids": [] if scene_ids is None else scene_ids,
                "evidence": [{"id": "ev-1", "source_path": "legacy.md", "observation": "migrated"}],
            }
        ),
        encoding="utf-8",
    )
    publish_json_document(path, RepositorySchema.CHANNEL_STRATEGY)


def test_ttp_readiness_reports_missing_analytics_config(tmp_path) -> None:
    result = evaluate_ttp_wf_new_readiness(tmp_path)

    assert result.status == "warn"
    assert result.message == (
        "config/channel/analytics.json 未生成。/wf-new 接続前に承認済み TTP 対象の保存が必要; "
        "docs/channel/personas/persona-definition.md 未作成"
    )
    assert result.next_action == {
        "kind": "human",
        "instructions": (
            "/setup --channel Step 4 で config を生成し、Step 5 以降で承認済み TTP 対象を "
            "config/channel/analytics.json::benchmark.channels に保存してください。"
            "ペルソナの不足はユーザー承認済み例外にせず、/channel-strategy --persona で検証済み "
            "persona-definition.json + .html pair を更新してください"
        ),
    }


def test_ttp_readiness_prefers_validated_persona_json_pair_over_legacy_markdown(tmp_path) -> None:
    legacy = tmp_path / "docs/channel/personas/persona-definition.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy without required headings", encoding="utf-8")
    _publish_persona(tmp_path)

    result = evaluate_ttp_wf_new_readiness(tmp_path)

    assert result.status == "warn"
    assert "analytics.json 未生成" in result.message
    assert "persona-definition" not in result.message


def test_confirmed_persona_json_requires_nonempty_scene_references(tmp_path) -> None:
    _publish_persona(tmp_path, status="confirmed")

    result = evaluate_ttp_wf_new_readiness(tmp_path)

    assert "confirmed persona の scene_ids が空です" in result.message


def test_tampered_persona_html_pair_does_not_fall_back_to_legacy_markdown(tmp_path) -> None:
    _publish_persona(tmp_path)
    (tmp_path / "docs/channel/personas/persona-definition.html").write_text("tampered", encoding="utf-8")

    result = evaluate_ttp_wf_new_readiness(tmp_path)

    assert "JSON+HTML pair" in result.message or "+ .html pair" in result.message


@pytest.mark.parametrize("reader", [_read_json_mapping, _read_yaml_mapping])
@pytest.mark.parametrize("contents", [None, '{"enabled": false, "future": [1]}', "[]"])
def test_readiness_config_mapping_distinguishes_missing_object_and_array(tmp_path: Path, reader, contents) -> None:
    path = tmp_path / "config"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")

    result = reader(path)

    if contents == "[]":
        assert result.data == {}
        assert result.error == f"{path.as_posix()} のトップレベルが object ではありません"
    else:
        assert result.data == ({} if contents is None else {"enabled": False, "future": [1]})
        assert result.error is None


@pytest.mark.parametrize("reader,format_name", [(_read_json_mapping, "JSON"), (_read_yaml_mapping, "YAML")])
def test_readiness_config_mapping_preserves_format_specific_error(tmp_path: Path, reader, format_name: str) -> None:
    path = tmp_path / "config"
    path.write_text("{", encoding="utf-8")

    result = reader(path)

    assert result.data == {}
    assert result.error is not None
    assert result.error.startswith(f"{path.as_posix()} が {format_name} として不正 (")


@pytest.mark.parametrize("reader", [_read_json_mapping, _read_yaml_mapping])
def test_readiness_config_mapping_reports_unreadable_existing_path(tmp_path: Path, reader) -> None:
    result = reader(tmp_path)

    assert result.data == {}
    assert result.error is not None
    assert result.error.startswith(f"{tmp_path.as_posix()} を読み込めません (")
