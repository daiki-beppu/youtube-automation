"""yt-channel-init — config 一式と channel-new 初期運用ファイルを生成する CLI."""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from youtube_automation.cli.channel_init_templates import (
    BENCHMARK_CHANNEL_SEPARATOR,
    CHANNEL_CONFIG_TEMPLATES,
    CONFIG_SUBDIR,
    DEFAULT_LOCALIZATION_LANGUAGES,
    OPTIONAL_CHANNEL_CONFIG_TEMPLATES,
    PLACEHOLDER_DEFAULT,
    ROOT_JSON_TEMPLATES,
    ROOT_TEXT_TEMPLATES,
    ChannelInitContext,
    serialize_json,
)
from youtube_automation.cli.setup_directory_contract import validate_existing_setup_directories
from youtube_automation.cli.target_resolver import resolve_existing_target_dir
from youtube_automation.utils.channel_settings import normalize_locale_to_short
from youtube_automation.utils.exceptions import ConfigError

NO_DIFF_PATHS: frozenset[str] = frozenset({".env"})


class ActionKind(Enum):
    """ファイル / ディレクトリ操作種別。文字列値はそのまま stdout サマリーに使う."""

    CREATED = "created"
    SKIPPED = "skipped"
    OVERWRITTEN = "overwritten"


@dataclass(frozen=True)
class FileAction:
    path: Path
    rel: str
    kind: ActionKind
    new_text: str = ""
    diff: str = ""


@dataclass(frozen=True)
class Plan:
    files: list[FileAction] = field(default_factory=list)


def _parse_benchmark_channel(value: str) -> dict[str, str]:
    parts = value.split(BENCHMARK_CHANNEL_SEPARATOR)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"--benchmark-channel は id{BENCHMARK_CHANNEL_SEPARATOR}slug"
            f"{BENCHMARK_CHANNEL_SEPARATOR}name{BENCHMARK_CHANNEL_SEPARATOR}relationship 形式で指定してください"
        )
    channel_id, slug, name, relationship = (part.strip() for part in parts)
    if not channel_id or not slug or not name or not relationship:
        raise argparse.ArgumentTypeError("--benchmark-channel に空の要素は指定できません")
    return {
        "id": channel_id,
        "slug": slug,
        "name": name,
        "relationship": relationship,
    }


def _normalize_repeated_option(values: list | None) -> tuple:
    if values is None:
        return ()
    return tuple(values)


def _parse_non_empty(value: str) -> str:
    text = value.strip()
    if not text:
        raise argparse.ArgumentTypeError("空文字は指定できません")
    return text


def _parse_language(value: str) -> str:
    language = value.strip()
    if not language:
        raise argparse.ArgumentTypeError("言語コードに空文字は指定できません")
    return language


def _resolve_localization_languages(
    values: list[str] | None,
    default_language: str,
) -> tuple[str, tuple[str, ...]]:
    languages = DEFAULT_LOCALIZATION_LANGUAGES if values is None else tuple(values)
    default = _canonicalize_language(default_language)
    languages = tuple(_canonicalize_language(lang) for lang in languages)
    if len(set(languages)) != len(languages):
        raise argparse.ArgumentTypeError("--supported-language に重複した言語コードは指定できません")
    if default not in languages:
        raise argparse.ArgumentTypeError("--default-language は --supported-language のいずれかに含めてください")
    return default, languages


def _canonicalize_language(value: str) -> str:
    language = _parse_language(value)
    return normalize_locale_to_short(language)


def _resolve_target_duration_bounds(
    target_min: float | None,
    target_max: float | None,
) -> tuple[float | None, float | None]:
    if target_min is not None and target_min < 1:
        raise argparse.ArgumentTypeError("--target-duration-min は 1 以上を指定してください")
    if target_max is not None and target_max < 1:
        raise argparse.ArgumentTypeError("--target-duration-max は 1 以上を指定してください")
    if target_min is not None and target_max is not None and target_min > target_max:
        raise argparse.ArgumentTypeError("--target-duration-min は --target-duration-max 以下を指定してください")
    return target_min, target_max


