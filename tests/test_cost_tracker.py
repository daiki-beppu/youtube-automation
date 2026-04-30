"""cost_tracker のユニットテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture
def tmp_channel(tmp_path: Path, monkeypatch):
    """一時ディレクトリをチャンネルディレクトリとして使う。"""
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    (tmp_path / "config" / "channel").mkdir(parents=True, exist_ok=True)
    # 最小限の meta.json / content.json を用意してローダを満たす
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


def test_estimate_cost_image_by_size():
    assert cost_tracker.estimate_cost("gemini-3.1-flash-image-preview", image_size="1K") == 0.067
    assert cost_tracker.estimate_cost("gemini-3.1-flash-image-preview", image_size="2K") == 0.101
    assert cost_tracker.estimate_cost("gemini-3.1-flash-image-preview", image_size="4K") == 0.15


def test_estimate_cost_video_per_second():
    got = cost_tracker.estimate_cost("veo-3.1-lite-generate-preview", quantity=8)
    assert got == pytest.approx(0.15 * 8)


def test_estimate_cost_audio_per_song():
    assert cost_tracker.estimate_cost("lyria-3-pro-preview") == 0.08


def test_estimate_cost_unknown_model_returns_none():
    assert cost_tracker.estimate_cost("no-such-model") is None


def test_estimate_cost_image_without_size_raises():
    with pytest.raises(ConfigError):
        cost_tracker.estimate_cost("gemini-3.1-flash-image-preview")


# ---------- OpenAI gpt-image-* 系の登録（Issue #67） ----------


def test_estimate_cost_gpt_image_2_high_quality_is_021():
    """Given gpt-image-2 + quality=high
    When estimate_cost を呼ぶ
    Then 1 枚あたり $0.21（order.md 補足 "1024×1024 high 品質で約 $0.21/枚"）。
    """
    assert cost_tracker.estimate_cost("gpt-image-2", image_size="high") == 0.21


def test_pricing_gpt_image_2_registers_three_quality_levels():
    """Given cost_tracker.PRICING
    When gpt-image-2 を引く
    Then low / medium / high の 3 品質が登録されている。
    """
    pricing = cost_tracker.PRICING.get("gpt-image-2")
    assert pricing is not None, "gpt-image-2 が PRICING に未登録"
    assert pricing.unit == "image"
    assert pricing.by_size is not None
    assert {"low", "medium", "high"}.issubset(pricing.by_size.keys())


@pytest.mark.parametrize("model", ["gpt-image-1.5", "gpt-image-1-mini"])
def test_pricing_gpt_image_lower_tier_models_are_registered(model: str):
    """Given gpt-image-1.5 / gpt-image-1-mini
    When PRICING を引く
    Then エントリが存在し unit=image, by_size に low/medium/high が揃う。

    単価の厳密値は order.md に明示なし（参考リンク経由）のため、
    暫定値の存在のみ確認する。
    """
    pricing = cost_tracker.PRICING.get(model)
    assert pricing is not None, f"{model} が PRICING に未登録"
    assert pricing.unit == "image"
    assert pricing.by_size is not None
    assert {"low", "medium", "high"}.issubset(pricing.by_size.keys())


def test_log_generation_gpt_image_2_uses_quality_as_image_size_key(tmp_channel: Path):
    """Given gpt-image-2 を log_generation する
    When metadata.image_size に "high" を渡す
    Then PRICING の by_size["high"] = 0.21 で記録される。
    """
    cost_tracker.log_generation(
        "image",
        model="gpt-image-2",
        quantity=1,
        metadata={"image_size": "high", "aspect_ratio": "16:9"},
    )
    entries = _read_log(tmp_channel, "image_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] == 0.21
    assert entries[0]["model"] == "gpt-image-2"


def test_log_generation_image_writes_file(tmp_channel: Path):
    entry = cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        quantity=1,
        metadata={"image_size": "2K", "aspect_ratio": "16:9"},
    )
    assert entry is not None
    assert entry["estimated_cost_usd"] == 0.101
    assert entry["category"] == "image"
    assert entry["unit"] == "image"

    entries = _read_log(tmp_channel, "image_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] == 0.101


def test_log_generation_video_auto_calculates(tmp_channel: Path):
    cost_tracker.log_generation(
        "video",
        model="veo-3.1-lite-generate-preview",
        quantity=8,
        metadata={"duration_sec": 8},
    )
    entries = _read_log(tmp_channel, "video_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] == pytest.approx(0.15 * 8)
    assert entries[0]["unit"] == "second"


def test_log_generation_audio_per_song(tmp_channel: Path):
    cost_tracker.log_generation("audio", model="lyria-3-pro-preview", quantity=1)
    entries = _read_log(tmp_channel, "audio_costs.json")
    assert len(entries) == 1
    assert entries[0]["estimated_cost_usd"] == 0.08
    assert entries[0]["unit"] == "song"


def test_log_generation_custom_cost_overrides_pricing(tmp_channel: Path):
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        cost_usd=0.04,
        metadata={"image_size": "2K"},
    )
    entries = _read_log(tmp_channel, "image_costs.json")
    assert entries[0]["estimated_cost_usd"] == 0.04


def test_log_generation_unknown_model_writes_zero(tmp_channel: Path, capsys):
    cost_tracker.log_generation("audio", model="no-such-model")
    out = capsys.readouterr().out
    assert "価格が未登録" in out
    entries = _read_log(tmp_channel, "audio_costs.json")
    assert entries[0]["estimated_cost_usd"] == 0.0


def test_read_all_combines_all_categories(tmp_channel: Path):
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        metadata={"image_size": "1K"},
    )
    cost_tracker.log_generation("video", model="veo-3.1-lite-generate-preview", quantity=8)
    cost_tracker.log_generation("audio", model="lyria-3-pro-preview")
    entries = cost_tracker.read_all()
    cats = [e["category"] for e in entries]
    assert sorted(cats) == ["audio", "image", "video"]


def test_read_log_normalizes_legacy_entries(tmp_channel: Path):
    """metadata/category なしの旧形式を正規化して読めること。"""
    legacy_path = tmp_channel / "data" / "image_costs.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-04-01T10:00:00+00:00",
                    "model": "gemini-3.1-flash-image-preview",
                    "image_size": "2K",
                    "aspect_ratio": "16:9",
                    "reference_count": 0,
                    "estimated_cost_usd": 0.04,
                    "output_file": "foo.png",
                }
            ]
        ),
        encoding="utf-8",
    )
    entries = cost_tracker.read_log("image")
    assert len(entries) == 1
    assert entries[0]["category"] == "image"
    assert entries[0]["unit"] == "image"
    assert entries[0]["metadata"]["image_size"] == "2K"
    assert entries[0]["metadata"]["output_file"] == "foo.png"


def test_print_summary_monthly_breakdown(tmp_channel: Path, capsys):
    # 2026-03 と 2026-04 にまたがるエントリを手動投入
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
                    "estimated_cost_usd": 0.101,
                    "metadata": {"image_size": "2K"},
                },
                {
                    "timestamp": "2026-04-10T10:00:00+00:00",
                    "category": "image",
                    "model": "gemini-3.1-flash-image-preview",
                    "quantity": 1,
                    "unit": "image",
                    "estimated_cost_usd": 0.101,
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
    assert "累積コスト" in out


def test_print_last_report_includes_monthly(tmp_channel: Path, capsys):
    cost_tracker.log_generation(
        "image",
        model="gemini-3.1-flash-image-preview",
        metadata={"image_size": "2K"},
    )
    capsys.readouterr()  # 直前の log 内 warn を流す
    cost_tracker.print_last_report()
    out = capsys.readouterr().out
    assert "今回" in out
    assert "今月" in out
    assert "累計" in out
    assert "¥" in out  # 円併記
    assert "1 USD = ¥160" in out  # conftest で固定


def test_get_jpy_per_usd_env_override(monkeypatch):
    monkeypatch.setenv("JPY_PER_USD", "150.5")
    assert cost_tracker.get_jpy_per_usd() == 150.5


def test_get_jpy_per_usd_invalid_env_falls_back_to_network_or_default(monkeypatch, tmp_channel: Path):
    """env が不正値の場合、キャッシュ or fetch or フォールバックで float を返す。"""
    monkeypatch.setenv("JPY_PER_USD", "not-a-number")

    def _boom(*a, **kw):
        raise OSError("no net")

    monkeypatch.setattr(cost_tracker.urllib.request, "urlopen", _boom)
    got = cost_tracker.get_jpy_per_usd()
    assert got == cost_tracker.JPY_PER_USD_FALLBACK


def test_get_jpy_per_usd_uses_cache(tmp_channel: Path, monkeypatch):
    monkeypatch.delenv("JPY_PER_USD", raising=False)
    cache_path = tmp_channel / "data" / ".exchange_rate_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    import time as _time

    cache_path.write_text(
        json.dumps({"rate": 155.55, "fetched_at": _time.time()}),
        encoding="utf-8",
    )
    # キャッシュが新鮮なのでネットワークは呼ばれないはず（万一呼ばれたら失敗）
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1
        raise OSError("should not be called")

    monkeypatch.setattr(cost_tracker.urllib.request, "urlopen", _boom)
    assert cost_tracker.get_jpy_per_usd() == 155.55
    assert called["n"] == 0


def test_format_usd_includes_yen(monkeypatch):
    monkeypatch.setenv("JPY_PER_USD", "160")
    s = cost_tracker._format_usd(1.25)
    assert "$1.2500" in s
    assert "¥200" in s


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


def test_relative_to_channel_dir_inside(tmp_channel: Path):
    p = tmp_channel / "collections" / "foo" / "bar.png"
    assert cost_tracker.relative_to_channel_dir(p) == "collections/foo/bar.png"


def test_relative_to_channel_dir_outside(tmp_channel: Path, tmp_path: Path):
    outside = tmp_path.parent / "elsewhere" / "x.png"
    assert cost_tracker.relative_to_channel_dir(outside) == str(outside)
