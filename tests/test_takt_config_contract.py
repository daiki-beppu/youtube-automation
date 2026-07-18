"""repo-local takt config の継承境界を検証する。"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_CONFIG = _REPO_ROOT / ".takt" / "config.yaml"


def test_project_config_does_not_replace_global_routing() -> None:
    config = yaml.safe_load(_PROJECT_CONFIG.read_text(encoding="utf-8"))

    for inherited_key in (
        "provider",
        "model",
        "language",
        "concurrency",
        "task_poll_interval_ms",
        "persona_providers",
    ):
        assert inherited_key not in config, (
            f"{inherited_key} は ~/.takt/config.yaml から継承する。project 側で再宣言すると global routing が失われる"
        )


def test_project_config_keeps_only_repo_specific_runtime_settings() -> None:
    config = yaml.safe_load(_PROJECT_CONFIG.read_text(encoding="utf-8"))

    assert config["draft_pr"] is False
    assert config["base_branch"] == "main"
    assert config["runtime"]["prepare"] == [".takt/runtime-prepare.sh"]
    assert config["observability"]["enabled"] is True
    assert config["observability"]["usage_events_phase"] is True
