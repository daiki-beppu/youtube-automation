"""yt-title-duplicate-check CLI boundary tests."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.scripts import title_duplicate_check as cli
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError


def _write_description(collection: Path, title: str) -> None:
    path = CollectionPaths(collection).descriptions_md_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"## タイトル案\n\n```\n{title}\n```\n", encoding="utf-8")


def test_title_option_scans_live_titles_and_default_exit_zero(tmp_path, monkeypatch):
    collections_root = tmp_path / "collections"
    live = collections_root / "live" / "20260601-old-collection"
    _write_description(live, "Rainy Jazz for Focus")
    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(ConfigError("no config")))

    rc = cli.main(["--title", "Rainy Jazz for Work", "--collections-root", str(collections_root)])

    assert rc == 0


def test_strict_returns_one_when_warning_found(tmp_path, monkeypatch):
    collections_root = tmp_path / "collections"
    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(ConfigError("no config")))
    monkeypatch.setattr(cli, "check_title_duplicate_warnings", lambda *_args, **_kwargs: ["duplicate"])

    rc = cli.main(["--title", "Rainy Jazz", "--collections-root", str(collections_root), "--strict"])

    assert rc == 1


def test_collection_argument_reads_descriptions_and_self_excludes(tmp_path, monkeypatch):
    collections_root = tmp_path / "collections"
    current = collections_root / "live" / "20260602-current-collection"
    other = collections_root / "live" / "20260601-other-collection"
    _write_description(current, "Current Title")
    _write_description(other, "Other Title")
    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(ConfigError("no config")))
    captured: dict[str, object] = {}

    def fake_check(title, existing_titles, template_check_cfg):
        captured["title"] = title
        captured["existing_titles"] = existing_titles
        captured["template_check_cfg"] = template_check_cfg
        return []

    monkeypatch.setattr(cli, "check_title_duplicate_warnings", fake_check)

    rc = cli.main([str(current), "--collections-root", str(collections_root)])

    assert rc == 0
    assert captured["title"] == "Current Title"
    assert captured["existing_titles"] == ["Other Title"]
