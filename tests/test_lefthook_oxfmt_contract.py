from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_oxfmt_hook_allows_unmatched_patterns_and_syncs_ignore_excludes() -> None:
    config = yaml.safe_load((ROOT / "lefthook.yml").read_text(encoding="utf-8"))
    oxfmt = config["pre-commit"]["commands"]["oxfmt"]

    assert "--no-error-on-unmatched-pattern" in oxfmt["run"]
    assert "poc/**" in oxfmt.get("exclude", [])


def test_oxfmt_config_ignores_poc_directory() -> None:
    oxfmt_config = (ROOT / "oxfmt.config.ts").read_text(encoding="utf-8")

    assert '"poc/**"' in oxfmt_config
