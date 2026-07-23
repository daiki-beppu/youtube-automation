#!/usr/bin/env python3
"""yt-distrokid-prepare: DistroKid 配信成果物 `30-distrokid/` を準備する CLI（#936）.

サブコマンド:
  plan   – disc 分割計画を draft spec.json に書き出す
  build  – spec.json に従って mp3 コピー / metadata.md / README.md を生成する
  cover  – ジャケット画像を 3000×3000 JPEG に最終化して cover_art_3000.jpg へ保存する
  verify – 生成成果物を読む側（build_release_payload）と同一コードパスで検証する

エラーハンドリング方針:
- ConfigError / ValidationError のみ catch して "[ERROR] ..." を表示し exit 1
- 生 Exception / KeyError を catch しない（リポジトリ規約）
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from youtube_automation.configuration import load_config
from youtube_automation.domains.distrokid.preparation import (
    _MAX_TRACKS_PER_DISC,
    COVER_ART_FILENAME,
    DISTROKID_DIRNAME,
    INDIVIDUAL_MUSIC_DIRNAME,
    build_draft_spec,
    format_total_duration,
    render_metadata_md,
    render_readme_md,
    resize_cover,
    split_tracks,
    validate_spec,
    verify_roundtrip,
    write_release_date,
)
from youtube_automation.domains.distrokid.release import (
    build_release_payload,
)
from youtube_automation.domains.distrokid.specification import SPEC_FILENAME, write_collection_spec
from youtube_automation.scripts.collection_serve import find_distrokid_discs
from youtube_automation.utils.collection_paths import CollectionPaths, resolve_collection_dir
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.probe import probe_duration

# ファイル名先頭の連番プレフィックス（metadata.md の # 列 = グローバル番号として使う）
_GLOBAL_NUM_RE = re.compile(r"^(\d+)-")


def _global_num(filename: str) -> int:
    """ファイル名の連番プレフィックスをグローバル番号として返す（#936）."""
    m = _GLOBAL_NUM_RE.match(filename)
    if m:
        return int(m.group(1))
    raise ConfigError(
        f"ファイル名に連番プレフィックスがありません: {filename!r}\n"
        "metadata.md の # 列はファイル名の先頭連番と一致する必要があります。"
    )


def _cmd_plan(args: argparse.Namespace) -> None:
    """plan サブコマンド: disc 分割計画を draft spec.json に書き出す（#936）."""
    collection_dir = resolve_collection_dir(args.collection)
    config = load_config()

    if not config.distrokid.enabled:
        raise ConfigError(
            "config.distrokid.enabled が False です。"
            "config/channel/distrokid.json の distrokid.enabled を true に設定してください。"
        )

    # mp3 一覧取得
    music_dir = collection_dir / INDIVIDUAL_MUSIC_DIRNAME
    mp3_files = sorted(music_dir.glob("*.mp3")) if music_dir.is_dir() else []
    filenames = [f.name for f in mp3_files]

    # 分割実行
    chunks = split_tracks(
        filenames,
        discs=args.discs,
        max_per_disc=args.max_per_disc,
    )

    # draft spec 生成
    paths = CollectionPaths(collection_dir)
    spec = build_draft_spec(
        paths.collection_name,
        chunks,
        artist=config.distrokid.profile.artist or config.meta.channel_name,
        language=config.distrokid.profile.language,
        genre_primary=config.distrokid.profile.main_genre,
        genre_secondary=config.distrokid.profile.sub_genre,
    )

    # 出力先決定
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = collection_dir / DISTROKID_DIRNAME / SPEC_FILENAME

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # サマリ表示
    n_discs = len(chunks)
    print(f"disc 分割サマリ: {n_discs} discs")
    for i, chunk in enumerate(chunks, start=1):
        print(f"  disc{i}: {len(chunk)} 曲")
    print(f"\nspec.json を書き出しました: {output_path}")

    # needs_unique トラックの数を確認して案内
    all_discs = spec.get("discs", [])
    needs_unique_count = sum(1 for d in all_discs for t in d.get("tracks", []) if t.get("needs_unique"))
    if needs_unique_count > 0:
        print(
            f"\n⚠ needs_unique なトラックが {needs_unique_count} 件あります。"
            "\n  spec.json の needs_unique トラックをユニーク化してから"
            "\n  yt-distrokid-prepare build --spec <path> を実行してください。"
        )
    else:
        print(f"\n次のステップ:\n  yt-distrokid-prepare build --spec {output_path} {collection_dir}")


