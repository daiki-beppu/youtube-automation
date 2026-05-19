"""ボツ画像のストック化 (assets/stock/) コアユーティリティ。

`/thumbnail` / `/collection-ideate` で生成された不採用画像を
``<channel_dir>/assets/stock/<theme-slug>/`` 配下に隣接メタデータ付きで
退避し、将来別コレクションで再利用できるようにする。

レイアウト::

    <channel_dir>/assets/stock/
        <theme-slug>/
            YYYYMMDD-<src-hash>-<orig>.png
            YYYYMMDD-<src-hash>-<orig>.meta.json
            ...

``.meta.json`` の schema_version は ``STOCK_SCHEMA_VERSION``。

skill-config の ``image_generation.stock.enabled`` が ``False`` のとき、
``archive_to_stock()`` は退避せず元ファイルを ``unlink`` するだけ
(従来挙動への opt-out)。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.image_provider.composition import resolve_unique_path

_STOCK_REF_MIN_BYTES = 1024
_STOCK_REF_MAX_BYTES = 15 * 1024 * 1024

STOCK_SCHEMA_VERSION = 1
META_SUFFIX = ".meta.json"

SourceRole = Literal["thumbnail_candidate", "ideate_preview"]
SOURCE_ROLES: tuple[SourceRole, ...] = ("thumbnail_candidate", "ideate_preview")


@dataclass(frozen=True)
class StockEntry:
    """``assets/stock/<theme>/<image>`` 1 件分のエントリ。"""

    image_path: Path
    theme: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def meta_path(self) -> Path:
        return self.image_path.with_suffix(self.image_path.suffix + META_SUFFIX)

    @property
    def source_role(self) -> str | None:
        role = self.meta.get("source_role")
        return role if isinstance(role, str) else None

    @property
    def generated_at(self) -> str | None:
        ts = self.meta.get("generated_at") or self.meta.get("rejected_at")
        return ts if isinstance(ts, str) else None


def stock_dir(channel_dir: Path) -> Path:
    """``<channel_dir>/assets/stock/`` を返す (mkdir 込み)。"""

    path = channel_dir / "assets" / "stock"
    path.mkdir(parents=True, exist_ok=True)
    return path


def theme_dir(channel_dir: Path, theme: str) -> Path:
    """``<channel_dir>/assets/stock/<theme-slug>/`` を返す (mkdir 込み)。"""

    slug = slugify_theme(theme)
    if not slug:
        raise ValidationError("theme は空文字列ではいけません")
    path = stock_dir(channel_dir) / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify_theme(text: str) -> str:
    """テーマ文字列を kebab-case slug に正規化する。

    - 英数以外を ``-`` に置換
    - 連続する ``-`` を 1 つに圧縮
    - 前後の ``-`` を除去
    - 小文字化
    """

    if not text:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", text)
    normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
    return normalized


def _source_hash(source: str) -> str:
    """source 文字列 (元コレクションのディレクトリ名等) から 6 文字 hex を生成。"""

    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:6]


def _validate_role(role: str | None) -> None:
    if role is None:
        return
    if role not in SOURCE_ROLES:
        raise ValidationError(f"source_role は {list(SOURCE_ROLES)} のいずれかである必要があります: {role!r}")


def load_stock_config(skill_cfg: dict[str, Any]) -> dict[str, Any]:
    """skill-config から ``image_generation.stock`` セクションを安全に取り出す。

    network of nested dicts を 1 箇所で取り出すことで、CLI 側の
    ``_stock_enabled`` / ``_resolve_defaults`` のような重複アクセスを排除する。
    存在しなければ空 dict を返す。
    """

    image_gen = skill_cfg.get("image_generation") if isinstance(skill_cfg, dict) else None
    if not isinstance(image_gen, dict):
        return {}
    stock = image_gen.get("stock")
    return stock if isinstance(stock, dict) else {}


def archive_to_stock(
    image: Path,
    meta: dict[str, Any],
    *,
    channel_dir: Path,
    enabled: bool = True,
) -> Path | None:
    """画像 1 枚を ``assets/stock/<theme>/`` に move + meta.json 書き出し。

    ``enabled=False`` のときは退避せず ``image.unlink()`` だけ実施して
    ``None`` を返す (skill-config の opt-out フラグに対応)。

    Args:
        image: 退避元画像パス。
        meta: 隣接メタデータ。最低限 ``theme`` を含む必要がある。
              ``source_role`` が含まれる場合は ``_VALID_ROLES`` で検証される。
        channel_dir: チャンネルルート。
        enabled: ``False`` で退避を行わず unlink のみ。

    Returns:
        退避先の画像パス (``enabled=False`` のときは ``None``)。

    Raises:
        ValidationError: ``image`` が存在しない / ``theme`` 欠落 / 不正な role。
    """

    if not image.exists() or not image.is_file():
        raise ValidationError(f"退避対象の画像が見つかりません: {image}")

    if not enabled:
        image.unlink()
        return None

    theme = meta.get("theme")
    if not isinstance(theme, str) or not theme.strip():
        raise ValidationError("meta['theme'] は必須です (空文字不可)")
    _validate_role(meta.get("source_role"))

    target_dir = theme_dir(channel_dir, theme)

    source = meta.get("source_collection") or image.stem
    src_hash = _source_hash(str(source))
    now_local = datetime.now(timezone.utc).astimezone()
    timestamp = now_local.isoformat(timespec="seconds")
    base_name = f"{now_local.strftime('%Y%m%d')}-{src_hash}-{image.stem}{image.suffix}"
    dest_image = resolve_unique_path(target_dir / base_name)

    meta_to_write = dict(meta)
    meta_to_write.setdefault("schema_version", STOCK_SCHEMA_VERSION)
    meta_to_write["image"] = dest_image.name
    meta_to_write["theme"] = slugify_theme(theme)
    meta_to_write.setdefault("generated_at", timestamp)
    meta_to_write["rejected_at"] = timestamp

    image.rename(dest_image)
    dest_meta = dest_image.with_suffix(dest_image.suffix + META_SUFFIX)
    dest_meta.write_text(json.dumps(meta_to_write, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest_image


def load_stock_meta(image_path: Path) -> dict[str, Any] | None:
    """画像隣接の ``.meta.json`` を読み込む。存在しない / 壊れていれば ``None``。"""

    meta_path = image_path.with_suffix(image_path.suffix + META_SUFFIX)
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_stock(
    channel_dir: Path,
    *,
    theme: str | None = None,
    source_role: str | None = None,
    limit: int | None = None,
) -> list[StockEntry]:
    """``assets/stock/`` の画像エントリを列挙する (新しい順)。

    Args:
        channel_dir: チャンネルルート。
        theme: 指定時はそのテーマ slug のみ対象。
        source_role: ``thumbnail_candidate`` / ``ideate_preview`` でフィルタ。
        limit: 返却件数の上限 (新しい順)。

    Returns:
        ``StockEntry`` のリスト (mtime 降順)。
    """

    root = stock_dir(channel_dir)
    entries: list[StockEntry] = []

    if theme is not None:
        slug = slugify_theme(theme)
        theme_dirs = [root / slug] if (root / slug).is_dir() else []
    else:
        theme_dirs = sorted([p for p in root.iterdir() if p.is_dir()])

    for tdir in theme_dirs:
        for image in tdir.iterdir():
            if image.is_dir():
                continue
            if image.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            if image.name.endswith(META_SUFFIX):
                continue
            meta = load_stock_meta(image) or {}
            entry = StockEntry(image_path=image, theme=tdir.name, meta=meta)
            if source_role is not None and entry.source_role != source_role:
                continue
            entries.append(entry)

    entries.sort(key=lambda e: e.image_path.stat().st_mtime, reverse=True)
    if limit is not None and limit >= 0:
        return entries[:limit]
    return entries


def resolve_stock_refs(
    channel_dir: Path,
    *,
    stock_refs_config: dict[str, Any],
    theme: str | None,
    rng: random.Random | None = None,
) -> list[Path]:
    """skill-config の ``reference_images.stock`` 設定に従い stock から参照画像を解決する。

    PR-B (#364): ``/thumbnail`` / ``/collection-ideate`` の生成時に、過去退避された
    ボツ画像 (``assets/stock/<theme>/``) を ``reference_images.default`` の末尾に
    自動合成するための解決関数。

    Args:
        channel_dir: チャンネルルート。
        stock_refs_config: ``image_generation.<provider>.reference_images.stock``
            dict。期待キー: ``enabled`` / ``max_count`` / ``theme_match`` /
            ``source_role`` / ``shuffle`` / ``seed`` / ``fallback_when_empty``。
        theme: 現在のテーマ slug。``theme_match="exact"`` のとき必須。
        rng: shuffle 用 ``random.Random``。``None`` のとき内部で ``seed`` から生成。

    Returns:
        絶対 Path のリスト (最大 ``max_count`` 件、存在チェック + サイズフィルタ済み)。
        ``enabled=False`` または空 stock + ``fallback_when_empty=True`` のときは ``[]``。

    Raises:
        ValidationError:
            - ``theme_match="exact"`` なのに ``theme`` が ``None``
            - stock 0 件かつ ``fallback_when_empty=False``
            - ``source_role`` が ``SOURCE_ROLES`` 以外
    """

    if not isinstance(stock_refs_config, dict) or not stock_refs_config.get("enabled"):
        return []

    theme_match = stock_refs_config.get("theme_match", "exact")
    if theme_match == "exact" and not theme:
        raise ValidationError("reference_images.stock.theme_match='exact' のとき theme は必須です")

    source_role = stock_refs_config.get("source_role")
    _validate_role(source_role)

    entries = list_stock(
        channel_dir,
        theme=theme if theme_match == "exact" else None,
        source_role=source_role,
    )

    surviving: list[Path] = []
    for entry in entries:
        path = entry.image_path
        if not path.exists():
            print(f"[WARN] skip missing stock: {path}", file=sys.stderr)
            continue
        size = path.stat().st_size
        if size < _STOCK_REF_MIN_BYTES or size > _STOCK_REF_MAX_BYTES:
            print(f"[WARN] skip oversized/undersized stock: {path} ({size} bytes)", file=sys.stderr)
            continue
        surviving.append(path)

    if not surviving:
        if stock_refs_config.get("fallback_when_empty", True):
            return []
        raise ValidationError("reference_images.stock: 採用可能な stock が 0 件 (fallback_when_empty=False)")

    if stock_refs_config.get("shuffle"):
        shuffler = rng if rng is not None else random.Random(stock_refs_config.get("seed"))
        shuffler.shuffle(surviving)

    max_count = int(stock_refs_config.get("max_count", 3))
    selected = surviving[:max_count] if max_count > 0 else []

    role_label = source_role or "any"
    for path in selected:
        print(f"[INFO] stock 採用: {path} (theme={theme or '*'}, role={role_label})", file=sys.stderr)

    return selected


def prune_stock(
    channel_dir: Path,
    *,
    theme: str | None = None,
    retention_days: int | None = None,
    max_per_theme: int | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """古い stock を削除する。

    削除条件は OR 結合:
      - ``retention_days`` を超過した画像 (mtime 基準)
      - 各テーマで mtime 降順 ``max_per_theme`` を超過した分

    Args:
        channel_dir: チャンネルルート。
        theme: 指定時はそのテーマ slug のみ対象。
        retention_days: 保持日数。``None`` でスキップ。
        max_per_theme: テーマあたりの最大保持件数。``None`` でスキップ。
        dry_run: ``True`` で削除せずパスのみ返す。

    Returns:
        削除対象の画像パス (隣接 meta.json も同時に削除される)。
    """

    root = stock_dir(channel_dir)
    cutoff = datetime.now().timestamp() - retention_days * 86400 if retention_days is not None else None

    if theme is not None:
        slug = slugify_theme(theme)
        theme_dirs = [root / slug] if (root / slug).is_dir() else []
    else:
        theme_dirs = sorted(p for p in root.iterdir() if p.is_dir())

    to_delete: list[Path] = []

    for tdir in theme_dirs:
        with_mtime: list[tuple[Path, float]] = [
            (p, p.stat().st_mtime)
            for p in tdir.iterdir()
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"} and not p.name.endswith(META_SUFFIX)
        ]
        with_mtime.sort(key=lambda item: item[1], reverse=True)

        for index, (image, mtime) in enumerate(with_mtime):
            expired = cutoff is not None and mtime < cutoff
            overflow = max_per_theme is not None and index >= max_per_theme
            if expired or overflow:
                to_delete.append(image)

    if not dry_run:
        for image in to_delete:
            meta = image.with_suffix(image.suffix + META_SUFFIX)
            image.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)

    return to_delete
