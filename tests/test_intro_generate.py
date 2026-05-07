"""Issue #137: `.claude/skills/intro/references/generate_intro.py` (B 節)。

設計 D の filter graph 組み立て (`build_filter_complex`) と CLI (`main`) の
振る舞いを検証する。subprocess.run は mock し、ffmpeg は呼ばない。

config 駆動化のチェーン:
  load_skill_config("intro") -> SEGMENTS / FONT_EN / FONT_JA / drawtext color
  -> build_filter_complex(segments, text, font, color)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests._skill_loader import load_skill_script
from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ConfigError

# 設計 D の本質的タイムライン (30s, 5 区間)
_EXPECTED_SEGMENT_BOUNDARIES = [0, 5, 10, 15, 25, 30]
_EXPECTED_DURATION = 30
_EXPECTED_FPS = 24


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


@pytest.fixture
def intro_module():
    return load_skill_script("intro", "generate_intro")


def _make_segments(*, all_with_text: bool = False) -> list[dict]:
    """テスト用の標準 segments list (v7.1 通り)。"""
    base = [
        {"name": "01_rain_cu", "start": 0, "end": 5,
         "text_en": "Rest in the sound of rain.", "text_ja": "雨の音に、心を預ける。"},
        {"name": "02_lamp_steam", "start": 5, "end": 10,
         "text_en": "Tonight, your own hideaway.", "text_ja": "今夜は、あなただけの隠れ家で。"},
        {"name": "04_cinemagraph_a", "start": 10, "end": 15, "text_en": "", "text_ja": ""},
        {"name": "03_room_ws", "start": 15, "end": 25, "text_en": "", "text_ja": ""},
        {"name": "04_cinemagraph_b", "start": 25, "end": 30, "text_en": "", "text_ja": ""},
    ]
    if all_with_text:
        for s in base:
            s["text_en"] = s["text_en"] or "filler"
            s["text_ja"] = s["text_ja"] or "fillerJA"
    return base


def _make_font() -> dict:
    return {
        "en": "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "ja": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    }


def _make_color() -> dict:
    return {"drawtext": "#3A4A55", "droplet": "#3A4A55"}


def _make_logo() -> dict:
    return {
        "heading_left": "Rain",
        "heading_right": "Jazz Night",
        "tagline": "Your rainy night jazz bar escape",
    }


def _make_text() -> dict:
    return {
        "fontsize_en": 84,
        "fontsize_ja": 42,
        "fontsize_logo": 96,
        "fontsize_tagline": 32,
        "fade_seconds": 0.7,
        "shadow_color": "black@0.35",
        "shadow_x": 1,
        "shadow_y": 2,
    }


# ---------- B-1: concat=n=5 chain ----------


def test_build_filter_complex_concat_chain_has_5_inputs(
    intro_module, tmp_path: Path
) -> None:
    """Given 5 segments を渡す
    When build_filter_complex(segments, ...) を呼ぶ
    Then concat フィルタが `concat=n=5:v=1:a=0` を含む。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    assert "concat=n=5:v=1:a=0" in filter_str, (
        f"5 input concat が見つからない:\n{filter_str}"
    )


# ---------- B-2: drawtext は text 非空 segment のみに適用される ----------


def test_build_filter_complex_drawtext_only_for_text_nonempty_segments(
    intro_module, tmp_path: Path
) -> None:
    """Given segments の最初 2 つだけ text 持ち、残り 3 つは空
    When build_filter_complex を呼ぶ
    Then drawtext は text を持つ 2 segment 分 (EN+JA = 4 命令) のみ生成される
        (他 3 segment への drawtext は出ない)。
    """
    segments = _make_segments()
    filter_str, _ = intro_module.build_filter_complex(
        segments=segments,
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    # text 非空の segment 2 つから EN/JA で 4 つの drawtext 命令が出る
    # logo segment 用の drawtext (heading_left / heading_right / tagline) も別途出るため
    # 「text segment 由来」の drawtext のみカウントする目的で textfile= の出現箇所を検査
    assert filter_str.count("textfile=") >= 4, (
        f"text 非空 segment x 2 の drawtext (EN+JA) が出ていない:\n{filter_str}"
    )


# ---------- B-3: droplet PNG overlay 15-25s ----------


def test_build_filter_complex_droplet_overlay_active_15_to_25s(
    intro_module, tmp_path: Path
) -> None:
    """Given logo segment 15-25s
    When build_filter_complex を呼ぶ
    Then droplet PNG overlay が 15-25s 区間でのみ enable される。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    assert "overlay" in filter_str, "droplet PNG overlay フィルタが無い"
    # `enable='between(t,15,25)'` が overlay 句のいずれかに付与されているはず
    assert "between(t,15,25)" in filter_str, (
        f"droplet overlay の enable 区間 (15-25s) が見つからない:\n{filter_str}"
    )


# ---------- B-4: drawtext color が config 値で fontcolor=0x... に展開される ----------


def test_build_filter_complex_encodes_drawtext_color_from_config(
    intro_module, tmp_path: Path
) -> None:
    """Given color.drawtext = "#3A4A55"
    When build_filter_complex を呼ぶ
    Then `fontcolor=0x3A4A55` (大文字) が drawtext 句に含まれる。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color={"drawtext": "#3A4A55", "droplet": "#3A4A55"},
        logo=_make_logo(),
        tmp=tmp_path,
    )
    # ffmpeg は `0xRRGGBB` 形式を要求 (`#` プレフィックスは不可)
    assert "0x3A4A55" in filter_str.upper().replace("0X", "0x"), (
        f"drawtext fontcolor が config 値 (#3A4A55) を反映していない:\n{filter_str}"
    )