def _cmd_build(args: argparse.Namespace) -> None:
    """build サブコマンド: spec.json に従って成果物を生成する（#936）."""
    collection_dir = resolve_collection_dir(args.collection)

    # spec 読み込み
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        raise ConfigError(f"spec.json が見つかりません: {spec_path}")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"spec.json が不正な JSON です: {spec_path}\n{exc}") from exc

    # release-date 検証
    release_date: str | None = None
    if args.release_date:
        try:
            datetime.date.fromisoformat(args.release_date)
        except ValueError as exc:
            raise ConfigError(f"--release-date の形式が不正です（YYYY-MM-DD が必要）: {args.release_date!r}") from exc
        release_date = args.release_date

    # mp3 一覧
    music_dir = collection_dir / INDIVIDUAL_MUSIC_DIRNAME
    mp3_files = sorted(music_dir.glob("*.mp3")) if music_dir.is_dir() else []
    music_filenames = [f.name for f in mp3_files]

    # spec 検証
    validate_spec(spec, music_filenames)

    # 冪等性チェック
    distrokid_dir = collection_dir / DISTROKID_DIRNAME
    discs = spec.get("discs", [])
    for disc in discs:
        slug = disc["slug"]
        disc_dir = distrokid_dir / slug
        has_existing_mp3 = disc_dir.is_dir() and any(disc_dir.glob("*.mp3"))
        if has_existing_mp3 and not args.force:
            raise ConfigError(
                f"既存の disc ディレクトリに mp3 があります: {disc_dir}\n--force を指定して再生成してください。"
            )

    # --force: spec に載っている disc dir のみ rmtree
    if args.force:
        for disc in discs:
            slug = disc["slug"]
            disc_dir = distrokid_dir / slug
            if disc_dir.is_dir():
                shutil.rmtree(disc_dir)

    # 検証済み spec を canonical パス（30-distrokid/spec.json）へ atomic 書き込みする（#941）。
    # serve が 30-distrokid/spec.json を SSOT として直接読むために必要。
    # --spec が canonical と同一パスでも問題ない（読み込み済み dict を書くため自己上書き OK）。
    # 冪等性チェックの後に書く: --force 不足で build を拒否した場合に
    # ディスク上の状態を一切変更しないため（#941）。
    write_collection_spec(distrokid_dir, spec)
    # spec.json を先頭に追加。serve が SSOT として直接読む canonical ファイル（#941）。
    generated_files: list[Path] = [distrokid_dir / SPEC_FILENAME]

    # 全 disc の mp3 を probe して尺計測
    all_durations: dict[str, float] = {}
    for disc in discs:
        for track in disc.get("tracks", []):
            fn = track["filename"]
            mp3_path = music_dir / fn
            dur = probe_duration(mp3_path)
            if dur is None:
                raise ConfigError(
                    f"ffprobe で尺を計測できませんでした: {mp3_path}\n"
                    "ffprobe がインストールされているか確認してください（brew install ffmpeg）。"
                )
            all_durations[fn] = dur

    # global_numbers マッピング
    global_numbers: dict[str, int] = {}
    for disc in discs:
        for track in disc.get("tracks", []):
            fn = track["filename"]
            global_numbers[fn] = _global_num(fn)

    # 各 disc の成果物生成
    disc_infos: list[dict] = []

    for disc in discs:
        slug = disc["slug"]
        disc_dir = distrokid_dir / slug
        disc_dir.mkdir(parents=True, exist_ok=True)

        # mp3 コピー（リネームなし）
        for track in disc.get("tracks", []):
            fn = track["filename"]
            src = music_dir / fn
            dst = disc_dir / fn
            shutil.copy2(src, dst)
            generated_files.append(dst)

        # metadata.md 生成
        md_path = disc_dir / "metadata.md"
        md_content = render_metadata_md(
            disc,
            all_durations,
            global_numbers,
            release_date=release_date,
            genre_primary=spec.get("genre_primary", ""),
            genre_secondary=spec.get("genre_secondary"),
            artist=spec.get("artist", ""),
            language=spec.get("language", ""),
        )
        md_path.write_text(md_content, encoding="utf-8")
        generated_files.append(md_path)

        # ラウンドトリップ検証
        track_list = disc.get("tracks", [])
        expected_numbers = [global_numbers[t["filename"]] for t in track_list]
        verify_roundtrip(md_path, disc, expected_numbers)

        # disc 統計
        total_secs = sum(all_durations.get(t["filename"], 0.0) for t in track_list)
        total_bytes = sum((music_dir / t["filename"]).stat().st_size for t in track_list)
        total_mb = total_bytes / (1024 * 1024)
        max_secs = max(
            (all_durations.get(t["filename"], 0.0) for t in track_list),
            default=0.0,
        )
        disc_infos.append(
            {
                "slug": slug,
                "album_title": disc["album_title"],
                "count": len(track_list),
                "total_secs": total_secs,
                "total_mb": total_mb,
                "max_secs": max_secs,
            }
        )

    # README.md 生成
    readme_path = distrokid_dir / "README.md"
    readme_content = render_readme_md(spec, disc_infos, collection_dir)
    readme_path.write_text(readme_content, encoding="utf-8")
    generated_files.append(readme_path)

    # --release-date: workflow-state.json 更新
    if release_date:
        paths = CollectionPaths(collection_dir)
        write_release_date(paths.workflow_state_path, release_date)
        generated_files.append(paths.workflow_state_path)

    # サマリ表示
    total_tracks = sum(d["count"] for d in disc_infos)
    total_secs_all = sum(d["total_secs"] for d in disc_infos)
    print(f"\n✅ build 完了: {len(discs)} discs / {total_tracks} 曲 / 合計 {format_total_duration(total_secs_all)}")
    for di in disc_infos:
        print(f"  {di['slug']}: {di['count']} 曲 / {format_total_duration(di['total_secs'])}")
    print(f"\n生成ファイル ({len(generated_files)} 件):")
    for p in generated_files:
        print(f"  {p}")
    if release_date:
        print(f"\nリリース日を workflow-state.json に設定しました: {release_date}")