def _resolve_distrokid_profile(args: argparse.Namespace) -> dict | None:
    profile_values = (
        args.distrokid_artist,
        args.distrokid_language,
        args.distrokid_main_genre,
        args.distrokid_sub_genre,
        args.distrokid_songwriter_first,
        args.distrokid_songwriter_last,
    )
    if not args.distrokid_enabled:
        if any(value is not None for value in profile_values):
            raise argparse.ArgumentTypeError("DistroKid profile 引数を使う場合は --distrokid-enabled が必要です")
        return None

    if args.distrokid_artist is None or args.distrokid_language is None or args.distrokid_main_genre is None:
        raise argparse.ArgumentTypeError(
            "--distrokid-enabled を使う場合は --distrokid-artist, --distrokid-language, "
            "--distrokid-main-genre が必要です"
        )

    if bool(args.distrokid_songwriter_first) != bool(args.distrokid_songwriter_last):
        raise argparse.ArgumentTypeError(
            "--distrokid-songwriter-first と --distrokid-songwriter-last はセットで指定してください"
        )

    profile: dict[str, object] = {
        "artist": args.distrokid_artist,
        "language": args.distrokid_language,
        "main_genre": args.distrokid_main_genre,
    }
    if args.distrokid_sub_genre is not None:
        profile["sub_genre"] = args.distrokid_sub_genre
    if args.distrokid_songwriter_first and args.distrokid_songwriter_last:
        songwriter = {
            "first": args.distrokid_songwriter_first,
            "last": args.distrokid_songwriter_last,
        }
        profile["songwriter"] = songwriter
    return profile


def _resolve_target_dir(target: str | None) -> Path:
    return resolve_existing_target_dir(target)


def _plan_actions(target: Path, ctx: ChannelInitContext, *, force: bool) -> Plan:
    """副作用なしで `Plan` を組み立てる（既存ファイルの read のみ実施）."""
    validate_existing_setup_directories(target)
    files: list[FileAction] = []
    config_dir = target / CONFIG_SUBDIR
    for name, render in CHANNEL_CONFIG_TEMPLATES.items():
        path = config_dir / name
        rel = (CONFIG_SUBDIR / name).as_posix()
        new_text = serialize_json(render(ctx))
        files.append(_plan_file(path, rel, new_text, force=force))
    for name, render in OPTIONAL_CHANNEL_CONFIG_TEMPLATES.items():
        if name == "distrokid.json" and ctx.distrokid_profile is None:
            continue
        path = config_dir / name
        rel = (CONFIG_SUBDIR / name).as_posix()
        new_text = serialize_json(render(ctx))
        files.append(_plan_file(path, rel, new_text, force=force))
    for rel_path, render in ROOT_JSON_TEMPLATES.items():
        path = target / rel_path
        new_text = serialize_json(render(ctx))
        files.append(_plan_file(path, rel_path.as_posix(), new_text, force=force))
    for rel_path, render in ROOT_TEXT_TEMPLATES.items():
        path = target / rel_path
        files.append(_plan_file(path, rel_path.as_posix(), render(ctx), force=force))

    return Plan(files=files)


def _plan_file(path: Path, rel: str, new_text: str, *, force: bool) -> FileAction:
    _validate_parent_directories(path, rel)
    if not path.exists():
        return FileAction(path=path, rel=rel, kind=ActionKind.CREATED, new_text=new_text)
    if not path.is_file():
        raise ConfigError(f"{rel} は通常ファイルである必要があります: {path}")

    current = path.read_text(encoding="utf-8")
    if current == new_text:
        return FileAction(path=path, rel=rel, kind=ActionKind.SKIPPED, new_text=new_text)
    if rel in NO_DIFF_PATHS:
        return FileAction(path=path, rel=rel, kind=ActionKind.SKIPPED, new_text=new_text)
    if force:
        return FileAction(path=path, rel=rel, kind=ActionKind.OVERWRITTEN, new_text=new_text)

    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{rel} (existing)",
            tofile=f"{rel} (template)",
        )
    )
    return FileAction(path=path, rel=rel, kind=ActionKind.SKIPPED, new_text=new_text, diff=diff)


def _validate_parent_directories(path: Path, rel: str) -> None:
    for index, parent_rel in enumerate(Path(rel).parents):
        if parent_rel == Path("."):
            break
        parent = path.parents[index]
        if parent.exists() and not parent.is_dir():
            raise ConfigError(f"{rel} の親ディレクトリ {parent_rel} はディレクトリである必要があります: {parent}")


def _apply(plan: Plan) -> None:
    for action in plan.files:
        if action.kind in (ActionKind.CREATED, ActionKind.OVERWRITTEN):
            action.path.parent.mkdir(parents=True, exist_ok=True)
            action.path.write_text(action.new_text, encoding="utf-8")


def _format_summary(plan: Plan) -> str:
    lines: list[str] = []
    for action in plan.files:
        lines.append(f"  {action.kind.value:<11} {action.rel}")
    return "\n".join(lines)