# ---------- B-5: text_en_*.txt / text_ja_*.txt が tmp に書かれる ----------


def test_build_filter_complex_writes_text_en_and_text_ja_files(
    intro_module, tmp_path: Path
) -> None:
    """Given build_filter_complex を呼ぶ
    Then text 非空 segment 用の text_en_*.txt / text_ja_*.txt が tmp に書かれる。
    """
    intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    en_files = list(tmp_path.glob("text_en_*.txt"))
    ja_files = list(tmp_path.glob("text_ja_*.txt"))
    assert len(en_files) >= 1, "text_en_*.txt が生成されていない"
    assert len(ja_files) >= 1, "text_ja_*.txt が生成されていない"


# ---------- B-6: y_offset が segment.start でセンター/上 1/3 に分岐 ----------


def test_build_filter_complex_y_offset_switches_at_5s_segment(
    intro_module, tmp_path: Path
) -> None:
    """Given 0-5s (mug 中心被り回避のため center) と 5-10s (upper-third)
    When build_filter_complex を呼ぶ
    Then y 式に center 系 (h-text_h)/2 と upper-third 系 (h/3) の両方が出現する。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    assert "(h-text_h)/2" in filter_str, "center 系 y 式が無い"
    assert "h/3" in filter_str, "upper-third 系 y 式が無い"


# ---------- B-7: alpha 式が segment 境界で 0.7s フェード ----------


def test_build_filter_complex_alpha_has_07_seconds_fade(
    intro_module, tmp_path: Path
) -> None:
    """Given segments に text 非空がある
    When build_filter_complex を呼ぶ
    Then alpha 式に 0.7s フェード ((t-start)/0.7) と end-out (max(0,(end-t)/0.7))
        の両端境界が現れる。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    # 0-5s segment のフェード: (t-0)/0.7 と (5-t)/0.7 が両方含まれる
    assert "/0.7" in filter_str, (
        f"alpha フェード (0.7s) が無い:\n{filter_str}"
    )


# ---------- B-8: logo heading が左右に分割され、中央 50px gap ----------


def test_build_filter_complex_logo_heading_split_with_50px_center_gap(
    intro_module, tmp_path: Path
) -> None:
    """Given logo segment (15-25s) で heading_left/heading_right + droplet PNG overlay
    When build_filter_complex を呼ぶ
    Then heading は左右 2 つの drawtext (中央から ±50px gap) に分割されている。
    """
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=_make_text(),
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    # 左 (heading_left): x = w/2 - 50 - text_w
    # 右 (heading_right): x = w/2 + 50
    assert "w/2-50-text_w" in filter_str, (
        f"heading_left (中央から左 50px) の x 式が無い:\n{filter_str}"
    )
    assert "w/2+50" in filter_str, (
        f"heading_right (中央から右 50px) の x 式が無い:\n{filter_str}"
    )


# ---------- B-9: 空 segments で ConfigError ----------


def test_build_filter_complex_raises_config_error_for_empty_segments(
    intro_module, tmp_path: Path
) -> None:
    """Given segments が空 list
    When build_filter_complex を呼ぶ
    Then ConfigError (`concat=n=0` を防ぐ early fail)。
    """
    with pytest.raises(ConfigError):
        intro_module.build_filter_complex(
            segments=[],
            text=_make_text(),
            font=_make_font(),
            color=_make_color(),
            logo=_make_logo(),
            tmp=tmp_path,
        )


