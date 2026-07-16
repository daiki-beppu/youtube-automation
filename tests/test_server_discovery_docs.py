from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCUMENTS = [
    ROOT / "extensions" / "suno-helper" / "README.md",
    ROOT / "extensions" / "distrokid-helper" / "README.md",
    ROOT / ".claude" / "skills" / "suno-helper" / "SKILL.md",
    ROOT / ".claude" / "skills" / "distrokid-helper" / "SKILL.md",
]
DISCOVERY_CONTRACT_DOCUMENTS = [
    ROOT / "docs" / "architecture.md",
    ROOT / "extensions" / "suno-helper" / "README.md",
    ROOT / "extensions" / "distrokid-helper" / "README.md",
]


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.parent.name + "/" + path.name)
def test_server_source_docs_describe_dynamic_registry_refresh_and_permanent_default(path: Path):
    text = path.read_text(encoding="utf-8")

    assert "動的検出" in text
    assert "http://localhost:7872/.well-known/yt-collection-serve" in text
    assert "selector を開く" in text
    assert "更新完了後" in text or "候補更新後" in text
    assert "http://youtube-automation.localhost:7873" in text
    assert "常に表示" in text
    assert re.search(r"yt-collection-serve\b[^\n]*--port\s+(?!7873\b)\d+", text)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.parent.name + "/" + path.name)
def test_server_source_docs_do_not_instruct_users_to_accumulate_or_reload_stale_candidates(path: Path):
    text = path.read_text(encoding="utf-8")
    normalized_lines = [re.sub(r"\s+", " ", line).strip().lower() for line in text.splitlines()]
    forbidden_observations = [
        "候補を自動保存",
        "登録済み候補",
        "localhost:7874 を選択",
        "ページを reload",
        "ページをリロードして再取得",
    ]

    for forbidden in forbidden_observations:
        assert all(forbidden.lower() not in line for line in normalized_lines)


def test_distrokid_readme_numbered_procedures_are_contiguous():
    text = (ROOT / "extensions" / "distrokid-helper" / "README.md").read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text)
    numbered_blocks = []
    for block in blocks:
        numbers = [int(value) for value in re.findall(r"(?m)^(\d+)\.\s+", block)]
        if numbers:
            numbered_blocks.append(numbers)

    assert numbered_blocks
    for numbers in numbered_blocks:
        assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize("path", DISCOVERY_CONTRACT_DOCUMENTS, ids=lambda path: path.parent.name + "/" + path.name)
def test_primary_docs_publish_complete_discovery_and_storage_contract(path: Path):
    text = path.read_text(encoding="utf-8")

    for field in (
        '"schema_version"',
        '"ttl_seconds"',
        '"servers"',
        '"instance_id"',
        '"expires_at"',
        '"server_info"',
        '"channel_name"',
        '"channel_short"',
        '"hostname"',
        '"port"',
        '"base_url"',
        '"label"',
    ):
        assert field in text
    for rule in ("heartbeat", "DELETE", "TTL", "Origin", "415", "403", "400", "413", "429"):
        assert rule in text
    assert "ytCollectionServeSources" in text
    assert "選択中 URL" in text
