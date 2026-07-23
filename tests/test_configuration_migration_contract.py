"""B1 configuration owner and C-05/C-07 migration contracts.

Coverage matrix (the implementation step must keep every row green):

* B1-01: the configuration package exposes the eleven specified public names.
* B1-02: wf-next skip keys default to ``True`` and preserve explicit booleans.
* B1-03: wf-next ``approval_gates`` is rejected for every value shape.
* B1-04: post-publish approval gates remain supported in their own namespace.
* B1-05: comments ``rules`` is rejected for every value shape and is absent from
  the loaded model.
* B1-06: wf-batch reads the new skip-key fields directly and reports the new
  configuration path when a non-interactive run cannot proceed.
* B1-07: the new configuration package has no domains/commands dependency.
* B1-08: the master-audio reference CLI accepts the new skip-key direction.

The tests use the public configuration loader as the seam.  The wf-batch test
uses its settings snapshot seam because invoking external collection commands
would test process orchestration rather than configuration propagation.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.configuration import (
    ChannelConfig,
    CommunityDraft,
    Distrokid,
    PinnedComment,
    Shorts,
    load_config,
    reset,
)
from youtube_automation.utils.exceptions import ConfigError


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _minimal_sections() -> dict[str, dict]:
    return {
        "meta.json": {
            "channel": {
                "name": "Migration Test",
                "short": "MT",
                "youtube_handle": "@migration-test",
                "url": "https://youtube.com/@migration-test",
                "tagline": "Configuration migration",
            }
        },
        "content.json": {
            "genre": {"primary": "ambient", "style": "minimal", "context": "study"},
            "tags": {"base": ["ambient"], "themes": {"study": ["study music"]}},
            "descriptions": {
                "opening": "{style} {primary} for {context}",
                "perfect_for": ["Studying"],
                "hashtags": ["#Ambient"],
            },
            "title": {"template": "{theme} - {activity}"},
        },
        "youtube.json": {"youtube": {"category_id": "10", "privacy_status": "public", "language": "ja"}},
    }


def _channel(tmp_path: Path, *, workflow: dict | None = None, comments: dict | None = None) -> Path:
    sections = _minimal_sections()
    if workflow is not None:
        sections["workflow.json"] = {"workflow": workflow}
    if comments is not None:
        sections["comments.json"] = {"comments": comments}
    root = tmp_path / "channel"
    for filename, value in sections.items():
        _write_json(root / "config" / "channel" / filename, value)
    return root


@pytest.fixture(autouse=True)
def _reset_configuration(monkeypatch):
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.delenv("CHANNEL", raising=False)
    reset()
    yield
    reset()


def test_configuration_public_api_preserves_the_specified_exports():
    from youtube_automation import configuration

    assert configuration.__all__ == [
        "ChannelConfig",
        "CommunityDraft",
        "Distrokid",
        "PinnedComment",
        "Shorts",
        "channel_dir",
        "find_workspace_root",
        "load_config",
        "reset",
        "select_channel",
        "workspace_channels",
    ]
    assert configuration.ChannelConfig is ChannelConfig
    assert configuration.CommunityDraft is CommunityDraft
    assert configuration.Distrokid is Distrokid
    assert configuration.PinnedComment is PinnedComment
    assert configuration.Shorts is Shorts


def test_channel_config_is_owned_by_configuration_model():
    from youtube_automation.configuration.model import ChannelConfig as ModelChannelConfig

    assert ChannelConfig is ModelChannelConfig


def test_configuration_package_has_no_domains_or_commands_dependency():
    configuration_root = Path(__file__).parents[1] / "src" / "youtube_automation" / "configuration"
    dependencies: list[tuple[str, str]] = []
    for path in configuration_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            if any(part in {"domains", "commands"} for name in imported for part in name.split(".")):
                dependencies.extend((path.name, name) for name in imported)

    assert dependencies == []


def test_wf_next_skip_keys_default_true_and_preserve_explicit_values(tmp_path, monkeypatch):
    default_channel = _channel(tmp_path / "default")
    monkeypatch.setenv("CHANNEL_DIR", str(default_channel))

    default_config = load_config()

    assert default_config.workflow.wf_next.skip_audio_approval is True
    assert default_config.workflow.wf_next.skip_upload_approval is True
    assert not hasattr(default_config.workflow.wf_next, "approval_gates")

    reset()
    explicit_channel = _channel(
        tmp_path / "explicit",
        workflow={"wf_next": {"skip_audio_approval": False, "skip_upload_approval": True}},
    )
    monkeypatch.setenv("CHANNEL_DIR", str(explicit_channel))

    explicit_config = load_config()

    assert explicit_config.workflow.wf_next.skip_audio_approval is False
    assert explicit_config.workflow.wf_next.skip_upload_approval is True


@pytest.mark.parametrize("skip_value", [None, "false", 0, 1, []])
def test_wf_next_skip_keys_require_boolean(tmp_path, monkeypatch, skip_value):
    channel = _channel(tmp_path, workflow={"wf_next": {"skip_audio_approval": skip_value}})
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    with pytest.raises(ConfigError, match=r"workflow\.wf_next\.skip_audio_approval"):
        load_config()


@pytest.mark.parametrize("legacy_value", [{}, {"audio": True}, [], "legacy", False, None])
def test_wf_next_approval_gates_is_always_rejected(tmp_path, monkeypatch, legacy_value):
    channel = _channel(tmp_path, workflow={"wf_next": {"approval_gates": legacy_value}})
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    with pytest.raises(ConfigError, match=r"workflow\.wf_next\.approval_gates"):
        load_config()


def test_post_publish_approval_gates_remain_supported(tmp_path, monkeypatch):
    channel = _channel(
        tmp_path,
        workflow={"post-publish": {"approval_gates": {"pinned-comment": True}}},
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    post_publish = load_config().workflow.post_publish

    assert post_publish.approval_gates.pinned_comment is True
    assert post_publish.approval_gates.community_post is False
    assert post_publish.approval_gates.metadata_audit is False


@pytest.mark.parametrize("rules_value", [[], None, {}, "legacy", False, [{"name": "old"}]])
def test_comments_rules_is_rejected_by_key_presence(tmp_path, monkeypatch, rules_value):
    channel = _channel(tmp_path, comments={"rules": rules_value})
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    with pytest.raises(ConfigError, match=r"comments\.rules"):
        load_config()


def test_comments_loader_returns_supported_configuration(tmp_path, monkeypatch):
    channel = _channel(tmp_path, comments={"enabled": False})
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    comments = load_config().comments

    assert comments.enabled is False
    assert comments.generator.provider == "codex"
    assert comments.max_replies_per_run == 20


def test_wf_batch_snapshots_new_skip_key_values(monkeypatch):
    from youtube_automation.scripts import wf_batch

    monkeypatch.setattr(
        wf_batch,
        "load_config",
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(
                wf_next=SimpleNamespace(
                    skip_manual_mastering=True,
                    skip_audio_approval=False,
                    skip_upload_approval=True,
                )
            )
        ),
    )

    settings = wf_batch._wf_next_settings()

    assert settings.skip_manual_mastering is True
    assert settings.skip_audio_approval is False
    assert settings.skip_upload_approval is True
    assert not hasattr(settings, "approval_gate_audio")
    assert not hasattr(settings, "approval_gate_upload")


def test_wf_batch_receives_skip_keys_from_the_real_configuration_loader(tmp_path, monkeypatch):
    channel = _channel(
        tmp_path,
        workflow={"wf_next": {"skip_audio_approval": False, "skip_upload_approval": True}},
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    from youtube_automation.scripts import wf_batch

    settings = wf_batch._wf_next_settings()

    assert settings.skip_audio_approval is False
    assert settings.skip_upload_approval is True


def test_master_audio_transition_uses_skip_audio_approval_cli(tmp_path):
    collection = tmp_path / "collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "01-master" / "raw-master.wav").write_bytes(b"raw")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "assets": {"raw_master": "raw-master.wav", "master_audio": None},
            }
        ),
        encoding="utf-8",
    )

    script = Path(__file__).parents[1] / ".claude" / "skills" / "wf-next" / "references" / "master_audio_transition.py"

    result = subprocess.run(
        [
            "python3",
            str(script),
            str(collection),
            "--skip-manual-mastering",
            "true",
            "--skip-audio-approval",
            "true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"


@pytest.mark.parametrize(
    ("skip_audio_approval", "skip_upload_approval"),
    [(False, True), (True, False), (False, False)],
)
def test_wf_batch_main_rejects_real_configuration_before_external_commands(
    tmp_path, monkeypatch, capsys, skip_audio_approval, skip_upload_approval
):
    channel = _channel(
        tmp_path,
        workflow={
            "wf_next": {
                "skip_audio_approval": skip_audio_approval,
                "skip_upload_approval": skip_upload_approval,
            }
        },
    )
    collection = channel / "collections" / "planning" / "001-a-collection"
    (collection / "02-Individual-music").mkdir(parents=True)
    (collection / "02-Individual-music" / "01-track.mp3").write_bytes(b"audio")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "assets": {"music_prompts": True, "raw_master": None},
                "planning": {"music": {"suno_playlist_url": "https://suno.com/playlist/test"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel))

    from youtube_automation.scripts import wf_batch

    def fail_if_external_command_runs(*args, **kwargs):
        raise AssertionError("wf-batch must reject before starting external commands")

    monkeypatch.setattr(wf_batch, "_run_command", fail_if_external_command_runs)

    result = wf_batch.main([])

    assert result == 1
    error = capsys.readouterr().err
    assert "workflow.wf_next.skip_audio_approval" in error
    assert "skip_upload_approval" in error
