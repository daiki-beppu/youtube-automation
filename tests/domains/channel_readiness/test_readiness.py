import json

from youtube_automation.domains.channel_readiness import evaluate_ttp_wf_new_readiness
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
