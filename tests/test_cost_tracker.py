"""cost_tracker のユニットテスト。

Issue #132: ハードコード単価 (PRICING) 撤廃 + log_generation を metadata 記録のみに簡素化。

- 新規エントリの `estimated_cost_usd` は `None` 固定
- `unit=` は呼び出し側で必須 (未指定で `ValueError`)
- 撤廃 API (`PRICING` / `estimate_cost` / `unit_for` / `ModelPricing` /
  `get_jpy_per_usd` / `_format_usd`) はモジュールから消えていること
- 旧形式 (`estimated_cost_usd` が float 値 / `unit` キー欠落) は read 側で
  互換吸収して読めること
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils import cost_tracker


@pytest.fixture
def tmp_channel(tmp_path: Path, monkeypatch):
    """一時ディレクトリをチャンネルディレクトリとして使う。"""
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    (tmp_path / "config" / "channel").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "channel" / "meta.json").write_text(
        json.dumps(
            {
                "channel": {"name": "test", "slug": "test", "default_language": "ja"},
                "youtube_channel": {"id": "UC_TEST", "handle": "@test", "url": "https://youtube.com/@test"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "channel" / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "test"},
                "tags": {"base": []},
                "descriptions": {"short": "", "long": ""},
                "title": {"prefix": "", "suffix": ""},
            }
        ),
        encoding="utf-8",
    )
    from youtube_automation.utils.config import reset

    reset()
    yield tmp_path
    reset()


def _read_log(channel_dir: Path, filename: str) -> list[dict]:
    path = channel_dir / "data" / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================
# log_generation: 新スキーマ書き込み (Test #1-5)
# ============================================================


def test_log_generation_image_records_metadata_with_null_cost(tmp_channel: Path):
    """Given image カテゴリで log_generation
    When unit="image" + metadata を渡す
    Then estimated_cost_usd is None / unit="image" / metadata が保持される。
    """
    entry = cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        quantity=1,
        unit="image",
        metadata={"image_size": "2K", "aspect_ratio": "16:9"},
    )
    assert entry is not None
    assert entry["category"] == "image"
    assert entry["model"] == "gemini-3.1-flash-image-preview"
    assert entry["unit"] == "image"
    assert entry["estimated_cost_usd"] is None
    assert entry["metadata"]["image_size"] == "2K"

    entries = _read_log(tmp_channel, "image_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] is None
    assert entries[0]["unit"] == "image"


def test_log_generation_video_records_metadata_with_null_cost(tmp_channel: Path):
    """Given video カテゴリで log_generation
    When unit="second" + quantity=8 を渡す
    Then estimated_cost_usd is None / unit="second" / quantity==8 が記録される。
    """
    cost_tracker.log_generation(
        "video",
        model="veo-3.1-lite-generate-preview",
        quantity=8,
        unit="second",
        metadata={"duration_sec": 8, "resolution": "1080p"},
    )
    entries = _read_log(tmp_channel, "video_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] is None
    assert entries[0]["unit"] == "second"
    assert entries[0]["quantity"] == 8
    assert entries[0]["metadata"]["duration_sec"] == 8


def test_log_generation_audio_song_records_metadata_with_null_cost(tmp_channel: Path):
    """Given audio カテゴリで lyria-3-pro-preview (song 単位)
    When unit="song" を渡す
    Then estimated_cost_usd is None / unit="song" が記録される。
    """
    cost_tracker.log_generation(
        "audio",
        model="lyria-3-pro-preview",
        quantity=1,
        unit="song",
    )
    entries = _read_log(tmp_channel, "audio_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] is None
    assert entries[0]["unit"] == "song"


def test_log_generation_audio_30sec_records_metadata_with_null_cost(tmp_channel: Path):
    """Given audio カテゴリで lyria-3-clip-preview (30sec 単位)
    When unit="30sec" を渡す
    Then estimated_cost_usd is None / unit="30sec" が記録される。
    """
    cost_tracker.log_generation(
        "audio",
        model="lyria-3-clip-preview",
        quantity=1,
        unit="30sec",
    )
    entries = _read_log(tmp_channel, "audio_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] is None
    assert entries[0]["unit"] == "30sec"


def test_log_generation_gpt_image_2_keeps_image_size_metadata_without_cost(tmp_channel: Path):
    """Given gpt-image-2 + image_size="high"
    When log_generation を呼ぶ
    Then metadata.image_size は保持されるが estimated_cost_usd は None
        (PRICING by_size 参照経路の撤廃を検証)。
    """
    cost_tracker.log_generation(
        "image",
        model="gpt-image-2",
        quantity=1,
        unit="image",
        metadata={"image_size": "high", "aspect_ratio": "16:9"},
    )
    entries = _read_log(tmp_channel, "image_costs.json")
    assert len(entries) == 1
    assert entries[0]["model"] == "gpt-image-2"
    assert entries[0]["metadata"]["image_size"] == "high"
    assert entries[0]["estimated_cost_usd"] is None


# ============================================================
# log_generation: estimated_cost_usd is None リグレッション (Test #6)
# ============================================================


@pytest.mark.parametrize(
    "category, model, unit",
    [
        ("image", "gemini-3.1-flash-image-preview", "image"),
        ("video", "veo-3.1-lite-generate-preview", "second"),
        ("audio", "lyria-3-pro-preview", "song"),
    ],
)
def test_log_generation_estimated_cost_usd_is_always_none(
    tmp_channel: Path, category: str, model: str, unit: str
):
    """Given 全カテゴリ (image / video / audio)
    When log_generation で新規エントリを書く
    Then estimated_cost_usd は必ず None (要件 2 のリグレッション対策)。
    """
    entry = cost_tracker.log_generation(category, model=model, quantity=1, unit=unit)
    assert entry is not None
    assert entry["estimated_cost_usd"] is None


# ============================================================
# log_generation: 並列書き込み (Test #7)
# ============================================================


def test_log_generation_concurrent_writes_preserve_all_entries(tmp_channel: Path):
    """ThreadPoolExecutor 並列呼び出しで全エントリが欠落せずに記録されること。"""
    from concurrent.futures import ThreadPoolExecutor

    N = 20
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [
            ex.submit(
                cost_tracker.log_generation,
                "audio",
                model="lyria-3-pro-preview",
                quantity=1,
                unit="song",
                metadata={"idx": i},
            )
            for i in range(N)
        ]
        for f in futures:
            f.result()

    entries = _read_log(tmp_channel, "audio_costs.json")
    assert len(entries) == N
    indices = sorted(e["metadata"]["idx"] for e in entries)
    assert indices == list(range(N))


# ============================================================
# log_generation: unit 必須化 (Test #8-11)
# ============================================================


@pytest.mark.parametrize(
    "category, model",
    [
        ("image", "gemini-3.1-flash-image-preview"),
        ("video", "veo-3.1-lite-generate-preview"),
        ("audio", "lyria-3-pro-preview"),
    ],
)
def test_log_generation_rejects_missing_unit(tmp_channel: Path, category: str, model: str):
    """Given log_generation 呼び出し
    When unit= を渡さない
    Then ValueError (契約違反)。
    """
    with pytest.raises(ValueError, match="unit"):
        cost_tracker.log_generation(category, model=model, quantity=1)  # type: ignore[call-arg]


def test_log_generation_rejects_empty_unit(tmp_channel: Path):
    """Given log_generation 呼び出し
    When unit="" を渡す
    Then ValueError (fail-fast)。
    """
    with pytest.raises(ValueError, match="unit"):
        cost_tracker.log_generation(
            "image",
            model="gemini-3.1-flash-image-preview",
            quantity=1,
            unit="",
        )


# ============================================================
# read_all / read_log: 互換吸収 (Test #12-15)
# ============================================================


def test_read_all_combines_all_categories(tmp_channel: Path):
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        quantity=1,
        unit="image",
        metadata={"image_size": "1K"},
    )
    cost_tracker.log_generation(
        "video",
        model="veo-3.1-lite-generate-preview",
        quantity=8,
        unit="second",
    )
    cost_tracker.log_generation(
        "audio",
        model="lyria-3-pro-preview",
        quantity=1,
        unit="song",
    )
    entries = cost_tracker.read_all()
    cats = [e["category"] for e in entries]
    assert sorted(cats) == ["audio", "image", "video"]


def test_read_log_reads_legacy_float_estimated_cost_usd(tmp_channel: Path):
    """Given 旧形式 (estimated_cost_usd が float 数値) のエントリ
    When read_log で読み出す
    Then float 値はそのまま保持され例外にならない (後方互換)。
    """
    legacy_path = tmp_channel / "data" / "image_costs.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-04-01T10:00:00+00:00",
                    "category": "image",
                    "model": "gemini-3.1-flash-image-preview",
                    "quantity": 1,
                    "unit": "image",
                    "estimated_cost_usd": 0.04,
                    "metadata": {"image_size": "2K"},
                }
            ]
        ),
        encoding="utf-8",
    )
    entries = cost_tracker.read_log("image")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] == 0.04


def test_normalize_entry_video_legacy_falls_back_to_second(tmp_channel: Path):
    """Given video 旧エントリ (metadata なし / unit キー欠落)
    When read_log で正規化される
    Then unit が "second" にフォールバックされる (_LEGACY_UNIT_BY_CATEGORY)。
    """
    legacy_path = tmp_channel / "data" / "video_costs.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-03-01T10:00:00+00:00",
                    "model": "veo-3.1-lite-generate-preview",
                    "duration_sec": 8,
                    "estimated_cost_usd": 1.2,
                }
            ]
        ),
        encoding="utf-8",
    )
    entries = cost_tracker.read_log("video")
    assert len(entries) == 1
    assert entries[0]["category"] == "video"
    assert entries[0]["unit"] == "second"
    assert entries[0]["metadata"]["duration_sec"] == 8


def test_normalize_entry_audio_legacy_falls_back_to_song(tmp_channel: Path):
    """Given audio 旧エントリ (metadata なし / unit キー欠落)
    When read_log で正規化される
    Then unit が "song" にフォールバックされる。
    """
    legacy_path = tmp_channel / "data" / "audio_costs.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-03-01T10:00:00+00:00",
                    "model": "lyria-3-pro-preview",
                    "estimated_cost_usd": 0.08,
                }
            ]
        ),
        encoding="utf-8",
    )
    entries = cost_tracker.read_log("audio")
    assert len(entries) == 1
    assert entries[0]["category"] == "audio"
    assert entries[0]["unit"] == "song"


# ============================================================
# print_last_report / print_summary: USD/JPY 表示撤廃 (Test #16-20)
# ============================================================


def test_print_last_report_omits_usd_jpy(tmp_channel: Path, capsys):
    """Given log_generation で 1 件記録
    When print_last_report を呼ぶ
    Then 出力に「今回」「今月」「累計」を含むが、「¥」「$」「USD = ¥」を含まない。
        末尾に "GCP Cloud Console" の案内行が含まれる。
    """
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        quantity=1,
        unit="image",
        metadata={"image_size": "2K"},
    )
    capsys.readouterr()  # 直前の log 内 warn を流す
    cost_tracker.print_last_report()
    out = capsys.readouterr().out
    assert "今回" in out
    assert "今月" in out
    assert "累計" in out
    assert "¥" not in out
    assert "$" not in out
    assert "USD = ¥" not in out
    assert "GCP Cloud Console" in out


def test_print_summary_shows_monthly_counts_only(tmp_channel: Path, capsys):
    """Given 2026-03 と 2026-04 にまたがる 2 件
    When print_summary("image") を呼ぶ
    Then 月別ラベル ("2026-03" / "2026-04") と「件」を含むが、
        累積コスト / "¥" / "$" は含まない。
    """
    path = tmp_channel / "data" / "image_costs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-03-15T10:00:00+00:00",
                    "category": "image",
                    "model": "gemini-3.1-flash-image-preview",
                    "quantity": 1,
                    "unit": "image",
                    "estimated_cost_usd": None,
                    "metadata": {"image_size": "2K"},
                },
                {
                    "timestamp": "2026-04-10T10:00:00+00:00",
                    "category": "image",
                    "model": "gemini-3.1-flash-image-preview",
                    "quantity": 1,
                    "unit": "image",
                    "estimated_cost_usd": None,
                    "metadata": {"image_size": "2K"},
                },
            ]
        ),
        encoding="utf-8",
    )
    cost_tracker.print_summary("image")
    out = capsys.readouterr().out
    assert "2026-03" in out
    assert "2026-04" in out
    assert "件" in out
    assert "累積コスト" not in out
    assert "¥" not in out
    assert "$" not in out


def test_print_last_report_with_no_history_shows_placeholder(tmp_channel: Path, capsys):
    """Given 履歴ファイルが存在しない
    When print_last_report を呼ぶ
    Then 「履歴なし」表示で正常終了する。
    """
    cost_tracker.print_last_report()
    out = capsys.readouterr().out
    assert "履歴なし" in out


def test_print_summary_with_no_data_shows_placeholder(tmp_channel: Path, capsys):
    """Given カテゴリにデータがない
    When print_summary("image") を呼ぶ
    Then 「生成履歴がまだありません」表示で正常終了する。
    """
    cost_tracker.print_summary("image")
    out = capsys.readouterr().out
    assert "生成履歴がまだありません" in out


def test_print_last_report_with_null_cost_does_not_emit_dollar(tmp_channel: Path, capsys):
    """Given estimated_cost_usd=None のエントリ
    When print_last_report を呼ぶ
    Then 出力に "$" 表記が含まれない (USD 列の撤廃を緩く担保)。
    """
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        quantity=1,
        unit="image",
        metadata={"image_size": "2K"},
    )
    capsys.readouterr()
    cost_tracker.print_last_report()
    out = capsys.readouterr().out
    assert "$" not in out


# ============================================================
# 撤廃 API 不在 (Test #21-23)
# ============================================================


def test_cost_tracker_module_has_no_pricing_attribute():
    """Given cost_tracker モジュール
    When PRICING 属性を引く
    Then 存在しない (アンチパターン 1 リグレッション: 復活防止)。
    """
    assert not hasattr(cost_tracker, "PRICING")


@pytest.mark.parametrize(
    "name",
    ["estimate_cost", "unit_for", "ModelPricing", "get_jpy_per_usd", "_format_usd"],
)
def test_cost_tracker_module_has_no_obsolete_api(name: str):
    """Given cost_tracker モジュール
    When 撤廃対象 API を引く
    Then 存在しない (PRICING 依存 API + JPY 換算群の完全削除を担保)。
    """
    assert not hasattr(cost_tracker, name), f"{name} がモジュールに残存"


def test_log_generation_rejects_cost_usd_keyword(tmp_channel: Path):
    """Given log_generation 呼び出し
    When `cost_usd=` キーワード引数を渡す
    Then TypeError (deprecated 受理形式の再投入を防ぐ)。
    """
    with pytest.raises(TypeError, match="cost_usd"):
        cost_tracker.log_generation(
            "image",
            model="gemini-3.1-flash-image-preview",
            quantity=1,
            unit="image",
            cost_usd=0.04,  # type: ignore[call-arg]
            metadata={"image_size": "2K"},
        )


# ============================================================
# relative_to_channel_dir (維持) (旧 Test #24-25)
# ============================================================


def test_relative_to_channel_dir_inside(tmp_channel: Path):
    p = tmp_channel / "collections" / "foo" / "bar.png"
    assert cost_tracker.relative_to_channel_dir(p) == "collections/foo/bar.png"


def test_relative_to_channel_dir_outside(tmp_channel: Path, tmp_path: Path):
    outside = tmp_path.parent / "elsewhere" / "x.png"
    assert cost_tracker.relative_to_channel_dir(outside) == str(outside)
