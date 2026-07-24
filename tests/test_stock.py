"""``utils.stock`` モジュールのユニットテスト。"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

import pytest

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.utils.stock import (
    META_SUFFIX,
    STOCK_SCHEMA_VERSION,
    StockEntry,
    archive_to_stock,
    list_stock,
    load_stock_meta,
    prune_stock,
    resolve_stock_refs,
    slugify_theme,
    stock_dir,
    theme_dir,
)


@pytest.fixture
def channel(tmp_path: Path) -> Path:
    return tmp_path / "channel"


def _make_image(path: Path, content: bytes = b"PNG") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---- slugify_theme --------------------------------------------------------


class TestSlugifyTheme:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Tavern", "tavern"),
            ("Jazz Bar", "jazz-bar"),
            ("midnight_LIBRARY", "midnight-library"),
            ("  Cozy  café  ", "cozy-caf"),
            ("---", ""),
            ("", ""),
        ],
    )
    def test_normalizes_to_kebab_case(self, raw: str, expected: str) -> None:
        assert slugify_theme(raw) == expected


# ---- stock_dir / theme_dir ------------------------------------------------


class TestStockDir:
    def test_creates_directory(self, channel: Path) -> None:
        path = stock_dir(channel)
        assert path == channel / "assets" / "stock"
        assert path.is_dir()

    def test_theme_dir_slugifies(self, channel: Path) -> None:
        path = theme_dir(channel, "Jazz Bar")
        assert path == channel / "assets" / "stock" / "jazz-bar"
        assert path.is_dir()

    def test_theme_dir_rejects_blank(self, channel: Path) -> None:
        with pytest.raises(ValidationError):
            theme_dir(channel, "   ---  ")


# ---- archive_to_stock -----------------------------------------------------


class TestArchiveToStock:
    def test_moves_image_and_writes_meta(self, channel: Path, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        dest = archive_to_stock(
            image,
            {
                "theme": "Tavern",
                "source_collection": "collections/planning/20260519-clm-tavern",
                "source_role": "thumbnail_candidate",
                "prompt": "warm candlelit interior",
                "provider": "gemini",
                "model": "gemini-3.1-flash-image-preview",
            },
            channel_dir=channel,
        )
        assert dest is not None
        assert dest.exists()
        assert dest.parent == channel / "assets" / "stock" / "tavern"
        assert not image.exists()

        meta_path = dest.with_suffix(dest.suffix + META_SUFFIX)
        assert meta_path.exists()

        meta = json.loads(meta_path.read_text())
        assert meta["schema_version"] == STOCK_SCHEMA_VERSION
        assert meta["theme"] == "tavern"
        assert meta["source_role"] == "thumbnail_candidate"
        assert meta["prompt"] == "warm candlelit interior"
        assert meta["image"] == dest.name
        assert "generated_at" in meta
        assert "rejected_at" in meta

    def test_filename_includes_date_and_hash(self, channel: Path, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        dest = archive_to_stock(
            image,
            {"theme": "tavern", "source_collection": "col-A"},
            channel_dir=channel,
        )
        assert dest is not None
        # YYYYMMDD-<6 hex>-<stem>.<ext>
        assert dest.suffix == ".jpg"
        date_part, src_hash, *_ = dest.stem.split("-")
        assert len(date_part) == 8 and date_part.isdigit()
        assert len(src_hash) == 6

    def test_enabled_false_unlinks_only(self, channel: Path, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        result = archive_to_stock(
            image,
            {"theme": "tavern"},
            channel_dir=channel,
            enabled=False,
        )
        assert result is None
        assert not image.exists()
        # stock ディレクトリは作られない (もしくは空)
        sd = channel / "assets" / "stock"
        if sd.exists():
            assert list(sd.rglob("*")) == [] or all(p.is_dir() for p in sd.rglob("*"))

    def test_missing_image_raises(self, channel: Path, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            archive_to_stock(
                tmp_path / "nope.jpg",
                {"theme": "tavern"},
                channel_dir=channel,
            )

    def test_missing_theme_raises(self, channel: Path, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        with pytest.raises(ValidationError):
            archive_to_stock(image, {}, channel_dir=channel)

    def test_invalid_role_raises(self, channel: Path, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        with pytest.raises(ValidationError):
            archive_to_stock(
                image,
                {"theme": "tavern", "source_role": "bogus"},
                channel_dir=channel,
            )

    def test_collision_auto_numbers(self, channel: Path, tmp_path: Path) -> None:
        # 同じ source_collection で同じ stem の画像を 2 回退避
        first = _make_image(tmp_path / "main-v1.jpg")
        archive_to_stock(
            first,
            {"theme": "tavern", "source_collection": "col"},
            channel_dir=channel,
        )

        second = _make_image(tmp_path / "main-v1.jpg")
        dest2 = archive_to_stock(
            second,
            {"theme": "tavern", "source_collection": "col"},
            channel_dir=channel,
        )
        assert dest2 is not None
        assert "-v2" in dest2.stem
        # tavern ディレクトリに 2 枚（画像）+ 2 つの meta.json があるはず
        files = sorted((channel / "assets" / "stock" / "tavern").iterdir())
        images = [f for f in files if not f.name.endswith(META_SUFFIX)]
        assert len(images) == 2


# ---- load_stock_meta ------------------------------------------------------


class TestLoadStockMeta:
    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "x.jpg")
        assert load_stock_meta(image) is None

    def test_returns_dict_when_present(self, tmp_path: Path) -> None:
        image = _make_image(tmp_path / "x.jpg")
        meta_path = image.with_suffix(image.suffix + META_SUFFIX)
        meta_path.write_text(json.dumps({"theme": "tavern"}))
        assert load_stock_meta(image) == {"theme": "tavern"}


# ---- list_stock -----------------------------------------------------------


class TestListStock:
    def _seed(self, channel: Path, tmp_path: Path) -> None:
        for idx, (theme, role) in enumerate(
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "ideate_preview"),
                ("library", "thumbnail_candidate"),
            ]
        ):
            image = _make_image(tmp_path / f"src-{idx}.jpg")
            archive_to_stock(
                image,
                {
                    "theme": theme,
                    "source_role": role,
                    "source_collection": f"col-{idx}",
                },
                channel_dir=channel,
            )
            # mtime が確実にずれるよう少し待つ
            time.sleep(0.01)

    def test_lists_all_themes(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel)
        assert len(entries) == 3
        themes = {e.theme for e in entries}
        assert themes == {"tavern", "library"}

    def test_theme_filter(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel, theme="tavern")
        assert all(e.theme == "tavern" for e in entries)
        assert len(entries) == 2

    def test_source_role_filter(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel, source_role="thumbnail_candidate")
        assert all(e.source_role == "thumbnail_candidate" for e in entries)
        assert len(entries) == 2

    def test_limit(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel, limit=1)
        assert len(entries) == 1

    def test_sorted_by_mtime_desc(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel)
        mtimes = [e.image_path.stat().st_mtime for e in entries]
        assert mtimes == sorted(mtimes, reverse=True)

    def test_stock_entry_helpers(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path)
        entries = list_stock(channel, theme="tavern")
        entry = entries[0]
        assert isinstance(entry, StockEntry)
        assert entry.meta_path.exists()
        assert entry.source_role in {"thumbnail_candidate", "ideate_preview"}
        assert entry.generated_at is not None


# ---- prune_stock ----------------------------------------------------------


class TestPruneStock:
    def _seed(self, channel: Path, tmp_path: Path, count: int = 5) -> list[Path]:
        targets: list[Path] = []
        for i in range(count):
            image = _make_image(tmp_path / f"src-{i}.jpg")
            dest = archive_to_stock(
                image,
                {"theme": "tavern", "source_collection": f"col-{i}"},
                channel_dir=channel,
            )
            assert dest is not None
            targets.append(dest)
            time.sleep(0.01)
        return targets

    def test_max_per_theme_keeps_newest(self, channel: Path, tmp_path: Path) -> None:
        self._seed(channel, tmp_path, count=5)
        deleted = prune_stock(channel, max_per_theme=2)
        # 削除されたものは存在しない
        assert all(not p.exists() for p in deleted)
        assert len(deleted) == 3

    def test_retention_days_filters_by_mtime(self, channel: Path, tmp_path: Path) -> None:
        archived = self._seed(channel, tmp_path, count=3)
        # 1 件目の mtime を 100 日前に巻き戻す
        old_target = archived[0]
        old_meta = old_target.with_suffix(old_target.suffix + META_SUFFIX)
        old_time = time.time() - 100 * 86400
        os.utime(old_target, (old_time, old_time))
        os.utime(old_meta, (old_time, old_time))

        deleted = prune_stock(channel, retention_days=30)
        assert old_target in deleted
        assert not old_target.exists()
        assert not old_meta.exists()
        # 新しい 2 件は残る
        for p in archived[1:]:
            assert p.exists()

    def test_dry_run_keeps_files(self, channel: Path, tmp_path: Path) -> None:
        archived = self._seed(channel, tmp_path, count=3)
        deleted = prune_stock(channel, max_per_theme=1, dry_run=True)
        assert len(deleted) == 2
        # dry-run なので実ファイルは残る
        for p in archived:
            assert p.exists()

    def test_theme_filter(self, channel: Path, tmp_path: Path) -> None:
        # tavern と library に複数件ずつ seed
        for theme in ("tavern", "library"):
            for i in range(3):
                image = _make_image(tmp_path / f"{theme}-{i}.jpg")
                archive_to_stock(
                    image,
                    {"theme": theme, "source_collection": f"col-{theme}-{i}"},
                    channel_dir=channel,
                )
                time.sleep(0.01)

        # tavern のみ枯らす
        deleted = prune_stock(channel, theme="tavern", max_per_theme=1)
        # 削除されたファイルはすべて tavern/ 配下
        assert all("/tavern/" in str(p) for p in deleted)
        # library は無傷
        library_remaining = list((channel / "assets" / "stock" / "library").glob("*.jpg"))
        assert len(library_remaining) == 3


# ---- resolve_stock_refs ---------------------------------------------------


def _seed_stock(
    channel: Path,
    tmp_path: Path,
    items: list[tuple[str, str]],
) -> list[Path]:
    """archive_to_stock 経由で stock を仕込む。

    items: [(theme, source_role), ...]。stock 参照テスト用に 2KB の本体を持たせる
    (resolve_stock_refs の min size 1024 バイトフィルタを通すため)。
    """

    archived: list[Path] = []
    for idx, (theme, role) in enumerate(items):
        image = _make_image(tmp_path / f"src-{idx}.jpg", content=b"P" * 2048)
        dest = archive_to_stock(
            image,
            {
                "theme": theme,
                "source_role": role,
                "source_collection": f"col-{idx}",
            },
            channel_dir=channel,
        )
        assert dest is not None
        archived.append(dest)
        time.sleep(0.01)
    return archived


class TestResolveStockRefs:
    def test_disabled_returns_empty(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(channel, tmp_path, [("tavern", "thumbnail_candidate")])
        result = resolve_stock_refs(
            channel,
            stock_refs_config={"enabled": False, "max_count": 3},
            theme="tavern",
        )
        assert result == []

    def test_missing_config_returns_empty(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(channel, tmp_path, [("tavern", "thumbnail_candidate")])
        assert resolve_stock_refs(channel, stock_refs_config={}, theme="tavern") == []

    def test_empty_stock_fallback_returns_empty(self, channel: Path) -> None:
        # stock 0 件 + fallback_when_empty=True (デフォルト)
        result = resolve_stock_refs(
            channel,
            stock_refs_config={"enabled": True, "max_count": 3, "theme_match": "exact"},
            theme="tavern",
        )
        assert result == []

    def test_empty_stock_strict_raises(self, channel: Path) -> None:
        with pytest.raises(ValidationError):
            resolve_stock_refs(
                channel,
                stock_refs_config={
                    "enabled": True,
                    "max_count": 3,
                    "theme_match": "exact",
                    "fallback_when_empty": False,
                },
                theme="tavern",
            )

    def test_exact_requires_theme(self, channel: Path) -> None:
        with pytest.raises(ValidationError):
            resolve_stock_refs(
                channel,
                stock_refs_config={"enabled": True, "theme_match": "exact"},
                theme=None,
            )

    def test_exact_filters_by_theme(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
                ("library", "thumbnail_candidate"),
                ("library", "thumbnail_candidate"),
            ],
        )
        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 10,
                "theme_match": "exact",
                "shuffle": False,
            },
            theme="tavern",
        )
        assert len(result) == 3
        assert all("/tavern/" in str(p) for p in result)

    def test_any_returns_all_themes_in_mtime_order(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("library", "thumbnail_candidate"),
                ("jazz-bar", "thumbnail_candidate"),
            ],
        )
        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 2,
                "theme_match": "any",
                "shuffle": False,
            },
            theme=None,
        )
        assert len(result) == 2
        # mtime 降順 = 最後に seed した jazz-bar が先頭
        assert "/jazz-bar/" in str(result[0])
        assert "/library/" in str(result[1])

    def test_source_role_filter(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "ideate_preview"),
                ("tavern", "thumbnail_candidate"),
            ],
        )
        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 10,
                "theme_match": "exact",
                "source_role": "thumbnail_candidate",
                "shuffle": False,
            },
            theme="tavern",
        )
        # ideate_preview 1 件が除外されて 2 件
        assert len(result) == 2
        for path in result:
            meta = load_stock_meta(path)
            assert meta is not None
            assert meta["source_role"] == "thumbnail_candidate"

    def test_invalid_source_role_raises(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(channel, tmp_path, [("tavern", "thumbnail_candidate")])
        with pytest.raises(ValidationError):
            resolve_stock_refs(
                channel,
                stock_refs_config={
                    "enabled": True,
                    "theme_match": "exact",
                    "source_role": "bogus",
                },
                theme="tavern",
            )

    def test_shuffle_with_seeded_rng_is_deterministic(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
            ],
        )
        cfg = {
            "enabled": True,
            "max_count": 4,
            "theme_match": "exact",
            "shuffle": True,
        }
        first = resolve_stock_refs(channel, stock_refs_config=cfg, theme="tavern", rng=random.Random(42))
        second = resolve_stock_refs(channel, stock_refs_config=cfg, theme="tavern", rng=random.Random(42))
        assert first == second

    def test_max_count_caps_results(self, channel: Path, tmp_path: Path) -> None:
        _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
            ],
        )
        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 10,
                "theme_match": "exact",
                "shuffle": False,
            },
            theme="tavern",
        )
        # max_count > stock 件数 でも実件数のみ返す
        assert len(result) == 3

    def test_unlinked_image_is_excluded(self, channel: Path, tmp_path: Path) -> None:
        archived = _seed_stock(
            channel,
            tmp_path,
            [
                ("tavern", "thumbnail_candidate"),
                ("tavern", "thumbnail_candidate"),
            ],
        )
        # 1 件を手動削除
        archived[0].unlink()
        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 10,
                "theme_match": "exact",
                "shuffle": False,
            },
            theme="tavern",
        )
        assert len(result) == 1
        assert archived[0] not in result

    def test_undersized_stock_is_skipped(self, channel: Path, tmp_path: Path) -> None:
        # 通常サイズの stock を 1 件
        _seed_stock(channel, tmp_path, [("tavern", "thumbnail_candidate")])
        # 小さすぎる stock を手動配置 (size filter で除外される想定)
        tiny_image = channel / "assets" / "stock" / "tavern" / "20990101-tiny-tiny.jpg"
        tiny_image.write_bytes(b"x")
        tiny_meta = tiny_image.with_suffix(tiny_image.suffix + META_SUFFIX)
        tiny_meta.write_text(
            json.dumps(
                {
                    "schema_version": STOCK_SCHEMA_VERSION,
                    "theme": "tavern",
                    "source_role": "thumbnail_candidate",
                    "image": tiny_image.name,
                }
            )
        )

        result = resolve_stock_refs(
            channel,
            stock_refs_config={
                "enabled": True,
                "max_count": 10,
                "theme_match": "exact",
                "shuffle": False,
            },
            theme="tavern",
        )
        assert tiny_image not in result
        assert len(result) == 1