def _collect_diffs(plan: Plan) -> str:
    return "".join(action.diff for action in plan.files if action.diff)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel-init",
        description=(
            "config 一式と channel-new 初期運用ファイルを生成する。既存ファイルは --force がない限り上書きしない。"
        ),
    )
    parser.add_argument(
        "--target",
        default=None,
        help="ターゲットチャンネルディレクトリ (default: CHANNEL_DIR → CWD)",
    )
    parser.add_argument("--short", required=True, help="仮チャンネルの短縮シンボル (例: BGM01)")
    parser.add_argument("--name", required=True, help="仮チャンネル名")
    parser.add_argument(
        "--genre",
        default=PLACEHOLDER_DEFAULT,
        help=f'ジャンル placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--style",
        default=PLACEHOLDER_DEFAULT,
        help=f'スタイル placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--context",
        default=PLACEHOLDER_DEFAULT,
        help=f'利用コンテキスト placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--core-message",
        default=PLACEHOLDER_DEFAULT,
        help=f'チャンネルのコアメッセージ placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--target-duration-min",
        type=float,
        default=None,
        help="動画尺の下限値 (分)",
    )
    parser.add_argument(
        "--target-duration-max",
        type=float,
        default=None,
        help="動画尺の上限値 (分)",
    )
    parser.add_argument(
        "--music-engine",
        choices=("suno", "lyria"),
        default="suno",
        help='チャンネルのデフォルト音楽エンジン (default: "suno")',
    )
    parser.add_argument(
        "--benchmark-channel",
        action="append",
        type=_parse_benchmark_channel,
        default=None,
        metavar="ID|SLUG|NAME|RELATIONSHIP",
        help="TTP ベンチマーク対象。複数回指定可",
    )
    parser.add_argument(
        "--channel-keyword",
        action="append",
        default=None,
        help="YouTube branding keyword。複数回指定可",
    )
    parser.add_argument("--branding-description", default="", help="YouTube branding description 初期値")
    parser.add_argument("--country", default="", help="YouTube branding country 初期値")
    parser.add_argument("--default-language", default="en", help='YouTube branding default_language (default: "en")')
    parser.add_argument(
        "--supported-language",
        action="append",
        type=_parse_language,
        default=None,
        metavar="LANG",
        help='localizations の supported_languages。複数回指定可 (default: "ja", "en", "de")',
    )
    parser.add_argument(
        "--distrokid-enabled",
        action="store_true",
        help="DistroKid 配信設定 config/channel/distrokid.json を生成し、distrokid.enabled=true にする",
    )
    parser.add_argument(
        "--distrokid-artist",
        type=_parse_non_empty,
        default=None,
        help="DistroKid リリースアーティスト名 (--distrokid-enabled 指定時は必須)",
    )
    parser.add_argument(
        "--distrokid-language",
        type=_parse_language,
        default=None,
        help="DistroKid メタデータ言語 (--distrokid-enabled 指定時は必須)",
    )
    parser.add_argument(
        "--distrokid-main-genre",
        type=_parse_non_empty,
        default=None,
        help="DistroKid main_genre (--distrokid-enabled 指定時は必須)",
    )
    parser.add_argument(
        "--distrokid-sub-genre",
        type=_parse_non_empty,
        default=None,
        help="DistroKid sub_genre",
    )
    parser.add_argument(
        "--distrokid-songwriter-first",
        type=_parse_non_empty,
        default=None,
        help="DistroKid songwriter.first",
    )
    parser.add_argument(
        "--distrokid-songwriter-last",
        type=_parse_non_empty,
        default=None,
        help="DistroKid songwriter.last",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="既存ファイルを上書きする（.env は機密保護のため常に保持）",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        default_language, supported_languages = _resolve_localization_languages(
            args.supported_language,
            args.default_language,
        )
        target_duration_min, target_duration_max = _resolve_target_duration_bounds(
            args.target_duration_min,
            args.target_duration_max,
        )
        distrokid_profile = _resolve_distrokid_profile(args)
    except argparse.ArgumentTypeError as e:
        parser.error(str(e))

    try:
        target = _resolve_target_dir(args.target)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    ctx = ChannelInitContext(
        short=args.short,
        name=args.name,
        genre=args.genre,
        style=args.style,
        context=args.context,
        core_message=args.core_message,
        target_duration_min=target_duration_min,
        target_duration_max=target_duration_max,
        music_engine=args.music_engine,
        benchmark_channels=_normalize_repeated_option(args.benchmark_channel),
        channel_keywords=_normalize_repeated_option(args.channel_keyword),
        branding_description=args.branding_description,
        country=args.country,
        default_language=default_language,
        supported_languages=supported_languages,
        distrokid_profile=distrokid_profile,
    )

    try:
        plan = _plan_actions(target, ctx, force=args.force)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    diffs = _collect_diffs(plan)
    if diffs:
        sys.stderr.write(diffs)

    _apply(plan)
    print(_format_summary(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