def _cmd_cover(args: argparse.Namespace) -> None:
    """cover サブコマンド: ジャケット画像を 3000×3000 JPEG に最終化する（#936）."""
    collection_dir = resolve_collection_dir(args.collection)
    input_path = Path(args.input)
    output_path = collection_dir / DISTROKID_DIRNAME / COVER_ART_FILENAME

    # 10-assets/ 配下の既存サムネ流用は非推奨の警告
    assets_dir = collection_dir / "10-assets"
    try:
        input_path.resolve().relative_to(assets_dir.resolve())
        print(
            f"⚠  警告: 入力画像が 10-assets/ 配下です: {input_path}\n"
            "  DistroKid ジャケットは YouTube サムネイルとは別に新規 AI 生成することを推奨します。"
        )
    except ValueError:
        pass  # 10-assets/ 外ならOK

    resize_cover(input_path, output_path, crop=args.crop, force=args.force)

    print(f"✅ カバーアートを保存しました: {output_path}")
    print("  サイズ: 3000×3000 JPEG")


def _cmd_verify(args: argparse.Namespace) -> None:
    """verify サブコマンド: 生成成果物を読む側と同一コードパスで検証する（#936）."""
    collection_dir = resolve_collection_dir(args.collection)
    config = load_config()

    if not config.distrokid.enabled:
        raise ConfigError(
            "config.distrokid.enabled が False です。"
            "verify を実行するには distrokid.enabled を true に設定してください。"
        )

    distrokid_dir = collection_dir / DISTROKID_DIRNAME
    disc_names = find_distrokid_discs(collection_dir)

    if not disc_names:
        raise ConfigError(
            f"30-distrokid/ 配下に mp3 を含む disc ディレクトリが見つかりません: {distrokid_dir}\n"
            "先に yt-distrokid-prepare build を実行してください。"
        )

    errors: list[str] = []
    warnings: list[str] = []

    # cover_art_3000.jpg の存在とサイズ検証
    cover_path = distrokid_dir / COVER_ART_FILENAME
    if not cover_path.is_file():
        errors.append(f"cover_art_3000.jpg が存在しません: {cover_path}")
    else:
        try:
            img = Image.open(cover_path)
            if img.size != (3000, 3000):
                errors.append(f"cover_art_3000.jpg のサイズが 3000×3000 ではありません: {img.size}")
            if img.format != "JPEG":
                errors.append(f"cover_art_3000.jpg が JPEG ではありません: {img.format}")
        except (UnidentifiedImageError, OSError) as exc:
            errors.append(f"cover_art_3000.jpg を開けませんでした: {exc}")

    # workflow-state.json の publish_target_at 確認
    paths = CollectionPaths(collection_dir)
    if paths.workflow_state_path.is_file():
        try:
            state = json.loads(paths.workflow_state_path.read_text(encoding="utf-8"))
            publish_at = (state.get("planning") or {}).get("publish_target_at")
            if not publish_at:
                warnings.append(
                    "workflow-state.json の planning.publish_target_at が未設定です。"
                    "\n  yt-distrokid-prepare build --release-date YYYY-MM-DD で設定できます。"
                )
        except (json.JSONDecodeError, OSError):
            warnings.append("workflow-state.json の読み取りに失敗しました。")
    else:
        warnings.append("workflow-state.json が存在しません（publish_target_at 未設定）。")

    # disc 横断タイトルユニーク・disc 曲数チェック
    all_titles: list[str] = []
    disc_results: list[dict] = []

    for disc_name in disc_names:
        # build_release_payload で読む側と同一コードパスで検証
        payload = build_release_payload(
            collection_dir,
            config.distrokid,
            distrokid_source=f"{DISTROKID_DIRNAME}/{disc_name}",
        )
        tracks = payload["release"].get("tracks", [])
        track_count = len(tracks)

        if track_count > _MAX_TRACKS_PER_DISC:
            errors.append(f"disc {disc_name!r} の曲数 {track_count} が上限 {_MAX_TRACKS_PER_DISC} を超えています。")

        for t in tracks:
            all_titles.append(t["title"])

        disc_results.append(
            {
                "disc": disc_name,
                "album_title": payload["release"].get("album_title", ""),
                "track_count": track_count,
                "cover": payload["release"].get("cover"),
            }
        )

    # disc 横断タイトルユニーク
    title_counter = Counter(all_titles)
    dup_titles = [t for t, c in title_counter.items() if c > 1]
    if dup_titles:
        errors.append(f"disc 横断でトラックタイトルが重複しています: {dup_titles}")

    # サマリ表示
    print(f"\n{'=' * 60}")
    print(f"verify: {collection_dir.name}")
    print(f"{'=' * 60}")
    print(f"{'disc':<35} {'曲数':>5} {'album_title'}")
    print(f"{'-' * 60}")
    for r in disc_results:
        print(f"{r['disc']:<35} {r['track_count']:>5}  {r['album_title']}")

    if warnings:
        print(f"\n⚠  警告 ({len(warnings)} 件):")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print(f"\n❌ エラー ({len(errors)} 件):")
        for e in errors:
            print(f"  - {e}")
        raise ConfigError(f"verify で {len(errors)} 件のエラーが見つかりました。上記を確認してください。")

    print(f"\n✅ verify 完了: {len(disc_results)} discs すべてパスしました。")


