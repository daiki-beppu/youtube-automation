"""analytics-collect の depth 成果物 validator 契約テスト。"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / ".claude/skills/analytics-collect/references/validate-depth.sh"


def _run_validator_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VALIDATOR), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_validator(tmp_path: Path, payload: dict, depth: str) -> subprocess.CompletedProcess[str]:
    analytics_json = tmp_path / "analytics.json"
    analytics_json.write_text(json.dumps(payload), encoding="utf-8")
    return _run_validator_cli(str(analytics_json), depth)


def test_rejects_invalid_argument_count() -> None:
    result = _run_validator_cli()

    assert result.returncode == 2
    assert result.stderr == "usage: validate-depth.sh <analytics-json> <standard|full>\n"


def test_rejects_missing_analytics_json(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    result = _run_validator_cli(str(missing_path), "standard")

    assert result.returncode == 1
    assert result.stderr == f"analytics JSON not found: {missing_path}\n"


def test_rejects_unsupported_depth(tmp_path: Path) -> None:
    analytics_json = tmp_path / "analytics.json"
    analytics_json.write_text('{"collection_depth":"standard"}', encoding="utf-8")

    result = _run_validator_cli(str(analytics_json), "deep")

    assert result.returncode == 2
    assert result.stderr == "unsupported depth: deep\n"


def test_full_depth_accepts_retention_and_country_payload(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {
            "collection_depth": "full",
            "retention": [
                {
                    "video_id": "VID_1",
                    "average_retention": 0.62,
                    "midpoint_retention": 0.55,
                    "data_points": 1,
                    "retention_curve": [{"elapsed_ratio": 0.5, "watch_ratio": 0.55}],
                }
            ],
            "audience": {"by_country": {"countries": {}}},
        },
        "full",
    )

    assert result.returncode == 0, result.stderr


def test_full_depth_rejects_empty_retention_payload(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {
            "collection_depth": "full",
            "retention": [],
            "audience": {"by_country": {"countries": {}}},
        },
        "full",
    )

    assert result.returncode != 0


def test_full_depth_rejects_non_analyzable_retention_payload(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {
            "collection_depth": "full",
            "retention": [{"video_id": "VID_1"}],
            "audience": {"by_country": {"countries": {}}},
        },
        "full",
    )

    assert result.returncode != 0


def test_full_depth_rejects_payload_without_country(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {"collection_depth": "full", "retention": [], "audience": {}},
        "full",
    )

    assert result.returncode != 0


def test_full_depth_rejects_country_api_error(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {
            "collection_depth": "full",
            "retention": [],
            "audience": {"by_country": {"countries": {}, "error": "country API failed"}},
        },
        "full",
    )

    assert result.returncode != 0


def test_full_depth_rejects_retention_api_error(tmp_path: Path) -> None:
    result = _run_validator(
        tmp_path,
        {
            "collection_depth": "full",
            "retention": [{"video_id": "VID_1", "error": "retention API failed"}],
            "audience": {"by_country": {"countries": {}}},
        },
        "full",
    )

    assert result.returncode != 0


def test_standard_depth_accepts_standard_payload(tmp_path: Path) -> None:
    result = _run_validator(tmp_path, {"collection_depth": "standard"}, "standard")

    assert result.returncode == 0, result.stderr
