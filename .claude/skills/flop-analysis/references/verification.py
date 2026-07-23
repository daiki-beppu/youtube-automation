#!/usr/bin/env python3
"""Deterministic verdict helpers for the flop-analysis orchestration."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from statistics import median, quantiles
from typing import NamedTuple

VERDICTS = frozenset({"supported", "refuted", "unverified"})
_EXCLUDED_TOKENS = frozenset(
    {
        "mix",
        "playlist",
        "collection",
        "single",
        "bgm",
        "music",
        "hour",
        "hours",
        "minute",
        "minutes",
        "分",
        "時間",
    }
)
_SUBJECT_STOPWORDS = frozenset({"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "the", "to", "with"})
_DURATION_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>hours?|minutes?|時間|分)",
    flags=re.IGNORECASE,
)


class VerdictResult(NamedTuple):
    verdict: str
    reason: str | None = None


class TitleVerdictResult(NamedTuple):
    verdict: str
    conflicts: tuple[str, ...]
    reason: str | None = None


class TransitionResult(NamedTuple):
    action: str
    reason: str | None = None


class TermResult(NamedTuple):
    genre_terms: tuple[str, ...]
    scene_terms: tuple[str, ...]
    subject_terms: tuple[str, ...]
    content_terms: tuple[str, ...]
    frequent_competitor_terms: tuple[str, ...]


def tokenize(value: str) -> tuple[str, ...]:
    """Normalize text and return semantic tokens in input order."""
    normalized = unicodedata.normalize("NFKC", value).lower()
    pieces: list[str] = []
    current: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if character.isspace() or category[0] in {"P", "S"}:
            if current:
                pieces.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        pieces.append("".join(current))
    return tuple(token for token in pieces if token and not token.isdecimal() and token not in _EXCLUDED_TOKENS)


def _token_set(values: Sequence[str]) -> frozenset[str]:
    return frozenset(token for value in values for token in tokenize(value))


def classify_terms(
    *,
    title: str,
    genre_vocabulary: Sequence[str],
    scene_vocabulary: Sequence[str],
    competitor_titles: Sequence[str] = (),
) -> TermResult:
    """Classify title promises and compute competitor document frequency."""
    title_terms = frozenset(tokenize(title))
    genre_terms = title_terms & _token_set(genre_vocabulary)
    scene_terms = title_terms & _token_set(scene_vocabulary)
    subject_terms = title_terms - genre_terms - scene_terms - _SUBJECT_STOPWORDS
    frequencies = Counter(token for competitor_title in competitor_titles for token in set(tokenize(competitor_title)))
    frequent_terms = tuple(token for token, _ in sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:10])
    return TermResult(
        tuple(sorted(genre_terms)),
        tuple(sorted(scene_terms)),
        tuple(sorted(subject_terms)),
        tuple(sorted(title_terms)),
        frequent_terms,
    )


def _duration_promises(title: str) -> tuple[float, ...]:
    normalized = unicodedata.normalize("NFKC", title).lower()
    durations: list[float] = []
    for match in _DURATION_PATTERN.finditer(normalized):
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        multiplier = 3600 if unit in {"hour", "hours", "時間"} else 60
        durations.append(value * multiplier)
    return tuple(durations)


def _raw_tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return frozenset(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def evaluate_title_alignment(
    *,
    title: str,
    genre_vocabulary: Sequence[str],
    scene_vocabulary: Sequence[str],
    actual_genre_texts: Sequence[str],
    actual_scene_texts: Sequence[str],
    thumbnail_scene_texts: Sequence[str],
    duration_seconds: float,
    actual_content_type: str,
) -> TitleVerdictResult:
    """Classify title promises, then compare them with the actual content."""
    required = {
        "title": title,
        "genre_vocabulary": genre_vocabulary,
        "scene_vocabulary": scene_vocabulary,
        "actual_genre_texts": actual_genre_texts,
        "actual_scene_texts": actual_scene_texts,
        "thumbnail_scene_texts": thumbnail_scene_texts,
        "duration_seconds": duration_seconds,
        "actual_content_type": actual_content_type,
    }
    missing = tuple(name for name, value in required.items() if not value)
    if missing:
        return TitleVerdictResult(
            "unverified",
            (),
            f"missing required inputs: {', '.join(missing)}",
        )

    classified = classify_terms(
        title=title,
        genre_vocabulary=genre_vocabulary,
        scene_vocabulary=scene_vocabulary,
    )
    promised_genres = frozenset(classified.genre_terms)
    promised_scenes = frozenset(classified.scene_terms)
    actual_genres = _token_set(actual_genre_texts)
    actual_scenes = _token_set(actual_scene_texts)
    thumbnail_scenes = _token_set(thumbnail_scene_texts)
    conflicts: list[str] = []
    if promised_genres and not promised_genres <= actual_genres:
        conflicts.append("genre_mood")
    if promised_scenes and (not promised_scenes <= actual_scenes or not promised_scenes <= thumbnail_scenes):
        conflicts.append("viewing_scene")

    durations = _duration_promises(title)
    if any(abs(promised - duration_seconds) / duration_seconds > 0.05 for promised in durations):
        conflicts.append("duration_format")
    normalized_title = _raw_tokens(title)
    content_type = actual_content_type.lower()
    if ({"single", "collection"} & normalized_title) - {content_type}:
        conflicts.append("duration_format")

    if conflicts:
        return TitleVerdictResult("supported", tuple(conflicts))
    return TitleVerdictResult("refuted", ())


def decide_secondary_transition(primary_verdicts: Sequence[str]) -> TransitionResult:
    """Choose the secondary-hypothesis transition after all primaries finish."""
    if not primary_verdicts:
        raise ValueError("primary_verdicts must not be empty")
    invalid = set(primary_verdicts) - VERDICTS
    if invalid:
        raise ValueError(f"invalid verdicts: {sorted(invalid)}")
    if "supported" in primary_verdicts:
        return TransitionResult("skip_secondaries", "primary hypothesis supported")
    if "unverified" in primary_verdicts:
        return TransitionResult("skip_secondaries", "primary hypothesis unverified")
    return TransitionResult("verify_secondaries")


def evaluate_content_metrics(
    *,
    intro_sec: float,
    peak_sec: float,
    scene_count: int,
    avg_cut_sec: float,
    competitor_avg_cut_median: float,
) -> VerdictResult:
    """Apply the fixed four-signal contract for weak-content verdicts."""
    signals = (
        intro_sec > 30,
        peak_sec > 30,
        scene_count == 0,
        avg_cut_sec > competitor_avg_cut_median * 1.5,
    )
    count = sum(signals)
    if count == 0:
        return VerdictResult("refuted")
    if count == 1:
        return VerdictResult("unverified", "a single signal cannot isolate the cause")
    return VerdictResult("supported")


def evaluate_thumbnail(
    *,
    ab_evidence: str,
    target_score: float,
    competitor_median: float,
) -> VerdictResult:
    """Combine A/B evidence with the deterministic four-feature score."""
    if ab_evidence not in {
        "challenger_winner",
        "current_winner",
        "performed_same",
        "inconclusive",
        "none",
    }:
        return VerdictResult("unverified", "unknown A/B evidence")
    visual_support = target_score <= 2 and competitor_median >= 3
    visual_refute = target_score >= competitor_median
    ab_support = ab_evidence == "challenger_winner"
    ab_refute = ab_evidence in {"current_winner", "performed_same"}
    if (ab_support and visual_refute) or (ab_refute and visual_support):
        return VerdictResult("unverified", "A/B and feature evidence conflict")
    if visual_support and not ab_refute:
        return VerdictResult("supported")
    if visual_refute and not ab_support:
        return VerdictResult("refuted")
    return VerdictResult("unverified", "evidence is outside support/refutation boundaries")


def normalize_ab_evidence(
    *,
    status: str,
    result_candidate_id: str | None,
    candidate_files: dict[str, str],
) -> str:
    """Map thumbnail-test history fields to the thumbnail verdict vocabulary."""
    if status == "performed_same":
        return "performed_same"
    if status in {"inconclusive", "none"}:
        return status
    if status != "winner" or result_candidate_id not in candidate_files:
        raise ValueError("invalid thumbnail-test result")
    winner = candidate_files[result_candidate_id].rsplit("/", 1)[-1]
    return "current_winner" if winner in {"thumbnail.jpg", "thumbnail.png"} else "challenger_winner"


def score_thumbnail_features(
    *,
    target: dict[str, float],
    competitors: Sequence[dict[str, float]],
) -> tuple[float, float]:
    """Return target score and competitor score median for the four fixed features."""
    features = ("brightness", "contrast", "saturation", "colorfulness")
    if len(competitors) < 3 or any(feature not in target for feature in features):
        raise ValueError("target and at least three competitors with four features are required")
    if any(feature not in item for item in competitors for feature in features):
        raise ValueError("target and at least three competitors with four features are required")
    values = {feature: [item[feature] for item in competitors] for feature in features}
    brightness_q1, _, brightness_q3 = quantiles(values["brightness"], n=4, method="inclusive")
    saturation_q1, _, saturation_q3 = quantiles(values["saturation"], n=4, method="inclusive")
    contrast_median = median(values["contrast"])
    colorfulness_median = median(values["colorfulness"])

    def score(item: dict[str, float]) -> int:
        return sum(
            (
                brightness_q1 <= item["brightness"] <= brightness_q3,
                item["contrast"] >= contrast_median,
                saturation_q1 <= item["saturation"] <= saturation_q3,
                item["colorfulness"] >= colorfulness_median,
            )
        )

    return float(score(target)), float(median(score(item) for item in competitors))


def evaluate_target_scene(*, matched_artifacts: int, artifact_count: int) -> VerdictResult:
    if artifact_count != 3:
        return VerdictResult("unverified", "three audience artifacts are required")
    return VerdictResult("refuted" if matched_artifacts >= 2 else "supported")


def evaluate_differentiation(
    *, same_genre_scene_count: int, subject_terms: Sequence[str], competitor_count: int
) -> VerdictResult:
    if competitor_count < 3:
        return VerdictResult("unverified", "at least three competitors are required")
    if same_genre_scene_count >= 5 and not subject_terms:
        return VerdictResult("supported")
    return VerdictResult("refuted")


def evaluate_signature_alignment(signature_present: bool) -> VerdictResult:
    return VerdictResult("refuted" if signature_present else "supported")


def evaluate_seo(
    *,
    target_search_share: float,
    baseline_search_share: float,
    impressions_low: float,
    overlap_count: int,
    competitor_count: int,
) -> VerdictResult:
    if competitor_count < 3:
        return VerdictResult("unverified", "at least three competitors are required")
    supported = target_search_share < baseline_search_share * impressions_low and overlap_count == 0
    return VerdictResult("supported" if supported else "refuted")


def evaluate_engagement(
    *,
    comment_ratio: float,
    comment_ratio_median: float,
    views: float,
    views_median: float,
    impressions_low: float,
    comparable_video_count: int,
) -> VerdictResult:
    if comparable_video_count < 3:
        return VerdictResult("unverified", "at least three comparable videos are required")
    supported = comment_ratio < comment_ratio_median * impressions_low and views < views_median * impressions_low
    return VerdictResult("supported" if supported else "refuted")


def evaluate_publish_time(
    *,
    target_slot_ratio: float,
    best_other_slot_ratio: float,
    moderate: float,
    mild: float,
    target_slot_count: int,
    other_slot_count: int,
) -> VerdictResult:
    if target_slot_count < 3 or other_slot_count < 3:
        return VerdictResult("unverified", "each compared slot requires three videos")
    supported = target_slot_ratio < moderate and best_other_slot_ratio >= mild
    return VerdictResult("supported" if supported else "refuted")


def evaluate_playlist_membership(*, playlist_count: int, retrieval_complete: bool) -> VerdictResult:
    if not retrieval_complete:
        return VerdictResult("unverified", "playlist retrieval is incomplete")
    return VerdictResult("supported" if playlist_count == 0 else "refuted")


def evaluate_marketability(
    *,
    theme_ratios: Sequence[float],
    competitor_theme_ratio: float,
    mild: float,
    own_theme_count: int,
    competitor_theme_count: int,
) -> VerdictResult:
    if len(theme_ratios) != 3 or own_theme_count < 3 or competitor_theme_count < 3:
        return VerdictResult("unverified", "day 0, 3, 6 and three videos per comparison are required")
    supported = all(value < mild for value in theme_ratios) and competitor_theme_ratio < mild
    return VerdictResult("supported" if supported else "refuted")


def evaluate_competition(
    *, same_genre_scene_count: int, competitor_count: int, matching_views_ratio: float, mild: float
) -> VerdictResult:
    if competitor_count < 3:
        return VerdictResult("unverified", "at least three competitors are required")
    if not 0 <= same_genre_scene_count <= competitor_count:
        return VerdictResult("unverified", "same_genre_scene_count must not exceed competitor_count")
    required_match_count = min(5, competitor_count)
    supported = same_genre_scene_count >= required_match_count and matching_views_ratio >= mild
    return VerdictResult("supported" if supported else "refuted")


def _string_sequence(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a JSON array of strings")
    return tuple(value)


def _number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _timestamp_seconds(payload: dict[str, object], key: str) -> float:
    """Accept video-analyze timestamp strings as well as numeric seconds."""
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be seconds or an M:SS/H:MM:SS timestamp")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"{key} must not be negative")
        return float(value)
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        raise ValueError(f"{key} must be seconds or an M:SS/H:MM:SS timestamp")
    parts = tuple(int(part) for part in value.split(":"))
    if any(part >= 60 for part in parts[1:]):
        raise ValueError(f"{key} timestamp minutes and seconds must be below 60")
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return float(seconds)


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _hypothesis_operation(payload: dict[str, object]) -> VerdictResult:
    hypothesis = payload.get("hypothesis")
    if hypothesis == "target-mismatch":
        return evaluate_target_scene(
            matched_artifacts=_integer(payload, "matched_artifacts"),
            artifact_count=_integer(payload, "artifact_count"),
        )
    if hypothesis == "differentiation":
        return evaluate_differentiation(
            same_genre_scene_count=_integer(payload, "same_genre_scene_count"),
            subject_terms=_string_sequence(payload, "subject_terms"),
            competitor_count=_integer(payload, "competitor_count"),
        )
    if hypothesis == "thumbnail-content-alignment":
        value = payload.get("signature_present")
        if not isinstance(value, bool):
            raise ValueError("signature_present must be a boolean")
        return evaluate_signature_alignment(value)
    if hypothesis == "seo":
        return evaluate_seo(
            target_search_share=_number(payload, "target_search_share"),
            baseline_search_share=_number(payload, "baseline_search_share"),
            impressions_low=_number(payload, "impressions_low"),
            overlap_count=_integer(payload, "overlap_count"),
            competitor_count=_integer(payload, "competitor_count"),
        )
    if hypothesis == "engagement":
        return evaluate_engagement(
            comment_ratio=_number(payload, "comment_ratio"),
            comment_ratio_median=_number(payload, "comment_ratio_median"),
            views=_number(payload, "views"),
            views_median=_number(payload, "views_median"),
            impressions_low=_number(payload, "impressions_low"),
            comparable_video_count=_integer(payload, "comparable_video_count"),
        )
    if hypothesis == "publish-time":
        return evaluate_publish_time(
            target_slot_ratio=_number(payload, "target_slot_ratio"),
            best_other_slot_ratio=_number(payload, "best_other_slot_ratio"),
            moderate=_number(payload, "moderate"),
            mild=_number(payload, "mild"),
            target_slot_count=_integer(payload, "target_slot_count"),
            other_slot_count=_integer(payload, "other_slot_count"),
        )
    if hypothesis == "playlist":
        retrieval_complete = payload.get("retrieval_complete")
        if not isinstance(retrieval_complete, bool):
            raise ValueError("retrieval_complete must be a boolean")
        return evaluate_playlist_membership(
            playlist_count=_integer(payload, "playlist_count"),
            retrieval_complete=retrieval_complete,
        )
    if hypothesis == "marketability":
        ratios = payload.get("theme_ratios")
        if not isinstance(ratios, list) or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) for value in ratios
        ):
            raise ValueError("theme_ratios must be a JSON array of numbers")
        return evaluate_marketability(
            theme_ratios=tuple(float(value) for value in ratios),
            competitor_theme_ratio=_number(payload, "competitor_theme_ratio"),
            mild=_number(payload, "mild"),
            own_theme_count=_integer(payload, "own_theme_count"),
            competitor_theme_count=_integer(payload, "competitor_theme_count"),
        )
    if hypothesis == "competition":
        return evaluate_competition(
            same_genre_scene_count=_integer(payload, "same_genre_scene_count"),
            competitor_count=_integer(payload, "competitor_count"),
            matching_views_ratio=_number(payload, "matching_views_ratio"),
            mild=_number(payload, "mild"),
        )
    raise ValueError("unknown hypothesis")


def _run_operation(operation: str, payload: dict[str, object]) -> tuple[object, ...]:
    if operation == "term-classification":
        title = payload.get("title")
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        return classify_terms(
            title=title,
            genre_vocabulary=_string_sequence(payload, "genre_vocabulary"),
            scene_vocabulary=_string_sequence(payload, "scene_vocabulary"),
            competitor_titles=_string_sequence(payload, "competitor_titles"),
        )
    if operation == "title-alignment":
        title = payload.get("title")
        duration = payload.get("duration_seconds")
        content_type = payload.get("actual_content_type")
        if not isinstance(title, str) or not isinstance(duration, (int, float)):
            raise ValueError("title and duration_seconds are required")
        if not isinstance(content_type, str):
            raise ValueError("actual_content_type must be a string")
        return evaluate_title_alignment(
            title=title,
            genre_vocabulary=_string_sequence(payload, "genre_vocabulary"),
            scene_vocabulary=_string_sequence(payload, "scene_vocabulary"),
            actual_genre_texts=_string_sequence(payload, "actual_genre_texts"),
            actual_scene_texts=_string_sequence(payload, "actual_scene_texts"),
            thumbnail_scene_texts=_string_sequence(payload, "thumbnail_scene_texts"),
            duration_seconds=float(duration),
            actual_content_type=content_type,
        )
    if operation == "secondary-transition":
        return decide_secondary_transition(_string_sequence(payload, "primary_verdicts"))
    if operation == "content-signals":
        return evaluate_content_metrics(
            intro_sec=_number(payload, "intro_sec"),
            peak_sec=_timestamp_seconds(payload, "peak_sec"),
            scene_count=_integer(payload, "scene_count"),
            avg_cut_sec=_number(payload, "avg_cut_sec"),
            competitor_avg_cut_median=_number(payload, "competitor_avg_cut_median"),
        )
    if operation == "thumbnail":
        status = payload.get("status")
        result_candidate_id = payload.get("result_candidate_id")
        candidate_files = payload.get("candidate_files")
        if not isinstance(status, str):
            raise ValueError("status must be a string")
        if result_candidate_id is not None and not isinstance(result_candidate_id, str):
            raise ValueError("result_candidate_id must be a string or null")
        if not isinstance(candidate_files, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in candidate_files.items()
        ):
            raise ValueError("candidate_files must be a JSON object of strings")
        evidence = normalize_ab_evidence(
            status=status,
            result_candidate_id=result_candidate_id,
            candidate_files=candidate_files,
        )
        target_path = payload.get("target_path")
        competitor_paths = _string_sequence(payload, "competitor_paths")
        if not isinstance(target_path, str):
            raise ValueError("target_path must be a string")
        from youtube_automation.domains.thumbnail.features import extract_features_from_path

        target_features = extract_features_from_path(Path(target_path))
        competitor_features = tuple(extract_features_from_path(Path(value)) for value in competitor_paths)
        target_score, competitor_median = score_thumbnail_features(
            target=target_features,
            competitors=competitor_features,
        )
        return evaluate_thumbnail(
            ab_evidence=evidence,
            target_score=target_score,
            competitor_median=competitor_median,
        )
    if operation == "hypothesis":
        return _hypothesis_operation(payload)
    raise ValueError(f"unknown operation: {operation}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        required=True,
        choices=(
            "term-classification",
            "title-alignment",
            "secondary-transition",
            "content-signals",
            "thumbnail",
            "hypothesis",
        ),
    )
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        parser.error("stdin must contain a JSON object")
    try:
        result = _run_operation(args.operation, payload)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result._asdict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
