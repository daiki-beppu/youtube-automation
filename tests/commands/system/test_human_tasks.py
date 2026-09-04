from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from youtube_automation.commands.system import human_tasks
from youtube_automation.domains.human_tasks import HumanTaskReport


def test_command_composes_canonical_channel_config_and_discord_notifier(monkeypatch, tmp_path: Path) -> None:
    notifier = object()
    recorded: dict[str, object] = {}

    def fake_generate(channel_root: Path, *, channel: str, distrokid_enabled: bool, notifier: object):
        recorded.update(
            channel_root=channel_root,
            channel=channel,
            distrokid_enabled=distrokid_enabled,
            notifier=notifier,
        )
        return SimpleNamespace(path=tmp_path / "human-tasks.md", report=HumanTaskReport(channel, ()))

    monkeypatch.setattr(
        human_tasks,
        "load_config_from_path",
        lambda _path: SimpleNamespace(
            meta=SimpleNamespace(channel_short="soulful-grooves"),
            distrokid=SimpleNamespace(enabled=True),
        ),
    )
    monkeypatch.setattr(human_tasks, "create_discord_notification_sink", lambda: notifier)
    monkeypatch.setattr(human_tasks, "generate_human_tasks", fake_generate)

    assert human_tasks.run(Namespace(channel_dir=tmp_path)) == 0
    assert recorded == {
        "channel_root": tmp_path,
        "channel": "soulful-grooves",
        "distrokid_enabled": True,
        "notifier": notifier,
    }
