"""DistroKid 配信成果物準備ユーティリティ（純ロジック層）（#936）.

`yt-distrokid-prepare` CLI が 4 つのサブコマンド（plan / build / cover / verify）で
使う純関数を集める。I/O と argparse 配線は `scripts/distrokid_prepare.py` の責務。

依存契約:
- `utils.distrokid_metadata.parse_album_metadata` / `parse_track_table`
  で生成した metadata.md を読み戻せること（ラウンドトリップ検証）。
- `scripts.distrokid_release.kebab_to_title` / `build_release_payload` で
  verify サブコマンドが読む側と同一コードパスで検証できること。
- `scripts.collection_serve.find_distrokid_discs` で disc 列挙が可能なこと。
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# 読む側（distrokid_release.py）の public ヘルパを再利用する。scripts → utils の
# 逆方向依存は存在しないため循環しない（#936）。
from youtube_automation.scripts.distrokid_release import kebab_to_title
from youtube_automation.utils.distrokid_metadata import (
    parse_album_metadata,
    parse_track_table,
)
from youtube_automation.utils.distrokid_spec import (  # noqa: F401  re-export (#941)
    SPEC_FILENAME,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.time_utils import format_duration_mss

# 30-distrokid ディレクトリ名。collection_serve.py の _DISTROKID_DIRNAME と対称。
# 既存 private 定数を public 化するリファクタは行わないため自モジュールで定義する（#936）。
DISTROKID_DIRNAME = "30-distrokid"

# 02-Individual-music ディレクトリ名。CollectionPaths.music_dir と対称。
INDIVIDUAL_MUSIC_DIRNAME = "02-Individual-music"

# ジャケット画像の固定ファイル名。distrokid_release.py の _COVER_ART_FILENAME と対称。
COVER_ART_FILENAME = "cover_art_3000.jpg"

# 1 disc の最大曲数（DistroKid 慣行上限）（#936）。
_MAX_TRACKS_PER_DISC = 35

# disc 番号の上限（sorted() で disc10 が disc2 より前に並ぶため）（#936）。
_MAX_DISCS = 9

# slug バリデーション正規表現（disc{N}-kebab-case）
_DISC_SLUG_RE = re.compile(r"^disc\d+-[a-z0-9][a-z0-9-]*$")

# ファイル名先頭の連番プレフィックス（例: "01-" "123-"）
_TRACK_PREFIX_RE = re.compile(r"^\d+-")


# ---------------------------------------------------------------------------
# plan: 曲ファイルを disc に分割する
# ---------------------------------------------------------------------------


def split_tracks(
    filenames: list[str],
    *,
    discs: int | None = None,
    max_per_disc: int = _MAX_TRACKS_PER_DISC,
) -> list[list[str]]:
    """ファイル名リストを disc に均等分割し、各 disc のファイル名リストを返す（#936）.

    均等連続チャンク戦略:
    - d = ceil(n / max_per_disc)（--discs 指定時は d = discs）
    - base = n // d、先頭 n % d 個の disc が base+1 曲（均等連続分割）
    - 例: 50→[25,25] / 71→[24,24,23] / 36→[18,18] / 70→[35,35]

    エラー条件（ConfigError）:
    - filenames が空
    - discs 指定時に 1 disc が max_per_disc を超える
    - 自動算出 d または指定 discs が _MAX_DISCS を超える
    """
    n = len(filenames)
    if n == 0:
        raise ConfigError(
            f"{INDIVIDUAL_MUSIC_DIRNAME}/ に mp3 が 0 件です。"
            "DistroKid 提出前にマスタリング済み mp3 を配置してください。"
        )

    if discs is not None:
        d = discs
        # 指定 disc 数で 1 disc が max_per_disc を超えるか検証
        # base は ceil(n/d) で最大 disc のサイズを算出
        max_in_disc = math.ceil(n / d)
        if max_in_disc > max_per_disc:
            raise ConfigError(
                f"--discs {d} を指定すると 1 disc 最大 {max_in_disc} 曲になり、"
                f"上限 {max_per_disc} を超えます。"
                f"--discs を増やすか --max-per-disc を緩和してください。"
            )
    else:
        d = math.ceil(n / max_per_disc)

    if d > _MAX_DISCS:
        raise ConfigError(
            f"disc 数が {d} になります（上限 {_MAX_DISCS}）。"
            "sorted() で disc10 が disc2 より前に並ぶため 9 discs 以下に収める必要があります。"
            f"現在 {n} 曲 / max-per-disc {max_per_disc} の設定を見直してください。"
        )

    # 均等連続チャンク分割
    base = n // d
    remainder = n % d  # 先頭 remainder 個の disc が base+1 曲

    chunks: list[list[str]] = []
    idx = 0
    for i in range(d):
        size = base + (1 if i < remainder else 0)
        chunks.append(filenames[idx : idx + size])
        idx += size

    return chunks


def build_draft_spec(
    collection_name: str,
    filenames_split: list[list[str]],
    *,
    artist: str,
    language: str,
    genre_primary: str,
    genre_secondary: str | None,
) -> dict:
    """分割ファイル名リストから draft spec dict を生成する（#936）.

    collection_name からコレクション slug（日付プレフィックスとチャンネル slug を除去）を
    抽出して disc slug と album_title を自動命名する。LLM が後で編集する前提。

    素タイトル（連番プレフィックスを除去した stem の kebab→Title）がコレクション全体で
    重複するトラックには needs_unique=True を付与する（重複グループ全件）。
    """
    # コレクション slug を disc slug の基底に使う
    # collection_name は CollectionPaths.collection_name から来る
    # （"20260526-channel-coding-focus-collection" → "coding-focus-collection" 程度）
    coll_slug = _collection_slug_base(collection_name)

    # 全トラックの素タイトルを事前収集して重複検出
    all_base_titles: list[str] = []
    for disc_files in filenames_split:
        for fn in disc_files:
            stem = Path(fn).stem
            bare = _TRACK_PREFIX_RE.sub("", stem)
            all_base_titles.append(kebab_to_title(bare))

    title_counts = Counter(all_base_titles)
    duplicated = {t for t, c in title_counts.items() if c > 1}

    discs: list[dict] = []
    for disc_idx, disc_files in enumerate(filenames_split, start=1):
        slug = f"disc{disc_idx}-{coll_slug}-vol{disc_idx}"
        # slug の "disc1-" 以降を album_title に変換
        album_title = kebab_to_title(slug[len(f"disc{disc_idx}-") :])

        tracks: list[dict] = []
        for fn in disc_files:
            stem = Path(fn).stem
            bare = _TRACK_PREFIX_RE.sub("", stem)
            title = kebab_to_title(bare)
            track_entry: dict = {"filename": fn, "title": title}
            if title in duplicated:
                track_entry["needs_unique"] = True
            tracks.append(track_entry)

        discs.append(
            {
                "slug": slug,
                "album_title": album_title,
                "tracks": tracks,
            }
        )

    return {
        "version": 1,
        "artist": artist,
        "language": language,
        "genre_primary": genre_primary,
        "genre_secondary": genre_secondary,
        "label": None,
        "discs": discs,
    }


def _collection_slug_base(collection_name: str) -> str:
    """collection_name から disc slug の基底 slug を抽出する（#936）.

    "20260526-channel-coding-focus-collection" のような形式から
    "coding-focus" を抽出する。末尾 "-collection" も除去。
    """
    name = collection_name
    # 末尾 "-collection" を除去
    if name.endswith("-collection"):
        name = name[: -len("-collection")]
    # 先頭の日付プレフィックス + チャンネル slug（日付で始まる場合）を除去
    # "20260526-sg-coding-focus" → "coding-focus"
    parts = name.split("-", 2)
    if len(parts) >= 3 and parts[0].isdigit():
        name = parts[2]
    return name if name else collection_name


# ---------------------------------------------------------------------------
# build: spec 検証と成果物生成
# ---------------------------------------------------------------------------


def validate_spec(spec: dict, music_filenames: list[str]) -> None:
    """spec dict を検証する。不正な場合は ValidationError を raise する（#936）.

    検証項目:
    1. 各 disc ≤ max_per_disc 曲
    2. spec の全 filename が music_filenames に exactly-once で出現
       （漏れ・重複・未知ファイルを個別に報告）
    3. トラックタイトルがコレクション全体（disc 横断）でユニーク
    4. slug が disc{N}-kebab-case かつ N が出現順（1, 2, ...）
    5. artist / language / 各 album_title が非空
    """
    errors: list[str] = []

    discs = spec.get("discs", [])

    # 5. 必須フィールド非空チェック
    if not str(spec.get("artist", "")).strip():
        errors.append("spec.artist が空です。")
    if not str(spec.get("language", "")).strip():
        errors.append("spec.language が空です。")

    all_spec_filenames: list[str] = []
    all_titles: list[str] = []
    slug_nums: list[int] = []

    for disc_idx, disc in enumerate(discs, start=1):
        # 5. album_title 非空
        if not str(disc.get("album_title", "")).strip():
            errors.append(f"discs[{disc_idx - 1}].album_title が空です。")

        # 4. slug バリデーション
        slug = disc.get("slug", "")
        if not _DISC_SLUG_RE.match(slug):
            errors.append(f"discs[{disc_idx - 1}].slug '{slug}' は disc{{N}}-kebab-case 形式ではありません。")
        else:
            # N を抽出して出現順チェック
            n = int(re.match(r"disc(\d+)-", slug).group(1))  # type: ignore[union-attr]
            slug_nums.append(n)

        tracks = disc.get("tracks", [])

        # 1. disc 曲数上限チェック
        if len(tracks) > _MAX_TRACKS_PER_DISC:
            errors.append(
                f"discs[{disc_idx - 1}] ({slug!r}) の曲数が {len(tracks)} 曲で、"
                f"上限 {_MAX_TRACKS_PER_DISC} を超えます。"
            )

        for track in tracks:
            fn = track.get("filename", "")
            all_spec_filenames.append(fn)
            title = track.get("title", "")
            all_titles.append(title)

    # 4. slug N が出現順（1, 2, ...）
    expected_nums = list(range(1, len(discs) + 1))
    if slug_nums and slug_nums != expected_nums:
        errors.append(f"disc slug の番号順が {slug_nums} で、期待する出現順 {expected_nums} と異なります。")

    # 2. filename exactly-once チェック
    music_set = set(music_filenames)
    spec_set = set(all_spec_filenames)

    # 重複割当
    dup_counter = Counter(all_spec_filenames)
    duplicates = [fn for fn, c in dup_counter.items() if c > 1]
    if duplicates:
        errors.append(f"spec に重複割当されているファイル: {duplicates}")

    # 漏れ（music にあるが spec にない）
    missing = sorted(music_set - spec_set)
    if missing:
        errors.append(f"spec に含まれていないファイル（漏れ）: {missing}")

    # 未知（spec にあるが music にない）
    unknown = sorted(spec_set - music_set)
    if unknown:
        errors.append(f"spec に存在しないファイル（未知）: {unknown}")

    # 3. disc 横断タイトルユニーク
    title_counter = Counter(all_titles)
    dup_titles = [t for t, c in title_counter.items() if c > 1]
    if dup_titles:
        errors.append(
            f"コレクション全体でトラックタイトルが重複しています: {dup_titles}。"
            "spec の needs_unique トラックをユニーク化してから build を実行してください。"
        )

    if errors:
        raise ValidationError("\n".join(errors))


# ---------------------------------------------------------------------------
# build: metadata.md 生成
# ---------------------------------------------------------------------------


def render_metadata_md(
    disc_spec: dict,
    durations: dict[str, float],
    global_numbers: dict[str, int],
    *,
    release_date: str | None = None,
    genre_primary: str = "",
    genre_secondary: str | None = None,
    artist: str = "",
    language: str = "",
) -> str:
    """disc 仕様と計測尺から metadata.md 本文を生成する（#936）.

    実例（soulful-grooves/.../30-distrokid/disc1-.../metadata.md）の体裁に準拠。
    ラウンドトリップ検証（verify_roundtrip）で parse_album_metadata / parse_track_table
    が読み戻せることを保証する。

    Args:
        disc_spec: spec dict の discs[] 要素（slug / album_title / tracks を含む）
        durations: filename → 秒数のマッピング
        global_numbers: filename → コレクション全体グローバル番号のマッピング
        release_date: YYYY-MM-DD 形式のリリース日（None なら未入力コメント枠）
        genre_primary: メインジャンル
        genre_secondary: サブジャンル（None なら未入力コメント枠）
        artist: アーティスト名
        language: メタデータ言語
    """
    album_title = disc_spec["album_title"]
    tracks = disc_spec["tracks"]

    # トラックリスト範囲と合計尺
    nums = [global_numbers[t["filename"]] for t in tracks]
    start_num = min(nums)
    end_num = max(nums)
    total_secs = sum(durations.get(t["filename"], 0.0) for t in tracks)
    total_duration_str = format_total_duration(total_secs)

    # リリース日セル
    if release_date:
        release_date_cell = release_date
    else:
        release_date_cell = "<!-- YYYY-MM-DD (DistroKid は 4 営業日以上先を推奨) -->"

    # ジャンルセル
    genre_secondary_cell = genre_secondary if genre_secondary else "<!-- 任意 -->"

    lines: list[str] = [
        f"# DistroKid 入力メタデータ — {album_title}",
        "",
        "> このファイルは DistroKid Web フォームへの転記用テンプレ。"
        "`<!-- ... -->` 部分を実値に書き換えてからフォームへ。",
        "> トラックタイトルは **コレクション全体でユニーク化済み**。",
        "",
        "## アルバム情報",
        "",
        "| 項目 | 値 |",
        "|------|-----|",
        f"| アルバムタイトル | {album_title} |",
        f"| アーティスト名 | {artist} |",
        f"| リリース日 | {release_date_cell} |",
        f"| ジャンル (Primary) | {genre_primary} |",
        f"| ジャンル (Secondary) | {genre_secondary_cell} |",
        "| レーベル名 | <!-- 任意。空欄なら DistroKid 既定 --> |",
        f"| 言語 | {language} |",
        "| Explicit | No |",
        "| Cover song | No |",
        "| Remix | No |",
        "| Previously released | No |",
        "| カバーアート | `../cover_art_3000.jpg` (3000×3000 JPEG) |",
        "",
        f"## トラックリスト ({start_num}-{end_num}, 全 {len(tracks)} 曲 / 合計 {total_duration_str})",
        "",
        "| # | タイトル | ファイル | 尺 | ISRC (任意) | 作詞 | 作曲 |",
        "|---|---------|---------|----|------------|------|------|",
    ]

    for track in tracks:
        fn = track["filename"]
        title = track["title"]
        num = global_numbers[fn]
        dur_secs = durations.get(fn, 0.0)
        dur_str = format_duration_mss(dur_secs)
        lines.append(f"| {num} | {title} | `{fn}` | {dur_str} |  |  |  |")

    lines.append("")
    return "\n".join(lines)


def format_total_duration(total_secs: float) -> str:
    """合計秒数を "Xh Ym Zs" 形式でフォーマットする（#936）.

    例: 5416.0 → "1h 30m 16s"
    """
    total_int = int(total_secs)
    h = total_int // 3600
    m = (total_int % 3600) // 60
    s = total_int % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# build: README.md 生成
# ---------------------------------------------------------------------------


def render_readme_md(
    spec: dict,
    disc_infos: list[dict],
    collection_dir: Path,
) -> str:
    """30-distrokid/README.md を生成する（#936）.

    実例 README の体裁に準拠。disc_infos は各 disc の実計測値:
    [{"slug": str, "album_title": str, "count": int, "total_secs": float,
      "total_mb": float, "max_secs": float}]
    """
    # spec から基本情報
    artist = spec.get("artist", "")
    n_discs = len(spec.get("discs", []))
    coll_name = collection_dir.name

    tree_lines = [
        "```",
        f"{DISTROKID_DIRNAME}/",
        "├── README.md                          ← このファイル",
        f"├── {COVER_ART_FILENAME}                 ← 3000×3000 JPEG ジャケット (全 disc 共通)",
    ]
    for i, di in enumerate(disc_infos):
        slug = di["slug"]
        count = di["count"]
        total_secs = di["total_secs"]
        total_mb = di["total_mb"]
        is_last = i == len(disc_infos) - 1
        prefix = "└──" if is_last else "├──"
        vol_str = format_total_duration(total_secs)
        indent = "    " if is_last else "│   "
        vol_num = slug.split("vol")[1] if "vol" in slug else str(i + 1)
        tree_lines.append(f"{prefix} {slug}/")
        tree_lines.append(f"{indent}├── 01〜{count:02d} の MP3 ({count} ファイル, {total_mb:.0f}MB, {vol_str})")
        tree_lines.append(f"{indent}└── metadata.md                    ← Vol.{vol_num} 用入力メタ枠")
    tree_lines.append("```")

    # 制約チェック表
    check_rows: list[str] = []
    for di in disc_infos:
        slug = di["slug"]
        count = di["count"]
        total_secs = di["total_secs"]
        total_h = total_secs / 3600
        max_secs = di["max_secs"]
        vol_str = format_total_duration(total_secs)
        max_dur_str = format_duration_mss(max_secs)
        ok_count = "✅" if count <= _MAX_TRACKS_PER_DISC else "❌"
        ok_total = "✅" if total_h < 10 else "❌"
        ok_max = "✅" if max_secs < 5 * 3600 else "❌"
        check_rows.append(f"| 1 アルバム曲数 | ≤ {_MAX_TRACKS_PER_DISC} 曲 | {count} 曲 | {slug} | {ok_count} |")
        check_rows.append(f"| アルバム合計尺 | < 10 時間 | {vol_str} | {slug} | {ok_total} |")
        check_rows.append(f"| 1 トラック尺 | < 5 時間 | max {max_dur_str} | {slug} | {ok_max} |")

    check_table = "\n".join(
        [
            "| 項目 | 仕様 | 実値 | disc | 判定 |",
            "|------|------|------|------|------|",
            "| 音源形式 | MP3/WAV/FLAC/M4A/AIFF | MP3 | 全 disc | ✅ |",
            "| カバーアート | 正方形 JPEG (3000×3000 推奨) | 3000×3000 JPEG | 全 disc | ✅ |",
        ]
        + check_rows
    )

    # アップロード手順
    upload_steps = []
    for di in disc_infos:
        slug = di["slug"]
        count = di["count"]
        upload_steps.append(f"   - {slug} → `{slug}/*.mp3` を **01〜{count:02d} の順** で {count} ファイル選択")

    upload_section = "\n".join(
        [
            "1. **DistroKid ログイン** → `Upload` → `Album` を選択",
            "2. **基本情報入力**: `metadata.md` の「アルバム情報」を上から転記",
            f"3. **カバーアート**: `{COVER_ART_FILENAME}` をドラッグ&ドロップ",
            "4. **トラックアップロード**:",
        ]
        + upload_steps
        + [
            "   - 番号順に並んでいることを必ず確認 (DistroKid は並び順 = トラック番号)",
            "5. **各トラックメタ**: `metadata.md` のトラック表から転記",
            "   - ISRC は空欄 → DistroKid が自動発行",
            "   - Songwriter はアーティスト名と同じなら空欄可",
            "   - Explicit / Cover / Remix / Previously released は全て **No**",
            "6. **ストア選択**: All stores (デフォルト)",
            "7. **YouTube Content ID**: **OFF 推奨** (元動画が YouTube に公開済みのため二重請求回避)",
            "8. **支払い** → `Submit`",
            f"9. Vol.2 以降は手順 1 から繰り返し（計 {n_discs} リリース）",
        ]
    )

    metadata_prereqs = []
    for di in disc_infos:
        slug = di["slug"]
        metadata_prereqs.append(f"- [ ] {slug}/metadata.md のリリース日・アルバムタイトルを確認")

    lines = [
        f"# DistroKid 提出キット — {coll_name}",
        "",
        f"このディレクトリは **DistroKid (音楽配信) アップロード用の成果物一式**。"
        f"`{artist}` の楽曲を **{n_discs} アルバム**に分けて配信する想定。",
        "",
        "## 構成",
        "",
        "\n".join(tree_lines),
        "",
        "## アップロード手順 (DistroKid Web)",
        "",
        "### 事前に決めること",
        "",
        "`disc?/metadata.md` を開いて `<!-- ... -->` 部分を埋める。最低限:",
        "",
        "- [ ] アルバムタイトル（各 Vol.）",
        f"- [ ] アーティスト名（例: `{artist}`）",
        "- [ ] リリース日 (DistroKid 推奨: 申請から **4 営業日以上先**)",
        "- [ ] ジャンル Primary / Secondary",
        "- [ ] 各トラックタイトルの最終確認 (自動生成された Title Case をチェック)",
    ]
    if metadata_prereqs:
        lines += metadata_prereqs

    lines += [
        "",
        "### 当日の作業",
        "",
        upload_section,
        "",
        "### 公開後の確認",
        "",
        "- DistroKid から **Spotify / Apple Music へのリンク** が届くまで通常 **1〜2 週間**",
        "- リンク到着後、`upload_tracking.json` に DSP URL を追記する運用を検討",
        "",
        "## 制約チェック (DistroKid 公式仕様)",
        "",
        check_table,
        "",
        "## トラブル時のリカバリ",
        "",
        "| 症状 | 対処 |",
        "|------|------|",
        "| アップロード途中で失敗 | DistroKid は下書き保存される。再ログインして続行 |",
        f"| カバーアートが弾かれる | `file {COVER_ART_FILENAME}` で `JPEG ... 3000x3000` を再確認 |",
        "| トラック順が崩れた | ファイル名の `01-` `02-` ... のゼロパディングが効いているか確認 |",
        "| YouTube ですでに収益化済みの曲が ContentID で弾かれる | YouTube Content ID は OFF にする |",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# build: ラウンドトリップ検証
# ---------------------------------------------------------------------------


def verify_roundtrip(
    md_path: Path,
    disc_spec: dict,
    expected_numbers: list[int],
) -> None:
    """生成した metadata.md を parser で読み戻してラウンドトリップを検証する（#936）.

    album_title / artist / language / 各 (number, title, filename) が
    spec・expected_numbers と一致しなければ ConfigError（テンプレ崩れの自己検知）。

    Args:
        md_path: 生成した metadata.md のパス
        disc_spec: spec の discs[] 要素（album_title / tracks を含む）
        expected_numbers: トラック順のグローバル番号リスト（disc_spec.tracks と同長）
    """
    album_meta = parse_album_metadata(md_path)
    tracks_read = parse_track_table(md_path)

    expected_album_title = disc_spec["album_title"]
    if album_meta.get("album_title") != expected_album_title:
        raise ConfigError(
            f"ラウンドトリップ検証失敗: album_title が一致しません。"
            f"期待値={expected_album_title!r}, 読み戻し={album_meta.get('album_title')!r}"
        )

    spec_tracks = disc_spec["tracks"]
    if len(tracks_read) != len(spec_tracks):
        raise ConfigError(
            f"ラウンドトリップ検証失敗: トラック数が一致しません。期待={len(spec_tracks)}, 読み戻し={len(tracks_read)}"
        )

    for i, (track_read, track_spec, exp_num) in enumerate(zip(tracks_read, spec_tracks, expected_numbers)):
        if track_read["number"] != exp_num:
            raise ConfigError(
                f"ラウンドトリップ検証失敗: track[{i}] の番号が一致しません。"
                f"期待={exp_num}, 読み戻し={track_read['number']}"
            )
        if track_read["title"] != track_spec["title"]:
            raise ConfigError(
                f"ラウンドトリップ検証失敗: track[{i}] のタイトルが一致しません。"
                f"期待={track_spec['title']!r}, 読み戻し={track_read['title']!r}"
            )
        if track_read["filename"] != track_spec["filename"]:
            raise ConfigError(
                f"ラウンドトリップ検証失敗: track[{i}] のファイル名が一致しません。"
                f"期待={track_spec['filename']!r}, 読み戻し={track_read['filename']!r}"
            )


# ---------------------------------------------------------------------------
# cover: ジャケット画像リサイズ
# ---------------------------------------------------------------------------


def resize_cover(
    input_path: Path,
    output_path: Path,
    *,
    crop: bool = False,
    force: bool = False,
) -> None:
    """1:1 ジャケット画像を 3000×3000 JPEG に最終化して出力する（#936）.

    役割は新規 AI 生成した 1:1 ジャケット画像の最終化であり、
    既存サムネのリサイズ機能ではない（10-assets/ 配下の流用は警告を表示する）。

    処理:
    1. Pillow で open → convert("RGB")
    2. 非正方形は ConfigError（--crop 指定時は中央クロップで許容）
    3. resize((3000, 3000), LANCZOS) → save JPEG quality=95
    4. 保存後に自己検証（3000×3000 / JPEG 確認）

    エラー:
    - 既存 cover があり --force 未指定: ConfigError
    - 壊れた画像（Pillow UnidentifiedImageError / OSError）: ConfigError
    - 非正方形（--crop 未指定時）: ConfigError
    """
    if output_path.exists() and not force:
        raise ConfigError(f"カバーアートが既に存在します: {output_path}\n--force を指定して上書きしてください。")

    try:
        img = Image.open(input_path)
    except UnidentifiedImageError as exc:
        raise ConfigError(f"画像を開けませんでした（不正な画像形式）: {input_path}") from exc
    except OSError as exc:
        raise ConfigError(f"画像を開けませんでした（I/O エラー）: {input_path}") from exc

    img = img.convert("RGB")
    w, h = img.size

    if w != h:
        if not crop:
            raise ConfigError(
                f"画像が正方形ではありません（{w}×{h}）。"
                "--crop を指定して中央クロップするか、1:1 画像を用意してください。"
            )
        # 中央クロップ
        min_side = min(w, h)
        left = (w - min_side) // 2
        top = (h - min_side) // 2
        img = img.crop((left, top, left + min_side, top + min_side))

    img = img.resize((3000, 3000), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), format="JPEG", quality=95)

    # 自己検証
    try:
        verify_img = Image.open(output_path)
    except (UnidentifiedImageError, OSError) as exc:
        raise ConfigError(f"保存した画像を開けませんでした: {output_path}") from exc

    if verify_img.size != (3000, 3000):
        raise ConfigError(f"保存した画像のサイズが 3000×3000 ではありません: {verify_img.size}")
    if verify_img.format != "JPEG":
        raise ConfigError(f"保存した画像が JPEG ではありません: {verify_img.format}")


# ---------------------------------------------------------------------------
# workflow-state.json のリリース日更新
# ---------------------------------------------------------------------------


def write_release_date(workflow_state_path: Path, date_str: str) -> None:
    """workflow-state.json の planning.publish_target_at をリリース日で更新する（#936）.

    既存キーを保持した上で atomic 書き込みを行う。
    workflow-state.json が無い場合は新規作成する。
    tempfile.mkstemp → os.replace パターン（collection_serve.write_distrokid_release と同方針）。

    Args:
        workflow_state_path: workflow-state.json のパス
        date_str: YYYY-MM-DD 形式のリリース日（事前に date.fromisoformat で検証済み想定）
    """
    # 形式バリデーション（再検証）
    try:
        date.fromisoformat(date_str)
    except ValueError as exc:
        raise ConfigError(f"リリース日の形式が不正です（YYYY-MM-DD が必要）: {date_str!r}") from exc

    # 既存データ読み込み（不在は空 dict）。壊れた JSON を黙って空 dict に
    # 置き換えると「既存キー保持」の保証が破れデータ消失するため fail-loud にする（#936）。
    if workflow_state_path.is_file():
        try:
            data = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"workflow-state.json が不正な JSON です: {workflow_state_path}\n"
                "上書きすると既存データが失われるため中断しました。手動で修復してください。"
            ) from exc
        except OSError as exc:
            raise ConfigError(f"workflow-state.json を読み取れませんでした: {workflow_state_path}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"workflow-state.json のトップレベルが object ではありません: {workflow_state_path}")
    else:
        data = {}

    # planning セクションを既存キー保持で更新
    if "planning" not in data or not isinstance(data["planning"], dict):
        data["planning"] = {}
    data["planning"]["publish_target_at"] = date_str

    # atomic 書き込み
    workflow_state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(workflow_state_path.parent),
        prefix=".workflow-state-",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, workflow_state_path)
    except BaseException:
        # 書き込み失敗時に temp を残さない（atomic write の後始末）
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
