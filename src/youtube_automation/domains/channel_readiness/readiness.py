"""Channel setup and TTP readiness policy implementation."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.analytics.benchmark import (
    TTP_VIDEO_ANALYZE_TOP_N,
    load_benchmark_videos,
    select_top_vod_benchmark_videos,
)
from youtube_automation.domains.thumbnail.references import resolve_configured_benchmark_references
from youtube_automation.domains.uploads.preflight import (
    check_descriptions_md_parseability,
    check_suno_genre_line_char_limit,
    check_thumbnail_skill_config,
)

UNSUPPORTED_VIDEO_ANALYZE_MODELS = {"gemini-3.1-flash-image-preview"}
UNSUPPORTED_THUMBNAIL_MODELS = {
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
}
_PERSONA_SECTIONS = (
    "第一ペルソナ",
    "コメント由来の語彙",
    "感情トリガー",
    "利用シーン",
    "検索キーワード",
    "避けるべき訴求",
    "自チャンネルへの示唆",
    "タイトル・タグ・概要欄・サムネ・音楽ムードへの影響",
    "候補の棄却・統合メモ",
)
_STRUCTURED_PERSONA_SECTIONS = frozenset(
    {
        "コメント由来の語彙",
        "感情トリガー",
        "利用シーン",
        "検索キーワード",
        "避けるべき訴求",
        "自チャンネルへの示唆",
    }
)
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_MARKDOWN_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_MARKDOWN_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])[ \t]+")
_PERSONA_SOURCE_ANNOTATION = re.compile(r"出典:\s*(?:推測|[A-Za-z0-9_.-]+\.(?:md|json))(?=[）)\]}、,;；\s]*$)")


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    message: str
    next_action: dict[str, object] | None = None


@dataclass(frozen=True)
class _MappingRead:
    data: dict[str, object]
    error: str | None = None


@dataclass(frozen=True)
class _BenchmarkChannelsRead:
    channels: list[dict[str, object]]
    errors: list[str]


def _matching_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def evaluate_ttp_wf_new_readiness(channel_dir: Path) -> ReadinessResult:
    persona_definition = channel_dir / "docs" / "channel" / "personas" / "persona-definition.md"
    missing_persona = _missing_persona_readiness_items(persona_definition)
    missing_persona_suffix = ("; " + "; ".join(missing_persona)) if missing_persona else ""

    analytics_path = channel_dir / "config" / "channel" / "analytics.json"
    if not analytics_path.is_file():
        return ReadinessResult(
            status="warn",
            message=(
                "config/channel/analytics.json 未生成。/wf-new 接続前に承認済み TTP 対象の保存が必要"
                + missing_persona_suffix
            ),
            next_action={
                "kind": "human",
                "instructions": _with_persona_recovery(
                    "/setup --channel Step 4 で config を生成し、Step 5 以降で承認済み TTP 対象を "
                    "config/channel/analytics.json::benchmark.channels に保存してください",
                    missing_persona,
                ),
            },
        )

    analytics_read = _read_json_mapping(analytics_path)
    if analytics_read.error:
        return ReadinessResult(
            status="warn",
            message="TTP 完了条件が未充足: " + analytics_read.error + missing_persona_suffix,
            next_action={
                "kind": "human",
                "instructions": _with_persona_recovery(
                    "config/channel/analytics.json を修正してから yt-doctor を再実行してください",
                    missing_persona,
                ),
            },
        )

    analytics = analytics_read.data
    channels_read = _benchmark_channels(analytics)
    channels = channels_read.channels
    if not channels:
        return ReadinessResult(
            status="warn",
            message=(
                "承認済み TTP 対象が 0 件。/setup --channel は /wf-new 接続前に TTP 対象承認が必要"
                + missing_persona_suffix
            ),
            next_action={
                "kind": "human",
                "instructions": _with_persona_recovery(
                    "/setup --channel Step 1/5 に戻り、TTP 対象を確認して "
                    "config/channel/analytics.json::benchmark.channels に承認済み対象を保存してください",
                    missing_persona,
                ),
            },
        )

    missing, approved_exceptions = _missing_ttp_readiness_items(channel_dir, channels)
    missing.extend(missing_persona)
    missing.extend(channels_read.errors)
    benchmark_missing, benchmark_notes = _missing_channel_new_benchmark_items(
        channel_dir,
        approved_exceptions,
        channels,
    )
    missing.extend(benchmark_missing)
    # live 配信除外の note は未充足条件ではないため missing に混ぜず、message 末尾に併記する
    note_suffix = ("。" + "; ".join(benchmark_notes)) if benchmark_notes else ""
    if missing:
        return ReadinessResult(
            status="warn",
            message="/setup --channel または /setup --regenerate の TTP 完了条件が未充足: "
            + "; ".join(missing)
            + note_suffix,
            next_action={
                "kind": "human",
                "instructions": _with_persona_recovery(
                    "/setup --channel Step 5-9 または "
                    "/setup --regenerate Step R3.5 の不足項目を解消してください。"
                    "意図的にスキップする場合は docs/channel/ttp-seed-confirmation.md に "
                    "ユーザー承認済み例外として未反映項目を明記し、最後に `uv run yt-doctor --json` で "
                    "`ttp_wf_new_readiness` が ok になることを確認してください",
                    missing_persona,
                ),
            },
        )

    return ReadinessResult(
        status="ok",
        message=(
            "TTP 対象承認・branding snapshot・benchmark docs・thumbnail / music readiness が "
            "/wf-new 接続可能（/setup --regenerate 完了相当）" + note_suffix
        ),
    )


def _missing_persona_readiness_items(path: Path) -> list[str]:
    relative = "docs/channel/personas/persona-definition.md"
    if not path.is_file():
        return [f"{relative} 未作成"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{relative} を読み込めません ({exc})"]

    sections = _persona_markdown_sections(text)
    missing: list[str] = []
    for name in _PERSONA_SECTIONS:
        if name not in sections:
            missing.append(f"{relative} 必須セクション欠落: {name}")
        elif not any(line.strip() for line in sections[name]):
            missing.append(f"{relative} 本文空: {name}")
    if "暫定" in text:
        missing.append(f"{relative} が未最終化（「暫定」表記あり）")
    for name in _PERSONA_SECTIONS:
        if name not in _STRUCTURED_PERSONA_SECTIONS or name not in sections:
            continue
        items = [line for line in sections[name] if _MARKDOWN_LIST_ITEM.match(line)]
        if not items or any(not _PERSONA_SOURCE_ANNOTATION.search(item) for item in items):
            missing.append(f"{relative} 出典注記不足: {name}")
    return missing


def _persona_markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    active_name: str | None = None
    active_level = 0
    fence_marker: str | None = None
    for line in text.splitlines():
        fence = _MARKDOWN_FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_marker is None:
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(fence_marker):
                fence_marker = None
            continue
        if fence_marker is not None:
            continue

        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            name = heading.group(2).strip()
            if active_name is not None and level <= active_level:
                active_name = None
            if name in _PERSONA_SECTIONS:
                sections.setdefault(name, [])
                active_name = name
                active_level = level
            continue
        if active_name is not None:
            sections[active_name].append(line)
    return sections


def _with_persona_recovery(instructions: str, missing_persona: list[str]) -> str:
    if not missing_persona:
        return instructions
    return (
        instructions + "。ペルソナの不足はユーザー承認済み例外にせず、"
        "/channel-strategy --persona で最終 persona-definition.md を更新してください"
    )


def _read_json_mapping(path: Path) -> _MappingRead:
    if not path.exists():
        return _MappingRead({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} が JSON として不正 ({e.msg})")
    except OSError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} を読み込めません ({e})")
    if not isinstance(data, dict):
        return _MappingRead({}, f"{_diagnostic_path(path)} のトップレベルが object ではありません")
    return _MappingRead(data)


def _read_yaml_mapping(path: Path) -> _MappingRead:
    if not path.exists():
        return _MappingRead({})
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} が YAML として不正 ({e})")
    except OSError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} を読み込めません ({e})")
    if not isinstance(data, dict):
        return _MappingRead({}, f"{_diagnostic_path(path)} のトップレベルが object ではありません")
    return _MappingRead(data)


def _skill_config_mapping(channel_dir: Path, skill: str) -> _MappingRead:
    try:
        return _MappingRead(load_skill_config(skill, use_cache=False, channel_dir=channel_dir))
    except ConfigError as exc:
        return _MappingRead({}, str(exc))


def _diagnostic_path(path: Path) -> str:
    return path.as_posix()


def _benchmark_channels(analytics: dict[str, object]) -> _BenchmarkChannelsRead:
    benchmark = analytics.get("benchmark")
    if not isinstance(benchmark, dict):
        return _BenchmarkChannelsRead([], [])
    channels = benchmark.get("channels")
    if not isinstance(channels, list):
        return _BenchmarkChannelsRead([], [])
    valid_channels: list[dict[str, object]] = []
    errors: list[str] = []
    for index, channel in enumerate(channels):
        if isinstance(channel, dict):
            valid_channels.append(channel)
        else:
            errors.append(f"benchmark.channels entry #{index + 1} が object ではありません")
    return _BenchmarkChannelsRead(valid_channels, errors)


def _missing_ttp_readiness_items(channel_dir: Path, channels: list[dict[str, object]]) -> tuple[list[str], set[str]]:
    missing: list[str] = []
    approved_exceptions: set[str] = set()
    seed_text = ""

    channels_without_relationship = [
        _channel_diagnostic_label(index, channel)
        for index, channel in enumerate(channels)
        if _is_placeholder_relationship(str(channel.get("relationship") or ""))
    ]
    if channels_without_relationship:
        missing.append(
            "benchmark.channels の relationship 未設定または placeholder ("
            + ", ".join(channels_without_relationship)
            + ")"
        )

    seed_confirmation = channel_dir / "docs" / "channel" / "ttp-seed-confirmation.md"
    if not seed_confirmation.is_file():
        missing.append("docs/channel/ttp-seed-confirmation.md 未作成")
    else:
        seed_text = seed_confirmation.read_text(encoding="utf-8", errors="replace")
        seed_missing, approved_exceptions = _validate_ttp_seed_confirmation(seed_text, channels)
        missing.extend(seed_missing)
        missing.extend(_missing_duration_ttp_items(seed_text, channels, approved_exceptions))

    missing.extend(_missing_branding_snapshot_items(channel_dir, channels, seed_text))

    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        missing.append(thumbnail_read.error)
    thumbnail_override = _read_yaml_mapping(channel_dir / "config" / "skills" / "thumbnail.yaml").data
    image_generation = thumbnail_override.get("image_generation")
    gemini = image_generation.get("gemini") if isinstance(image_generation, dict) else None
    model = gemini.get("model") if isinstance(gemini, dict) else None
    if isinstance(model, str) and model in UNSUPPORTED_THUMBNAIL_MODELS:
        missing.append(f"thumbnail model が旧/非対応: {model}")
    if "thumbnail" not in approved_exceptions:
        thumbnail_missing = _thumbnail_ttp_reference_missing_reason(channel_dir, thumbnail_read.data)
        if thumbnail_missing:
            missing.append(thumbnail_missing)

    video_analyze_read = _skill_config_mapping(channel_dir, "audit.video")
    if video_analyze_read.error:
        missing.append(video_analyze_read.error)
    model = video_analyze_read.data.get("model")
    if isinstance(model, str) and model in UNSUPPORTED_VIDEO_ANALYZE_MODELS:
        missing.append(f"audit.video model が旧/非対応: {model}")

    youtube_read = _read_json_mapping(channel_dir / "config" / "channel" / "youtube.json")
    if youtube_read.error:
        missing.append(youtube_read.error)
    youtube = youtube_read.data
    if youtube.get("music_engine", "suno") == "suno" and "music" not in approved_exceptions:
        music_readiness = _suno_music_readiness(channel_dir, channels)
        missing.extend(music_readiness.errors)
        if not music_readiness.ready:
            missing.append("Suno genre_line または data/video_analysis の suno_preset 未設定")

    return missing, approved_exceptions


def _missing_channel_new_benchmark_items(
    channel_dir: Path,
    approved_exceptions: set[str],
    channels: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    if not _matching_files(channel_dir / "data", "benchmark_*.json"):
        missing.append("data/benchmark_*.json が無い")
    analysis_missing, notes = _missing_video_analysis_items(channel_dir, _approved_ttp_channel_slugs(channels))
    missing.extend(analysis_missing)
    if not _benchmark_report_files(channel_dir):
        missing.append("docs/benchmarks/*.md が無い")
    if "thumbnail" not in approved_exceptions and not _benchmark_thumbnail_files(channel_dir):
        missing.append("data/thumbnail_compare/benchmark/ に TTP 参照画像が無い")
    return missing, notes


def _missing_video_analysis_items(channel_dir: Path, approved_slugs: list[str]) -> tuple[list[str], list[str]]:
    approved_slug_set = set(approved_slugs)
    if not approved_slug_set:
        return [], []
    benchmark_by_slug, errors = _latest_benchmark_videos_by_slug(channel_dir, approved_slug_set)
    missing = list(errors)
    notes: list[str] = []
    video_analysis_dir = channel_dir / "data" / "video_analysis"
    for slug in approved_slugs:
        slug_dir, slug_error = _video_analysis_slug_dir(channel_dir, video_analysis_dir, slug)
        if slug_error:
            missing.append(slug_error)
            continue
        videos = benchmark_by_slug.get(slug, [])
        top_videos, skipped_live = select_top_vod_benchmark_videos(videos, TTP_VIDEO_ANALYZE_TOP_N)
        excluded_live = len(skipped_live)
        if excluded_live:
            notes.append(
                f"{slug}: live 配信 {excluded_live} 本は Gemini で解析不能のため "
                f"benchmark top {TTP_VIDEO_ANALYZE_TOP_N} の判定から除外（次点 VOD を繰り上げ）"
            )
        if len(videos) < TTP_VIDEO_ANALYZE_TOP_N and not excluded_live:
            missing.append(
                f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} が不足 ({len(top_videos)}/{TTP_VIDEO_ANALYZE_TOP_N})"
            )
        expected_ids = {str(video.get("video_id")) for video in top_videos if video.get("video_id")}
        if len(expected_ids) < len(top_videos):
            missing.append(f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} に video_id 欠落があります")
        if not expected_ids:
            if excluded_live and videos:
                missing.append(f"{slug}: benchmark 上位が live 配信のみで解析可能な VOD がありません")
            else:
                missing.append(f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} に video_id がありません")
            continue
        done_ids, analysis_errors = _verified_video_analysis_ids(
            slug,
            slug_dir or video_analysis_dir / slug,
            expected_ids,
        )
        missing.extend(analysis_errors)
        done = len(done_ids)
        # live 除外が発生した場合のみ母数を実際に解析可能な VOD 数へ縮小する
        # （除外なしで benchmark が N 本未満の従来ケースは分母 N のまま warn を維持）
        required = len(top_videos) if excluded_live else TTP_VIDEO_ANALYZE_TOP_N
        if done == 0:
            missing.append(f"{slug}: video_analysis 未実行 (0/{required})")
        elif done < required:
            missing.append(f"{slug}: video_analysis が一部のみ ({done}/{required})")
    return missing, notes


def _latest_benchmark_videos_by_slug(
    channel_dir: Path,
    approved_slugs: set[str],
) -> tuple[dict[str, list[dict[str, object]]], list[str]]:
    try:
        videos = load_benchmark_videos(channel_dir / "data")
    except (ConfigError, json.JSONDecodeError, OSError, ValueError) as exc:
        return {}, [str(exc)]
    result: dict[str, list[dict[str, object]]] = {}
    for video in videos:
        slug = str(video.get("channel_slug") or "").strip()
        if slug in approved_slugs:
            result.setdefault(slug, []).append(video)
    return result, []


def _verified_video_analysis_ids(slug: str, slug_dir: Path, expected_ids: set[str]) -> tuple[set[str], list[str]]:
    done: set[str] = set()
    errors: list[str] = []
    for video_id in sorted(expected_ids):
        path = slug_dir / f"{video_id}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{slug}: {path.name} 読み込み失敗: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{slug}: {path.name} のトップレベルが object ではありません")
            continue
        payload_video_id = data.get("video_id")
        if payload_video_id is not None and str(payload_video_id) != video_id:
            errors.append(f"{slug}: {path.name} の video_id が期待値と一致しません")
            continue
        done.add(video_id)
    return done, errors


_SEED_CONFIRMATION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source", ("source", "ソース", "url", "handle", "channel id", "チャンネルid")),
    ("seed fetch 要約", ("seed fetch", "seed 要約", "seed preview", "fetch", "取得要約", "収集要約")),
    (
        "承認 / 不採用判断",
        (
            "承認 / 不採用判断",
            "承認判断",
            "不採用判断",
            "判断:",
            "approved:",
            "rejected:",
        ),
    ),
    ("転写したい要素", ("転写したい要素", "転写", "要素:")),
    ("relationship", ("relationship", "関係性")),
    ("未反映項目", ("未反映", "未適用", "none", "なし")),
)


_PLACEHOLDER_RELATIONSHIPS = {"", "seed", "default", "unknown", "none", "n/a", "未設定", "なし"}


def _validate_ttp_seed_confirmation(seed_text: str, channels: list[dict[str, object]]) -> tuple[list[str], set[str]]:
    missing: list[str] = []
    sections = _seed_confirmation_sections(seed_text)

    for index, channel in enumerate(channels):
        label = _channel_diagnostic_label(index, channel)
        identifiers = _channel_seed_identifiers(channel)
        if not identifiers:
            missing.append(f"ttp-seed-confirmation.md 照合用の id / slug が benchmark.channels に未設定 ({label})")
            continue

        candidate_sections = _sections_for_identifiers(sections, identifiers)
        if not candidate_sections:
            missing.append(f"ttp-seed-confirmation.md に承認済み TTP 対象の識別子が未記録 ({label})")
            continue

        candidate_text = "\n".join(candidate_sections)
        for marker_label, markers in _SEED_CONFIRMATION_MARKERS:
            if not _has_seed_confirmation_marker(candidate_text, marker_label, markers):
                missing.append(f"ttp-seed-confirmation.md に {marker_label} が未記録 ({label})")
        if not _has_branding_transfer_policy(candidate_text):
            missing.append(f"ttp-seed-confirmation.md に branding snapshot 参照または転写方針が未記録 ({label})")

        relationship = str(channel.get("relationship") or "").strip()
        if (
            relationship
            and not _is_placeholder_relationship(relationship)
            and relationship.lower() not in candidate_text.lower()
        ):
            missing.append(f"ttp-seed-confirmation.md に承認済み TTP 対象の relationship が未記録 ({label})")

    exception_blocks = _approved_ttp_exception_blocks(seed_text)
    approved_exception_line_numbers = {
        line_number for _, line_numbers in exception_blocks for line_number in line_numbers
    }
    unapproved_skip_lines = [
        line.strip()
        for line_number, line in enumerate(seed_text.splitlines())
        if _line_mentions_ttp_skip(line) and line_number not in approved_exception_line_numbers
    ]
    if unapproved_skip_lines:
        missing.append("ttp-seed-confirmation.md に未承認の TTP 未反映 / スキップ項目あり")

    approved_exceptions, exception_missing = _validate_approved_ttp_exception_blocks(exception_blocks)
    missing.extend(exception_missing)
    return missing, approved_exceptions


def _seed_confirmation_sections(seed_text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in seed_text.splitlines():
        stripped = line.strip()
        starts_new_heading = stripped.startswith("#") and current
        starts_new_list_channel = bool(
            current and re.match(r"^[-*]\s+(?:channel|チャンネル|候補)\b", stripped, re.IGNORECASE)
        )
        if not stripped or starts_new_heading or starts_new_list_channel:
            if current:
                sections.append("\n".join(current))
                current = []
            if not stripped:
                continue
        current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections or [seed_text]


def _sections_for_identifiers(sections: list[str], identifiers: list[str]) -> list[str]:
    return [
        section
        for section in sections
        if any(_section_mentions_identifier(section, identifier) for identifier in identifiers)
    ]


def _section_mentions_identifier(section: str, identifier: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}(?![A-Za-z0-9_-])", re.IGNORECASE)
    identifier_line_markers = ("source", "ソース", "url", "handle", "channel", "チャンネル", "id", "slug")
    return any(
        any(marker in line.lower() for marker in identifier_line_markers) and pattern.search(line)
        for line in section.splitlines()
    )


def _is_placeholder_relationship(relationship: str) -> bool:
    return relationship.strip().lower() in _PLACEHOLDER_RELATIONSHIPS


def _channel_seed_identifiers(channel: dict[str, object]) -> list[str]:
    return [value for value in (str(channel.get("id") or "").strip(), str(channel.get("slug") or "").strip()) if value]


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    return any(marker.lower() in lower_text for marker in markers)


def _has_seed_confirmation_marker(text: str, marker_label: str, markers: tuple[str, ...]) -> bool:
    if _contains_any_marker(text, markers):
        return True
    if marker_label != "承認 / 不採用判断":
        return False

    decision_text = "\n".join(line for line in text.splitlines() if not _line_mentions_approved_exception(line))
    normalized = unicodedata.normalize("NFKC", decision_text).casefold()
    return bool(
        re.search(r"ユーザー承認\s*:\s*承認済み", normalized)
        or re.search(r"ユーザー不採用\s*:\s*(?:不採用|却下)", normalized)
    )


def _has_branding_transfer_policy(text: str) -> bool:
    lower_text = text.lower()
    if "competitor-branding-snapshot.json" in lower_text or "branding snapshot" in lower_text:
        return True
    policy_markers = ("description", "keywords", "localizations")
    transfer_markers = ("転写", "方針", "参照", "構造", "抽出")
    return any(
        any(policy_marker in line.lower() for policy_marker in policy_markers)
        and any(transfer_marker in line for transfer_marker in transfer_markers)
        for line in text.splitlines()
    )


def _line_mentions_ttp_skip(line: str) -> bool:
    lower_line = line.lower()
    if "スキップ" in line or "skip" in lower_line:
        return True
    if "未反映" not in line and "未適用" not in line:
        return False
    return not _line_declares_no_unapplied_items(line)


def _line_declares_no_unapplied_items(line: str) -> bool:
    lower_line = line.lower()
    return ("なし" in line or "none" in lower_line) and "ただし" not in line and "but" not in lower_line


def _line_mentions_approved_exception(line: str) -> bool:
    lower_line = line.lower()
    return "ユーザー承認済み例外" in line or "approved exception" in lower_line


def approved_ttp_exceptions(seed_text: str) -> tuple[set[str], list[str]]:
    return _validate_approved_ttp_exception_blocks(_approved_ttp_exception_blocks(seed_text))


def _approved_ttp_exception_blocks(seed_text: str) -> list[tuple[str, set[int]]]:
    lines = seed_text.splitlines()
    blocks: list[tuple[str, set[int]]] = []
    for line_number, line in enumerate(lines):
        if not _line_mentions_approved_exception(line):
            continue
        heading_match = re.match(r"^\s*(#{1,6})\s+", line)
        if not heading_match:
            blocks.append((line, {line_number}))
            continue

        heading_level = len(heading_match.group(1))
        block_lines = [line]
        block_line_numbers = {line_number}
        for following_number in range(line_number + 1, len(lines)):
            following_line = lines[following_number]
            following_heading = re.match(r"^\s*(#{1,6})\s+", following_line)
            if following_heading and len(following_heading.group(1)) <= heading_level:
                break
            block_lines.append(following_line)
            block_line_numbers.add(following_number)
        blocks.append(("\n".join(block_lines), block_line_numbers))
    return blocks


def _validate_approved_ttp_exception_blocks(
    blocks: list[tuple[str, set[int]]],
) -> tuple[set[str], list[str]]:
    exceptions: set[str] = set()
    missing: list[str] = []
    for block, _ in blocks:
        lower_block = block.lower()
        categories: set[str] = set()
        if "thumbnail" in lower_block or "サムネ" in block:
            categories.add("thumbnail")
        if "music" in lower_block or "suno" in lower_block or "曲構造" in block or "音楽" in block:
            categories.add("music")
        if "duration" in lower_block or "動画尺" in block:
            categories.add("duration")

        if not categories:
            missing.append("ユーザー承認済み例外に対象 category が未記録")
            continue
        if not any(_line_mentions_ttp_skip(line) for line in block.splitlines()):
            missing.append("ユーザー承認済み例外に具体的な未反映 / スキップ内容が未記録")
            continue
        if not _approved_exception_has_reason(block):
            missing.append("ユーザー承認済み例外に進める理由が未記録")
            continue
        if "thumbnail" in categories and "/thumbnail" not in lower_block:
            missing.append("thumbnail のユーザー承認済み例外に後続 /thumbnail が未記録")
            continue
        if "music" in categories and "/music --prompt" not in lower_block:
            missing.append("music のユーザー承認済み例外に後続 /music --prompt が未記録")
            continue
        if "duration" in categories and not any(
            command in lower_block for command in ("/benchmark", "/channel-research --benchmark")
        ):
            missing.append("duration のユーザー承認済み例外に後続 /channel-research --benchmark が未記録")
            continue

        exceptions.update(categories)
    return exceptions, missing


def _missing_duration_ttp_items(
    seed_text: str,
    channels: list[dict[str, object]],
    approved_exceptions: set[str],
) -> list[str]:
    if "duration" in approved_exceptions:
        return []

    missing: list[str] = []
    evidence_lines = _duration_ttp_evidence_lines(seed_text)
    duration_lines = [line for line in evidence_lines if _has_duration_context(line[0])]
    if not any(_has_duration_evidence_label(text) for text, _, _ in duration_lines):
        missing.append("duration TTP 根拠が未記録")
    has_min = any(_has_duration_range_context(text) and _has_min_label(text) for text, _, _ in duration_lines)
    has_max = any(_has_duration_range_context(text) and _has_max_label(text) for text, _, _ in duration_lines)
    if not has_min or not has_max:
        missing.append("duration 推奨 min/max が未記録")
    if not any(_has_duration_approval(text) for text, _, _ in duration_lines):
        missing.append("duration 推奨のユーザー承認結果が未記録")

    duration_channel_lines = [text for text, _, _ in duration_lines if _has_target_channel_label(text)]
    for index, channel in enumerate(channels):
        identifiers = _channel_seed_identifiers(channel)
        if identifiers and not any(
            any(identifier.lower() in line for identifier in identifiers) for line in duration_channel_lines
        ):
            missing.append(
                f"duration TTP 根拠に承認済み channel が未記録 ({_channel_diagnostic_label(index, channel)})"
            )

    selected_count = sum(
        1
        for text, is_list_item, item_text in duration_lines
        if is_list_item and _has_selected_video_label(text) and _has_selected_video_evidence(item_text)
    )
    required_count = TTP_VIDEO_ANALYZE_TOP_N * len(channels)
    if selected_count < required_count:
        missing.append(f"duration selected video の根拠が不足 ({selected_count}/{required_count})")
    return missing


def _duration_ttp_evidence_lines(seed_text: str) -> list[tuple[str, bool, str]]:
    headings: dict[int, str] = {}
    evidence_lines: list[tuple[str, bool, str]] = []
    for raw_line in seed_text.splitlines():
        stripped = raw_line.strip()
        heading_match = re.match(r"^(#{1,6})\s*(.*?)\s*#*$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            headings = {current_level: text for current_level, text in headings.items() if current_level < level}
            headings[level] = heading_match.group(2)
            continue
        if not stripped:
            continue
        list_match = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", stripped)
        content = list_match.group(1) if list_match else stripped
        context = " ".join([*(headings[level] for level in sorted(headings)), content])
        evidence_lines.append(
            (
                _normalize_duration_evidence_text(context),
                list_match is not None,
                _normalize_duration_evidence_text(content),
            )
        )
    return evidence_lines


def _normalize_duration_evidence_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[`*_]", " ", normalized)
    normalized = re.sub(r"[:=|/・,;()\[\]{}]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _has_duration_context(text: str) -> bool:
    return bool(re.search(r"\bduration\b", text)) or "動画尺" in text.replace(" ", "")


def _has_duration_evidence_label(text: str) -> bool:
    return "根拠" in text or bool(re.search(r"\b(?:evidence|source|basis)\b", text))


def _has_target_channel_label(text: str) -> bool:
    return ("対象" in text and ("channel" in text or "チャンネル" in text)) or bool(
        re.search(r"\btarget\s+channels?\b", text)
    )


def _has_selected_video_label(text: str) -> bool:
    compact = text.replace(" ", "")
    return (
        ("選定" in text and "動画" in text)
        or ("上位5本" in compact and "動画" in text)
        or bool(re.search(r"\bselected\s+videos?\b", text))
        or bool(re.search(r"\btop\s*5\b", text) and re.search(r"\bvideos?\b", text))
    )


def _has_selected_video_evidence(item_text: str) -> bool:
    identifier_source = re.sub(r"^(?:duration\s+)?selected\s+video\s*", "", item_text).strip(" :=-")
    identifier_source = re.sub(r"^(?:動画尺\s*)?(?:選定動画|動画)\s*", "", identifier_source).strip(" :=-")
    identifier = re.split(
        r"\s*(?:[|/,;]|\bviews?\s*[:=]?|\b(?:duration|length)\s*[:=]?|再生(?:数|回数)?\s*[:=]?)",
        identifier_source,
        maxsplit=1,
    )[0].strip(" :=-")
    if identifier in {"tbd", "todo", "n/a", "na", "未定", "保留"}:
        return False
    has_identifier = bool(re.search(r"[a-z0-9ぁ-んァ-ヶ一-龠]", identifier))
    has_views = bool(
        re.search(r"\bviews?\s*[:=]?\s*[\d,]+\b", item_text)
        or re.search(r"\b[\d,]+\s+views?\b", item_text)
        or re.search(r"再生(?:数|回数)?\s*[:=]?\s*[\d,]+", item_text)
    )
    has_duration = bool(
        re.search(r"\bpt(?=\d)(?:\d+h)?(?:\d+m)?(?:\d+s)?\b", item_text)
        or re.search(r"\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s|時間|分|秒)\b", item_text)
    )
    return has_identifier and has_views and has_duration


def _has_duration_range_context(text: str) -> bool:
    return "推奨" in text or "範囲" in text or bool(re.search(r"\b(?:recommend(?:ed|ation)?|range|target)\b", text))


def _has_min_label(text: str) -> bool:
    return "最小" in text or "下限" in text or bool(re.search(r"\b(?:min|minimum)\b", text))


def _has_max_label(text: str) -> bool:
    return "最大" in text or "上限" in text or bool(re.search(r"\b(?:max|maximum)\b", text))


def _has_duration_approval(text: str) -> bool:
    compact = text.replace(" ", "")
    user_approved = "ユーザー承認済み" in compact or bool(
        re.search(r"\b(?:approved\s+by\s+(?:the\s+)?user|user\s+approved)\b", text)
    )
    approval_context = (
        "推奨" in text or "承認" in text or bool(re.search(r"\b(?:recommend(?:ed|ation)?|approval)\b", text))
    )
    return user_approved and approval_context


def _approved_exception_has_reason(line: str) -> bool:
    lower_line = line.lower()
    return "ため" in line or "理由" in line or "because" in lower_line or "進める" in line


def _missing_branding_snapshot_items(
    channel_dir: Path,
    channels: list[dict[str, object]],
    seed_text: str,
) -> list[str]:
    branding_read = _read_json_mapping(channel_dir / "docs" / "channel" / "competitor-branding-snapshot.json")
    if branding_read.error:
        return [branding_read.error]

    branding_snapshot = branding_read.data
    snapshot_items = branding_snapshot.get("items")
    if branding_snapshot.get("untrusted_data") is not True:
        return ["docs/channel/competitor-branding-snapshot.json 未作成または空"]
    if not isinstance(snapshot_items, list):
        return ["docs/channel/competitor-branding-snapshot.json の items が list ではありません"]
    if not snapshot_items:
        return ["docs/channel/competitor-branding-snapshot.json 未作成または空"]

    missing: list[str] = []
    if branding_snapshot.get("reference_only") is not True:
        missing.append("competitor-branding-snapshot.json の reference_only が true ではありません")
    if any(not isinstance(item, dict) for item in snapshot_items):
        missing.append("competitor-branding-snapshot.json の items に object ではない要素があります")
    image_references = branding_snapshot.get("channel_image_references")
    if not isinstance(image_references, list):
        missing.append("competitor-branding-snapshot.json の channel_image_references が list ではありません")
        image_references = []
    elif any(not isinstance(item, dict) for item in image_references):
        missing.append("competitor-branding-snapshot.json の channel_image_references に object ではない要素があります")
    approved_ids = _approved_ttp_channel_ids(channels)
    snapshot_by_id = {
        str(item.get("id")): item
        for item in snapshot_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    image_reference_by_id = {
        str(item.get("channel_id")): item
        for item in image_references
        if isinstance(item, dict) and str(item.get("channel_id") or "").strip()
    }

    channels_without_id = [
        _channel_diagnostic_label(index, channel)
        for index, channel in enumerate(channels)
        if not str(channel.get("id") or "").strip()
    ]
    if channels_without_id:
        missing.append(f"benchmark.channels の id 未設定 ({', '.join(channels_without_id)})")

    missing_ids = [channel_id for channel_id in approved_ids if channel_id not in snapshot_by_id]
    if missing_ids:
        missing.append(
            "competitor-branding-snapshot.json に承認済み TTP 対象の snapshot 不足 (" + ", ".join(missing_ids) + ")"
        )
    missing_image_reference_ids = [channel_id for channel_id in approved_ids if channel_id not in image_reference_by_id]
    if missing_image_reference_ids:
        missing.append(
            "competitor-branding-snapshot.json に承認済み TTP 対象の画像参照メタ不足 ("
            + ", ".join(missing_image_reference_ids)
            + ")"
        )

    for channel_id in approved_ids:
        item = snapshot_by_id.get(channel_id)
        if item is None:
            continue
        missing_fields = [
            field for field in ("snippet", "brandingSettings", "localizations") if not isinstance(item.get(field), dict)
        ]
        if missing_fields:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に必須 field 不足 ({', '.join(missing_fields)})"
            )
        image_reference = image_reference_by_id.get(channel_id)
        if image_reference is None:
            continue
        if image_reference.get("reference_only") is not True:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} 画像参照メタ reference_only が true ではありません"
            )
        fallback_note_recorded = _channel_branding_fallback_note_recorded(channel_dir)
        if not _channel_image_reference_has_icon_source(image_reference) and not fallback_note_recorded:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に "
                "icon 画像参照または fallback 根拠 note がありません"
            )
        if not _channel_image_reference_has_banner_source(image_reference) and not fallback_note_recorded:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に "
                "banner 画像参照または fallback 根拠 note がありません"
            )

    missing.extend(
        _missing_channel_branding_thumbnail_config(channel_dir, approved_ids, image_references, image_reference_by_id)
    )
    missing.extend(_missing_channel_branding_outputs(channel_dir, seed_text))
    return missing


def _approved_ttp_channel_ids(channels: list[dict[str, object]]) -> list[str]:
    return [channel_id for channel in channels if (channel_id := str(channel.get("id") or "").strip())]


def _channel_image_reference_has_icon_source(image_reference: dict[str, object]) -> bool:
    icon = image_reference.get("icon")
    return isinstance(icon, dict) and isinstance(icon.get("url"), str) and bool(icon["url"].strip())


def _channel_image_reference_has_banner_source(image_reference: dict[str, object]) -> bool:
    banner = image_reference.get("banner")
    return isinstance(banner, list) and any(
        isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"].strip() for item in banner
    )


def _missing_channel_branding_thumbnail_config(
    channel_dir: Path,
    approved_ids: list[str],
    image_references: list[object],
    image_reference_by_id: dict[str, dict[str, object]],
) -> list[str]:
    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        return []
    image_generation = thumbnail_read.data.get("image_generation")
    if not isinstance(image_generation, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    channel_branding = reference_images.get("channel_branding")
    if not isinstance(channel_branding, dict):
        return ["thumbnail.yaml の reference_images.channel_branding 未設定"]

    missing: list[str] = []
    if channel_branding.get("snapshot") != "docs/channel/competitor-branding-snapshot.json":
        missing.append("thumbnail.yaml の reference_images.channel_branding.snapshot が未設定または不正")
    if channel_branding.get("output_icon") != "branding/icon.png":
        missing.append("thumbnail.yaml の reference_images.channel_branding.output_icon が未設定または不正")
    if channel_branding.get("output_banner") != "branding/banner.png":
        missing.append("thumbnail.yaml の reference_images.channel_branding.output_banner が未設定または不正")

    icon_required = any(
        _channel_image_reference_has_icon_source(image_reference_by_id[channel_id])
        for channel_id in approved_ids
        if channel_id in image_reference_by_id
    )
    banner_required = any(
        _channel_image_reference_has_banner_source(image_reference_by_id[channel_id])
        for channel_id in approved_ids
        if channel_id in image_reference_by_id
    )
    if icon_required:
        missing.extend(
            _missing_channel_branding_reference_list(
                "icon_references",
                channel_branding.get("icon_references"),
                image_references,
                "icon",
            )
        )
    if banner_required:
        missing.extend(
            _missing_channel_branding_reference_list(
                "banner_references",
                channel_branding.get("banner_references"),
                image_references,
                "banner",
            )
        )
    return missing


def _missing_channel_branding_reference_list(
    field_name: str,
    value: object,
    image_references: list[object],
    kind: str,
) -> list[str]:
    label = f"thumbnail.yaml の reference_images.channel_branding.{field_name}"
    if not isinstance(value, list) or not value:
        return [f"{label} 未設定"]

    invalid_refs = [
        str(item) for item in value if not _channel_branding_reference_resolves(item, image_references, kind)
    ]
    if invalid_refs:
        return [f"{label} に snapshot fragment として解決できない参照があります ({', '.join(invalid_refs)})"]
    return []


def _channel_branding_reference_resolves(value: object, image_references: list[object], kind: str) -> bool:
    if not isinstance(value, str) or not value.strip() or "{{" in value:
        return False

    if kind == "icon":
        match = re.fullmatch(
            r"docs/channel/competitor-branding-snapshot\.json#channel_image_references\[(\d+)\]\.icon",
            value.strip(),
        )
        if match is None:
            return False
        index = int(match.group(1))
        if index >= len(image_references):
            return False
        image_reference = image_references[index]
        return isinstance(image_reference, dict) and _channel_image_reference_has_icon_source(image_reference)

    if kind == "banner":
        match = re.fullmatch(
            r"docs/channel/competitor-branding-snapshot\.json#channel_image_references\[(\d+)\]\.banner\[(\d+)\]",
            value.strip(),
        )
        if match is None:
            return False
        image_index = int(match.group(1))
        banner_index = int(match.group(2))
        if image_index >= len(image_references):
            return False
        image_reference = image_references[image_index]
        if not isinstance(image_reference, dict):
            return False
        banner = image_reference.get("banner")
        if not isinstance(banner, list) or banner_index >= len(banner):
            return False
        banner_reference = banner[banner_index]
        return (
            isinstance(banner_reference, dict)
            and isinstance(banner_reference.get("url"), str)
            and bool(banner_reference["url"].strip())
        )

    return False


def _missing_channel_branding_outputs(channel_dir: Path, seed_text: str) -> list[str]:
    missing: list[str] = []
    missing.extend(
        _missing_channel_branding_output_image(
            channel_dir,
            "branding/icon.png",
            expected_ratio=1.0,
            max_size_bytes=4 * 1024 * 1024,
            label="branding/icon.png",
        )
    )
    missing.extend(
        _missing_channel_branding_output_image(
            channel_dir,
            "branding/banner.png",
            expected_ratio=16 / 9,
            max_size_bytes=6 * 1024 * 1024,
            label="branding/banner.png",
        )
    )
    if not _channel_branding_output_approved(seed_text):
        missing.append("docs/channel/ttp-seed-confirmation.md に channel branding 画像のユーザー承認記録がありません")
    return missing


def _missing_channel_branding_output_image(
    channel_dir: Path,
    relative_path: str,
    *,
    expected_ratio: float,
    max_size_bytes: int,
    label: str,
) -> list[str]:
    path = channel_dir / relative_path
    if not path.is_file():
        candidates = _channel_branding_output_candidates(channel_dir, relative_path)
        if candidates:
            candidate_list = ", ".join(candidates)
            if len(candidates) > 1:
                return [
                    f"{label} は見つかりませんが、既存候補が複数あります: {candidate_list}。"
                    f"最終版を確認してから変換してください。採用後に {label} にしてください（自動判定はしません）"
                ]
            return [
                f"{label} は見つかりませんが、既存候補があります: {candidate_list}。{label} にリネーム/変換してください"
            ]
        return [f"{label} が未生成"]
    try:
        if path.stat().st_size > max_size_bytes:
            return [f"{label} のファイルサイズが上限を超えています"]
    except OSError as exc:
        return [f"{label} のファイルサイズを確認できません ({exc})"]

    try:
        with PILImage.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        return [f"{label} を画像として読み込めません ({exc})"]

    if width <= 0 or height <= 0:
        return [f"{label} の画像サイズが不正です"]
    actual_ratio = width / height
    if abs(actual_ratio - expected_ratio) > 0.03:
        return [f"{label} のアスペクト比が不正です"]
    return []


def _channel_branding_output_candidates(channel_dir: Path, relative_path: str) -> list[str]:
    target = Path(relative_path)
    branding_dir = channel_dir / target.parent
    if not branding_dir.is_dir():
        return []

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    target_stem = target.stem
    versioned_pattern = re.compile(rf"^{re.escape(target_stem)}-v\d+$")
    candidates: list[str] = []
    for candidate in sorted(branding_dir.iterdir(), key=lambda item: item.name):
        if not candidate.is_file() or candidate.suffix.lower() not in allowed_suffixes:
            continue
        if candidate.stem == target_stem or versioned_pattern.fullmatch(candidate.stem):
            candidates.append(candidate.relative_to(channel_dir).as_posix())
    return candidates


def _channel_branding_output_approved(seed_text: str) -> bool:
    for line in seed_text.splitlines():
        lower_line = line.lower()
        mentions_branding_output = (
            "branding/icon.png" in lower_line
            or "branding/banner.png" in lower_line
            or "channel branding" in lower_line
            or "チャンネル画像" in line
        )
        if mentions_branding_output and ("承認済み" in line or "approved" in lower_line):
            return True
    return False


def _channel_branding_fallback_note_recorded(channel_dir: Path) -> bool:
    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        return False
    image_generation = thumbnail_read.data.get("image_generation")
    if not isinstance(image_generation, dict):
        return False
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return False
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return False
    notes = reference_images.get("notes")
    if not isinstance(notes, str):
        return False
    lower_notes = notes.lower()
    return "fallback" in lower_notes or "取得できない" in notes or "参照画像なし" in notes


def _approved_ttp_channel_slugs(channels: list[dict[str, object]]) -> list[str]:
    return [slug for channel in channels if (slug := str(channel.get("slug") or "").strip())]


def _video_analysis_slug_dir(channel_dir: Path, video_analysis_dir: Path, slug: str) -> tuple[Path | None, str | None]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug):
        return None, f"benchmark.channels の slug が不正 ({_safe_diagnostic_value(slug)})"
    channel_root = channel_dir.resolve(strict=False)
    root = video_analysis_dir.resolve(strict=False)
    candidate = (video_analysis_dir / slug).resolve(strict=False)
    try:
        root.relative_to(channel_root)
    except ValueError:
        return None, "data/video_analysis の channel_dir 外参照を拒否"
    try:
        candidate.relative_to(root)
        candidate.relative_to(channel_root)
    except ValueError:
        return None, f"data/video_analysis の channel_dir 外参照を拒否 ({_safe_diagnostic_value(slug)})"
    return candidate, None


def _channel_diagnostic_label(index: int, channel: dict[str, object]) -> str:
    parts = [f"entry #{index + 1}"]
    if channel_id := _safe_diagnostic_value(channel.get("id")):
        parts.append(f"id={channel_id}")
    if slug := _safe_diagnostic_value(channel.get("slug")):
        parts.append(f"slug={slug}")
    return " ".join(parts)


def _safe_diagnostic_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9_.:@/-]", "_", text)[:80]


def _thumbnail_ttp_reference_missing_reason(channel_dir: Path, thumbnail: dict[str, object]) -> str | None:
    refs, invalid_refs = _thumbnail_reference_images(channel_dir, thumbnail)
    if invalid_refs:
        sample = ", ".join(invalid_refs[:3])
        return f"reference_images.default の参照パスが不正: {sample}"
    if not refs:
        return "thumbnail reference_images.default 未設定 / reference_images.default が空または未転記"

    missing_refs = [str(path) for path in refs if not path.is_file()]
    if missing_refs:
        sample = ", ".join(missing_refs[:3])
        return f"reference_images.default の参照先が見つからない / 参照画像が存在しない: {sample}"
    return None


def _benchmark_report_files(channel_dir: Path) -> list[Path]:
    return _matching_files(channel_dir / "docs" / "benchmarks", "*.md")


def _benchmark_thumbnail_files(channel_dir: Path) -> list[Path]:
    root = channel_dir / "data" / "thumbnail_compare" / "benchmark"
    if not root.is_dir():
        return []
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.rglob(pattern) if path.is_file())
    return sorted(files)


def _thumbnail_reference_images(
    channel_dir: Path,
    thumbnail: dict[str, object] | None = None,
) -> tuple[list[Path], list[str]]:
    if thumbnail is None:
        thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
        if thumbnail_read.error:
            return [], [thumbnail_read.error]
        thumbnail = thumbnail_read.data

    image_generation = thumbnail.get("image_generation")
    if not isinstance(image_generation, dict):
        return [], []
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return [], []
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return [], []

    resolved = resolve_configured_benchmark_references(channel_dir, reference_images.get("default"))
    invalid_refs = list(resolved.invalid_reasons)
    invalid_refs.extend(f"未解決 placeholder が残っている: {value}" for value in resolved.placeholders)
    return resolved.references, invalid_refs


@dataclass(frozen=True)
class _MusicReadiness:
    ready: bool
    errors: list[str]


def _suno_music_readiness(channel_dir: Path, channels: list[dict[str, object]]) -> _MusicReadiness:
    errors: list[str] = []
    suno, suno_error = _load_skill_config_for_channel("music.prompt", channel_dir)
    if suno_error:
        errors.append(suno_error)
    genre_line = str(suno.get("genre_line") or "")
    style_char_limit = suno.get("style_char_limit", 120)
    try:
        limit = int(style_char_limit)
    except (TypeError, ValueError):
        limit = 120
        errors.append("suno.style_char_limit が数値ではありません")
    genre_ready = False
    if genre_line.strip():
        if len(genre_line) <= limit:
            genre_ready = True
        else:
            errors.append(f"Suno genre_line が style_char_limit 超過 ({len(genre_line)}/{limit})")
    variants = suno.get("style_variants")
    if isinstance(variants, dict):
        for name, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            variant_genre_line = variant.get("genre_line")
            if isinstance(variant_genre_line, str) and len(variant_genre_line) > limit:
                errors.append(
                    "Suno style_variants."
                    f"{_safe_diagnostic_value(name)}.genre_line が style_char_limit 超過 "
                    f"({len(variant_genre_line)}/{limit})"
                )
    if genre_ready:
        return _MusicReadiness(True, errors)

    video_analysis_dir = channel_dir / "data" / "video_analysis"
    slug_dirs: list[Path] = []
    for slug in _approved_ttp_channel_slugs(channels):
        slug_dir, slug_error = _video_analysis_slug_dir(channel_dir, video_analysis_dir, slug)
        if slug_error:
            errors.append(slug_error)
            continue
        if slug_dir is None:
            continue
        slug_dirs.append(slug_dir)
    if not video_analysis_dir.is_dir():
        return _MusicReadiness(False, errors)
    for slug_dir in slug_dirs:
        for path in slug_dir.glob("*.json"):
            payload_read = _read_json_mapping(path)
            if payload_read.error:
                errors.append(payload_read.error)
                continue
            payload = payload_read.data
            preset = payload.get("suno_preset")
            if isinstance(preset, dict) and str(preset.get("genre_line") or "").strip():
                return _MusicReadiness(True, errors)
    return _MusicReadiness(False, errors)


def evaluate_initial_setup_readiness(channel_dir: Path) -> ReadinessResult:
    issues: list[str] = []

    approved_exceptions: set[str] = set()
    seed_confirmation = channel_dir / "docs" / "channel" / "ttp-seed-confirmation.md"
    if seed_confirmation.is_file():
        try:
            seed_text = seed_confirmation.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(f"docs/channel/ttp-seed-confirmation.md 読み込み失敗: {exc}")
        else:
            approved_exceptions, _ = approved_ttp_exceptions(seed_text)

    thumbnail_cfg, thumbnail_error = _load_skill_config_for_channel("thumbnail", channel_dir)
    if thumbnail_error:
        issues.append(thumbnail_error)
    else:
        issues.extend(
            check_thumbnail_skill_config(
                channel_dir,
                thumbnail_cfg,
                skip_reference_images="thumbnail" in approved_exceptions,
            )
        )

    suno_cfg, suno_error = _load_skill_config_for_channel("music.prompt", channel_dir)
    if suno_error:
        issues.append(suno_error)
    else:
        msg = check_suno_genre_line_char_limit(suno_cfg)
        if msg:
            issues.append(msg)

    for desc_md in _planning_descriptions_md_paths(channel_dir):
        msg = check_descriptions_md_parseability(desc_md, allowed_root=channel_dir)
        if msg:
            issues.append(msg)

    if not issues:
        return ReadinessResult(
            status="ok",
            message="初期セットアップの thumbnail / suno / descriptions.md 事前検査 OK",
        )

    return ReadinessResult(
        status="warn",
        message="; ".join(issues),
        next_action={
            "kind": "human",
            "instructions": (
                "/setup --regenerate で config/skills/thumbnail.yaml と config/skills/music.yaml::prompt を再確認し、"
                "descriptions.md の parse 失敗は /video --describe で再生成してください"
            ),
        },
    )


def _load_skill_config_for_channel(skill: str, channel_dir: Path) -> tuple[dict, str | None]:
    try:
        return load_skill_config(skill, use_cache=False, channel_dir=channel_dir), None
    except (ConfigError, OSError, yaml.YAMLError) as exc:
        return {}, f"config/skills/{skill}.yaml 読み込み失敗: {exc}"


def _planning_descriptions_md_paths(channel_dir: Path) -> list[Path]:
    planning_root = channel_dir / "collections" / "planning"
    if not planning_root.is_dir():
        return []
    return sorted(planning_root.glob("*/20-documentation/descriptions.md"))


__all__ = [
    "ReadinessResult",
    "approved_ttp_exceptions",
    "evaluate_initial_setup_readiness",
    "evaluate_ttp_wf_new_readiness",
]
