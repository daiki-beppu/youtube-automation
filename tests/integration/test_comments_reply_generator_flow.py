"""comments.generator 設定が loader → replier → history まで伝搬する統合テスト."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from youtube_automation.utils.comments.generator.base import GeneratedReply
from youtube_automation.utils.comments.replier import CommentReplier
from youtube_automation.utils.config import load_config, reset


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _channel_sections() -> dict[str, dict]:
    return {
        "meta.json": {
            "channel": {
                "name": "Test Channel",
                "short": "TC",
                "youtube_handle": "@testchannel",
                "url": "https://youtube.com/@testchannel",
            }
        },
        "content.json": {
            "genre": {"primary": "jazz", "style": "lo-fi", "context": "rainy night"},
            "tags": {
                "base": ["jazz"],
                "themes": {"night": ["night jazz"]},
            },
            "descriptions": {
                "opening": "opening",
                "perfect_for": ["studying"],
                "hashtags": ["#Jazz"],
            },
            "title": {"template": "{theme} - {activity}"},
        },
        "youtube.json": {
            "youtube": {
                "category_id": "10",
                "privacy_status": "public",
                "language": "ja",
            }
        },
        "comments.json": {
            "comments": {
                "enabled": True,
                "generator": {
                    "type": "gemini",
                    "model": "gemini-2.5-flash",
                    "channel_persona": "Rain Jazz Night host",
                    "max_length": 180,
                    "fallback_on_error": "template",
                    "min_interval_sec": 2.5,
                },
                "rules": [
                    {
                        "name": "default_ai",
                        "pattern": ".+",
                        "generator": "gemini",
                    }
                ],
                "templates": {
                    "ja": {
                        "default": "ありがとうございます！",
                    }
                },
            }
        },
    }


def _setup_channel(tmp_path: Path) -> Path:
    channel_dir = tmp_path / "channel"
    for filename, data in _channel_sections().items():
        _write_json(channel_dir / "config" / "channel" / filename, data)
    return channel_dir


def _mock_youtube() -> MagicMock:
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "v1", "snippet": {"title": "Night Rain Jazz"}}]
    }

    def _list(**_kwargs):
        result = MagicMock()
        result.execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "canReply": True,
                        "totalReplyCount": 0,
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "authorDisplayName": "Alice",
                                "textOriginal": "first!",
                                "publishedAt": "2026-04-01T00:00:00Z",
                            },
                        },
                    }
                }
            ]
        }
        return result

    yt.commentThreads.return_value.list.side_effect = _list
    yt.comments.return_value.insert.return_value.execute.return_value = {"id": "reply1"}
    return yt


def test_loader_configured_generator_reaches_replier_and_history(tmp_path, monkeypatch):
    class _Generator:
        def __init__(self):
            self.calls = []

        def generate(self, ctx):
            self.calls.append(ctx)
            return GeneratedReply(text="AI reply", prompt="generated prompt")

    generator = _Generator()
    channel_dir = _setup_channel(tmp_path)
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": generator},
    )
    reset()

    config = load_config()
    replier = CommentReplier(
        _mock_youtube(),
        config=config.comments,
        channel_dir=channel_dir,
        default_language=config.youtube.api.language,
    )

    plan = replier.run(dry_run=False, video_ids=["v1"])

    assert len(plan.replied) == 1
    assert plan.replied[0]["generator"] == "gemini"
    assert plan.replied[0]["prompt"] == "generated prompt"
    assert generator.calls[0].channel_persona == "Rain Jazz Night host"
    assert generator.calls[0].max_length == 180