# ---------- B-13: text config の override 値が drawtext fontsize に伝搬 ----------


def test_build_filter_complex_propagates_text_fontsize_overrides(
    intro_module, tmp_path: Path
) -> None:
    """Given text dict を override (fontsize_en=64 / fontsize_logo=80)
    When build_filter_complex を呼ぶ
    Then drawtext 句に `fontsize=64` (EN) と `fontsize=80` (logo) が反映される
        (channel が config/skills/intro.yaml で text.* を上書きできる証跡)。
    """
    text = _make_text()
    text["fontsize_en"] = 64
    text["fontsize_logo"] = 80
    filter_str, _ = intro_module.build_filter_complex(
        segments=_make_segments(),
        text=text,
        font=_make_font(),
        color=_make_color(),
        logo=_make_logo(),
        tmp=tmp_path,
    )
    assert "fontsize=64" in filter_str, (
        f"text.fontsize_en=64 (EN drawtext) が反映されていない:\n{filter_str}"
    )
    assert "fontsize=80" in filter_str, (
        f"text.fontsize_logo=80 (logo drawtext) が反映されていない:\n{filter_str}"
    )


# ---------- B-10: main() — input 不在時 stderr 出力 + exit 1 ----------


def test_main_lists_missing_inputs_and_exits_1_when_assets_absent(
    intro_module, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given branding/intro_assets/ が存在せず必要 mp4 もない repo
    When main() を実行
    Then stderr に missing inputs リストが出て exit code 1。
    """
    # repo 構造: config/channel/meta.json (resolve_repo_root の根拠) のみ
    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv", ["generate_intro", "--repo-root", str(repo)]
    )

    rc = intro_module.main()
    err = capsys.readouterr().err
    assert rc == 1, f"exit code が 1 でない: {rc}"
    assert "missing" in err.lower() or "見つかり" in err, (
        f"stderr に missing inputs の説明が無い:\n{err}"
    )


# ---------- B-11: main() — output 存在 + --force 無しでスキップ ----------


def test_main_skips_ffmpeg_when_output_exists_without_force(
    intro_module, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given branding/intro.mp4 が既に存在し、--force なし
    When main() を実行
    Then ffmpeg を呼ばずに rc=0 で抜ける。
    """
    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")
    (repo / "branding").mkdir()
    out_path = repo / "branding" / "intro.mp4"
    out_path.write_bytes(b"\x00")  # 既存

    monkeypatch.setattr(
        "sys.argv", ["generate_intro", "--repo-root", str(repo)]
    )

    with patch.object(intro_module.subprocess, "run") as mock_run:
        rc = intro_module.main()

    assert rc == 0
    mock_run.assert_not_called()


# ---------- B-12: main() — ffmpeg cmd に -r 24 と -an が含まれる ----------


def test_main_passes_r24_and_an_to_ffmpeg(
    intro_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given 全 input 揃った状態で main() を呼ぶ
    When ffmpeg subprocess を mock 観測
    Then cmd に `-r 24` と `-an` (audio なし、video-only) が含まれる。
    """
    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")
    intro_dir = repo / "branding" / "intro_assets"
    intro_dir.mkdir(parents=True)
    # 必要 input ファイルをすべて作る (空でも exists() チェックを通せばよい)
    for name in [
        "01_rain_cu_loop.mp4",
        "02_lamp_steam_loop.mp4",
        "04_cinemagraph_loop.mp4",
        "03_room_ws_loop.mp4",
        "05_droplet.png",
    ]:
        (intro_dir / name).write_bytes(b"\x00")

    monkeypatch.setattr(
        "sys.argv", ["generate_intro", "--repo-root", str(repo), "--force"]
    )

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    with patch.object(intro_module.subprocess, "run", side_effect=fake_run):
        rc = intro_module.main()

    assert rc == 0, f"main が成功しない: {rc}"
    cmd = captured.get("cmd")
    assert cmd is not None, "ffmpeg subprocess が呼ばれていない"
    assert "-r" in cmd, f"-r フラグが cmd に無い: {cmd}"
    r_idx = cmd.index("-r")
    assert cmd[r_idx + 1] == str(_EXPECTED_FPS), (
        f"-r 値が {_EXPECTED_FPS} でない: {cmd[r_idx + 1]}"
    )
    assert "-an" in cmd, f"`-an` (no audio) が cmd に無い (video-only でない): {cmd}"
    # 出力長 (-t) も 30s
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == str(_EXPECTED_DURATION)
