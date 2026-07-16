"""Executable verdicts used by the flop-analysis skill."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "flop-analysis" / "references" / "verification.py"


def _run_cli(operation: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--operation", operation],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def _load_module():
    spec = importlib.util.spec_from_file_location("flop_analysis_verification", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tokenize_removes_format_duration_and_numeric_tokens() -> None:
    verification = _load_module()

    assert verification.tokenize("Ｒａｉｎ Jazz - 2 Hours BGM") == ("rain", "jazz")


def test_term_classification_recognizes_mismatched_promises_and_document_frequency() -> None:
    verification = _load_module()

    result = verification.classify_terms(
        title="Rain Rock for Sleep - 2 Hours",
        genre_vocabulary=("jazz", "rock"),
        scene_vocabulary=("study", "sleep"),
        competitor_titles=("Jazz Study Rain", "Jazz Sleep", "Rain Focus"),
    )

    assert result.genre_terms == ("rock",)
    assert result.scene_terms == ("sleep",)
    assert result.subject_terms == ("rain",)
    assert result.frequent_competitor_terms[:3] == ("jazz", "rain", "focus")


@pytest.mark.parametrize(
    ("title", "expected_verdict", "expected_conflicts"),
    [
        ("Rain Jazz for Study - 2 Hours", "refuted", ()),
        ("Rain Rock for Study - 2 Hours", "supported", ("genre_mood",)),
        ("Rain Jazz for Sleep - 2 Hours", "supported", ("viewing_scene",)),
        ("Rain Jazz for Study - 30 Minutes", "supported", ("duration_format",)),
        ("Rain Jazz Single for Study - 2 Hours", "supported", ("duration_format",)),
    ],
)
def test_title_alignment_reaches_refuted_and_each_supported_axis(
    title: str,
    expected_verdict: str,
    expected_conflicts: tuple[str, ...],
) -> None:
    verification = _load_module()

    result = verification.evaluate_title_alignment(
        title=title,
        genre_vocabulary=("jazz", "rock"),
        scene_vocabulary=("study", "sleep"),
        actual_genre_texts=("rain jazz", "calm jazz"),
        actual_scene_texts=("study", "focus"),
        thumbnail_scene_texts=("study desk",),
        duration_seconds=7200,
        actual_content_type="collection",
    )

    assert result.verdict == expected_verdict
    assert result.conflicts == expected_conflicts


def test_title_alignment_is_unverified_when_required_inputs_are_missing() -> None:
    verification = _load_module()

    result = verification.evaluate_title_alignment(
        title="Rain Jazz for Study",
        genre_vocabulary=(),
        scene_vocabulary=("study",),
        actual_genre_texts=("jazz",),
        actual_scene_texts=("study",),
        thumbnail_scene_texts=("study",),
        duration_seconds=7200,
        actual_content_type="collection",
    )

    assert result.verdict == "unverified"
    assert result.reason == "missing required inputs: genre_vocabulary"


def test_title_alignment_uses_thumbnail_scene_as_an_alignment_input() -> None:
    verification = _load_module()

    result = verification.evaluate_title_alignment(
        title="Rain Jazz for Study",
        genre_vocabulary=("jazz",),
        scene_vocabulary=("study", "sleep"),
        actual_genre_texts=("jazz",),
        actual_scene_texts=("study",),
        thumbnail_scene_texts=("sleep",),
        duration_seconds=7200,
        actual_content_type="collection",
    )

    assert result.verdict == "supported"
    assert result.conflicts == ("viewing_scene",)


@pytest.mark.parametrize(
    ("primary_verdicts", "expected_action", "expected_reason"),
    [
        (("refuted", "refuted"), "verify_secondaries", None),
        (("supported", "refuted"), "skip_secondaries", "primary hypothesis supported"),
        (("unverified", "refuted"), "skip_secondaries", "primary hypothesis unverified"),
    ],
)
def test_secondary_transition_is_executable(
    primary_verdicts: tuple[str, ...],
    expected_action: str,
    expected_reason: str | None,
) -> None:
    verification = _load_module()

    result = verification.decide_secondary_transition(primary_verdicts)

    assert result.action == expected_action
    assert result.reason == expected_reason


@pytest.mark.parametrize(
    ("intro_sec", "peak_sec", "expected"),
    [
        (20.0, 20.0, "refuted"),
        (31.0, 20.0, "unverified"),
        (31.0, 31.0, "supported"),
    ],
)
def test_content_verdict_is_executable(intro_sec: float, peak_sec: float, expected: str) -> None:
    verification = _load_module()

    result = verification.evaluate_content_metrics(
        intro_sec=intro_sec,
        peak_sec=peak_sec,
        scene_count=1,
        avg_cut_sec=1.0,
        competitor_avg_cut_median=1.0,
    )

    assert result.verdict == expected


def test_content_cli_accepts_video_analyze_timestamp_schema() -> None:
    result = _run_cli(
        "content-signals",
        {
            "intro_sec": 20,
            "peak_sec": "1:30",
            "scene_count": 2,
            "avg_cut_sec": 6.5,
            "competitor_avg_cut_median": 4.0,
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] == "supported"


@pytest.mark.parametrize("peak", ["1:60", "not-a-timestamp", -1, True])
def test_content_cli_rejects_invalid_peak_timestamps(peak: object) -> None:
    result = _run_cli(
        "content-signals",
        {
            "intro_sec": 20,
            "peak_sec": peak,
            "scene_count": 2,
            "avg_cut_sec": 6.5,
            "competitor_avg_cut_median": 4.0,
        },
    )

    assert result.returncode == 2
    assert "peak_sec" in result.stderr


@pytest.mark.parametrize(
    ("ab_evidence", "target_score", "competitor_median", "expected"),
    [
        ("challenger_winner", 2.0, 3.0, "supported"),
        ("current_winner", 3.0, 3.0, "refuted"),
        ("challenger_winner", 3.0, 3.0, "unverified"),
        ("none", 3.0, 3.5, "unverified"),
    ],
)
def test_thumbnail_verdict_is_executable(
    ab_evidence: str,
    target_score: float,
    competitor_median: float,
    expected: str,
) -> None:
    verification = _load_module()

    result = verification.evaluate_thumbnail(
        ab_evidence=ab_evidence,
        target_score=target_score,
        competitor_median=competitor_median,
    )

    assert result.verdict == expected


def test_thumbnail_history_schema_maps_winner_to_current_or_challenger() -> None:
    verification = _load_module()
    candidates = {"A": "10-assets/thumbnail.jpg", "B": "10-assets/thumbnail-v2.jpg"}

    assert (
        verification.normalize_ab_evidence(status="winner", result_candidate_id="A", candidate_files=candidates)
        == "current_winner"
    )
    assert (
        verification.normalize_ab_evidence(status="winner", result_candidate_id="B", candidate_files=candidates)
        == "challenger_winner"
    )


def test_thumbnail_feature_scoring_is_executable() -> None:
    verification = _load_module()
    competitors = (
        {"brightness": 20.0, "contrast": 10.0, "saturation": 20.0, "colorfulness": 10.0},
        {"brightness": 40.0, "contrast": 20.0, "saturation": 40.0, "colorfulness": 20.0},
        {"brightness": 60.0, "contrast": 30.0, "saturation": 60.0, "colorfulness": 30.0},
    )

    assert verification.score_thumbnail_features(
        target={"brightness": 40.0, "contrast": 5.0, "saturation": 40.0, "colorfulness": 5.0},
        competitors=competitors,
    ) == (2.0, 2.0)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (lambda module: module.evaluate_target_scene(matched_artifacts=1, artifact_count=3), "supported"),
        (
            lambda module: module.evaluate_differentiation(
                same_genre_scene_count=5, subject_terms=(), competitor_count=10
            ),
            "supported",
        ),
        (lambda module: module.evaluate_signature_alignment(False), "supported"),
        (
            lambda module: module.evaluate_seo(
                target_search_share=0.2,
                baseline_search_share=1.0,
                impressions_low=0.5,
                overlap_count=0,
                competitor_count=10,
            ),
            "supported",
        ),
        (
            lambda module: module.evaluate_engagement(
                comment_ratio=0.2,
                comment_ratio_median=1.0,
                views=20,
                views_median=100,
                impressions_low=0.5,
                comparable_video_count=3,
            ),
            "supported",
        ),
        (
            lambda module: module.evaluate_publish_time(
                target_slot_ratio=0.6,
                best_other_slot_ratio=1.0,
                moderate=0.7,
                mild=0.9,
                target_slot_count=3,
                other_slot_count=3,
            ),
            "supported",
        ),
        (
            lambda module: module.evaluate_playlist_membership(playlist_count=0, retrieval_complete=True),
            "supported",
        ),
        (
            lambda module: module.evaluate_marketability(
                theme_ratios=(0.5, 0.6, 0.7),
                competitor_theme_ratio=0.8,
                mild=0.9,
                own_theme_count=3,
                competitor_theme_count=3,
            ),
            "supported",
        ),
        (
            lambda module: module.evaluate_competition(
                same_genre_scene_count=5,
                competitor_count=10,
                matching_views_ratio=1.0,
                mild=0.9,
            ),
            "supported",
        ),
    ],
)
def test_remaining_hypothesis_verdicts_are_executable(result, expected: str) -> None:
    verification = _load_module()

    assert result(verification).verdict == expected


@pytest.mark.parametrize(
    ("competitor_count", "same_genre_scene_count", "expected"),
    [
        (2, 2, "unverified"),
        (3, 3, "supported"),
        (9, 5, "supported"),
        (10, 4, "refuted"),
    ],
)
def test_competition_uses_all_available_competitors_from_three_to_ten(
    competitor_count: int,
    same_genre_scene_count: int,
    expected: str,
) -> None:
    verification = _load_module()

    result = verification.evaluate_competition(
        same_genre_scene_count=same_genre_scene_count,
        competitor_count=competitor_count,
        matching_views_ratio=1.0,
        mild=0.9,
    )

    assert result.verdict == expected


def test_cli_exposes_term_classification_and_secondary_transition() -> None:
    term_result = _run_cli(
        "term-classification",
        {
            "title": "Rain Jazz for Study",
            "genre_vocabulary": ["jazz"],
            "scene_vocabulary": ["study"],
            "competitor_titles": ["Study Jazz", "Rain Jazz"],
        },
    )
    transition_result = _run_cli("secondary-transition", {"primary_verdicts": ["refuted", "refuted"]})

    assert term_result.returncode == 0, term_result.stderr
    assert json.loads(term_result.stdout)["genre_terms"] == ["jazz"]
    assert transition_result.returncode == 0, transition_result.stderr
    assert json.loads(transition_result.stdout)["action"] == "verify_secondaries"


def test_cli_exposes_thumbnail_operation_with_real_images(tmp_path: Path) -> None:
    paths = []
    for index, color in enumerate(((20, 20, 20), (50, 80, 100), (100, 50, 80), (180, 180, 180))):
        path = tmp_path / f"thumbnail-{index}.png"
        Image.new("RGB", (32, 32), color).save(path)
        paths.append(path)

    result = _run_cli(
        "thumbnail",
        {
            "status": "performed_same",
            "result_candidate_id": None,
            "candidate_files": {"A": "10-assets/thumbnail.jpg"},
            "target_path": str(paths[0]),
            "competitor_paths": [str(path) for path in paths[1:]],
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] in {"supported", "refuted", "unverified"}


@pytest.mark.parametrize(
    "payload",
    [
        {"hypothesis": "target-mismatch", "matched_artifacts": 1, "artifact_count": 3},
        {
            "hypothesis": "differentiation",
            "same_genre_scene_count": 5,
            "subject_terms": [],
            "competitor_count": 5,
        },
        {"hypothesis": "thumbnail-content-alignment", "signature_present": False},
        {
            "hypothesis": "seo",
            "target_search_share": 0.2,
            "baseline_search_share": 1.0,
            "impressions_low": 0.5,
            "overlap_count": 0,
            "competitor_count": 5,
        },
        {
            "hypothesis": "engagement",
            "comment_ratio": 0.2,
            "comment_ratio_median": 1.0,
            "views": 20,
            "views_median": 100,
            "impressions_low": 0.5,
            "comparable_video_count": 3,
        },
        {
            "hypothesis": "publish-time",
            "target_slot_ratio": 0.6,
            "best_other_slot_ratio": 1.0,
            "moderate": 0.7,
            "mild": 0.9,
            "target_slot_count": 3,
            "other_slot_count": 3,
        },
        {"hypothesis": "playlist", "playlist_count": 0, "retrieval_complete": True},
        {
            "hypothesis": "marketability",
            "theme_ratios": [0.5, 0.6, 0.7],
            "competitor_theme_ratio": 0.8,
            "mild": 0.9,
            "own_theme_count": 3,
            "competitor_theme_count": 3,
        },
        {
            "hypothesis": "competition",
            "same_genre_scene_count": 5,
            "competitor_count": 5,
            "matching_views_ratio": 1.0,
            "mild": 0.9,
        },
    ],
    ids=lambda payload: str(payload["hypothesis"]),
)
def test_cli_exposes_every_hypothesis(payload: dict[str, object]) -> None:
    result = _run_cli("hypothesis", payload)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] in {"supported", "refuted", "unverified"}


def test_cli_exposes_title_verdict_as_json() -> None:
    payload = {
        "title": "Rain Rock for Study - 2 Hours",
        "genre_vocabulary": ["jazz", "rock"],
        "scene_vocabulary": ["study", "sleep"],
        "actual_genre_texts": ["rain jazz"],
        "actual_scene_texts": ["study"],
        "thumbnail_scene_texts": ["study desk"],
        "duration_seconds": 7200,
        "actual_content_type": "collection",
    }

    result = _run_cli("title-alignment", payload)

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "verdict": "supported",
        "conflicts": ["genre_mood"],
        "reason": None,
    }