def _build_parser() -> argparse.ArgumentParser:
    """argparse パーサを構築する（#936）."""
    parser = argparse.ArgumentParser(
        prog="yt-distrokid-prepare",
        description="DistroKid 配信成果物 30-distrokid/ を準備する",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # plan
    p_plan = sub.add_parser("plan", help="disc 分割計画を draft spec.json に書き出す")
    p_plan.add_argument("collection", nargs="?", default=None, help="コレクションディレクトリ（省略時 CWD）")
    p_plan.add_argument("--discs", type=int, default=None, metavar="N", help="disc 数を手動指定")
    p_plan.add_argument(
        "--max-per-disc",
        type=int,
        default=_MAX_TRACKS_PER_DISC,
        dest="max_per_disc",
        metavar="N",
        help=f"1 disc の最大曲数（既定: {_MAX_TRACKS_PER_DISC}）",
    )
    p_plan.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="spec.json の出力先（既定: <collection>/30-distrokid/spec.json）",
    )

    # build
    p_build = sub.add_parser(
        "build",
        help="spec.json に従って mp3 コピー / metadata.md / README.md を生成する",
    )
    p_build.add_argument("collection", nargs="?", default=None, help="コレクションディレクトリ（省略時 CWD）")
    p_build.add_argument("--spec", required=True, metavar="PATH", help="spec.json のパス")
    p_build.add_argument("--force", action="store_true", help="既存 disc dir を上書きする")
    p_build.add_argument(
        "--release-date",
        default=None,
        dest="release_date",
        metavar="YYYY-MM-DD",
        help="リリース日（workflow-state.json に書き込む）",
    )

    # cover
    p_cover = sub.add_parser("cover", help="ジャケット画像を 3000×3000 JPEG に最終化する")
    p_cover.add_argument("collection", nargs="?", default=None, help="コレクションディレクトリ（省略時 CWD）")
    p_cover.add_argument("--input", required=True, metavar="PATH", help="入力画像パス")
    p_cover.add_argument("--force", action="store_true", help="既存 cover_art_3000.jpg を上書きする")
    p_cover.add_argument("--crop", action="store_true", help="非正方形画像を中央クロップして許容する")

    # verify
    p_verify = sub.add_parser("verify", help="生成成果物を読む側と同一コードパスで検証する")
    p_verify.add_argument("collection", nargs="?", default=None, help="コレクションディレクトリ（省略時 CWD）")

    return parser


def main() -> None:
    """yt-distrokid-prepare のエントリポイント（#936）."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "plan":
            _cmd_plan(args)
        elif args.command == "build":
            _cmd_build(args)
        elif args.command == "cover":
            _cmd_cover(args)
        elif args.command == "verify":
            _cmd_verify(args)
    except (ConfigError, ValidationError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
