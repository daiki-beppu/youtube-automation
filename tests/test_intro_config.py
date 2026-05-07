"""Issue #137: `.claude/skills/intro/config.default.yaml` のロード可能性 (A 節)。

upstream に新規追加される intro skill の config.default.yaml を
`load_skill_config("intro")` 経由でロードできること、設計 D の本質的な構造
(5 segments / 30s) と RJN サンプルとして load されるデフォルト値、
channel 上書きが deep-merge される運用を担保する。
"""

from __future__ import annotations

import pytest
import yaml

from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config

# 設計 D の本質的タイムライン (30s, 5 区間)
_EXPECTED_SEGMENT_BOUNDARIES = [0, 5, 10, 15, 25, 30]


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


# ---------- A-1: ロード可能性 + 主要キーの存在 ----------


def test_load_skill_config_intro_returns_dict_with_expected_keys() -> None:
    """Given upstream 同梱の intro/config.default.yaml
    When load_skill_config("intro") を呼ぶ
    Then segments / text / color / font / logo / droplet が dict として取れる。
    """
    cfg = skill_config.load_skill_config("intro", use_cache=False)

    expected_keys = {"segments", "text", "color", "font", "logo", "droplet"}
    missing = expected_keys - set(cfg.keys())
    assert not missing, f"intro/config.default.yaml に欠落しているキー: {missing}"


# ---------- A-2: 5 segments / v7.1 timeline ----------


def test_load_skill_config_intro_exposes_5_segments_with_v7_timeline() -> None:
    """Given intro config の `segments`
    When 値を確認
    Then 設計 D の 5 区間 (0/5/10/15/25/30s 境界) を持つ list である。
    """
    cfg = skill_config.load_skill_config("intro", use_cache=False)
    segments = cfg["segments"]
    assert isinstance(segments, list), f"segments が list でない: {type(segments)}"
    assert len(segments) == 5, f"segments 数が 5 でない: {len(segments)}"

    # 各 segment の start / end を抽出して timeline 境界を確認
    boundaries: list[int] = []
    for i, seg in enumerate(segments):
        assert isinstance(seg, dict), f"segments[{i}] が dict でない: {type(seg)}"
        assert "start" in seg, f"segments[{i}] に `start` キーが無い"
        assert "end" in seg, f"segments[{i}] に `end` キーが無い"
        boundaries.append(int(seg["start"]))
    boundaries.append(int(segments[-1]["end"]))
    assert boundaries == _EXPECTED_SEGMENT_BOUNDARIES, (
        f"timeline 境界が v7.1 と不一致: {boundaries} (expected {_EXPECTED_SEGMENT_BOUNDARIES})"
    )


# ---------- A-3: drawtext 色 #3A4A55 ----------


def test_load_skill_config_intro_exposes_drawtext_color_3a4a55() -> None:
    """Given intro config の `color`
    When drawtext 用カラーを確認
    Then dark teal `#3A4A55` (sammune-aligned) が default として記述されている。
    """
    cfg = skill_config.load_skill_config("intro", use_cache=False)
    color = cfg["color"]
    assert isinstance(color, dict), f"color が dict でない: {type(color)}"
    # 想定: drawtext or text or main などのキー名で hex 文字列を保持
    serialized = yaml.safe_dump(color)
    assert "3A4A55" in serialized.upper(), (
        f"`#3A4A55` (dark teal) が color block に無い:\n{serialized}"
    )


# ---------- A-4: channel override (font.en) ----------


def test_channel_override_replaces_font_en_via_deep_merge(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given channel override `config/skills/intro.yaml` で `font.en` のみ指定
    When load_skill_config("intro") を呼ぶ
    Then default の他キーは残り、`font.en` のみ Linux パスへ書き換わる。
    """
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "intro.yaml"
    linux_font = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
    override_path.write_text(
        yaml.safe_dump({"font": {"en": linux_font}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("intro", use_cache=False)
    font = cfg["font"]
    assert isinstance(font, dict), f"font が dict でない: {type(font)}"
    assert font.get("en") == linux_font, (
        f"font.en が override されていない: {font.get('en')!r}"
    )
    # default の他キー (font.ja 等) は残っているはず
    assert "ja" in font, f"font.ja が override で失われた: {font}"


# ---------- A-5: channel override (logo.heading_left の単一 text 行) ----------


def test_channel_override_replaces_single_text_line_via_deep_merge(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given channel override で `logo.heading_left` のみ指定
    When load_skill_config("intro") を呼ぶ
    Then RJN 固有 default ("Rain") を Sleep 等の別 channel ブランドへ
        差し替えできる (運用上の上書き経路担保)。
    """
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "intro.yaml"
    override_path.write_text(
        yaml.safe_dump({"logo": {"heading_left": "Sleep"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("intro", use_cache=False)
    logo = cfg["logo"]
    assert logo.get("heading_left") == "Sleep", (
        f"logo.heading_left が override されていない: {logo.get('heading_left')!r}"
    )
    # 同階層の他キー (heading_right / tagline 等) が override で消えていない
    other_keys = set(logo.keys()) - {"heading_left"}
    assert other_keys, f"logo の他キーが deep-merge で失われた: {logo}"
