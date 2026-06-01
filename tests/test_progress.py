"""utils.progress の単体テスト（Issue #641）。

進捗フォーマット純粋関数（spinner / elapsed / ETA / 推定進捗率 /
1 行レンダラー / TTY 判定）の動作と境界値を担保する。
"""

from __future__ import annotations

import io

import pytest

from youtube_automation.utils import progress

# ---------- spinner_frame ----------


class TestSpinnerFrame:
    def test_first_frame(self) -> None:
        assert progress.spinner_frame(0) == progress.SPINNER_FRAMES[0]

    def test_wraps_around(self) -> None:
        n = len(progress.SPINNER_FRAMES)
        assert progress.spinner_frame(n) == progress.spinner_frame(0)
        assert progress.spinner_frame(n + 3) == progress.spinner_frame(3)

    def test_handles_negative_tick(self) -> None:
        # 負数は modulo で末尾に巻く（Python の % は数学的剰余）
        n = len(progress.SPINNER_FRAMES)
        assert progress.spinner_frame(-1) == progress.SPINNER_FRAMES[n - 1]


# ---------- format_elapsed ----------


class TestFormatElapsed:
    @pytest.mark.parametrize(
        "secs,expected",
        [
            (0, "0m00s"),
            (5, "0m05s"),
            (59, "0m59s"),
            (60, "1m00s"),
            (65, "1m05s"),
            (599, "9m59s"),
            (3600, "1h00m00s"),
            (3725, "1h02m05s"),
        ],
    )
    def test_formats_known_durations(self, secs: int, expected: str) -> None:
        assert progress.format_elapsed(secs) == expected

    def test_clamps_negative_to_zero(self) -> None:
        assert progress.format_elapsed(-5) == "0m00s"

    def test_accepts_float(self) -> None:
        # 小数部は切り捨て（int(seconds)）
        assert progress.format_elapsed(65.9) == "1m05s"


# ---------- format_eta ----------


class TestFormatEta:
    def test_none_renders_dashes(self) -> None:
        assert progress.format_eta(None) == "--"

    def test_zero_or_negative_renders_dashes(self) -> None:
        assert progress.format_eta(0) == "--"
        assert progress.format_eta(-3) == "--"

    @pytest.mark.parametrize(
        "secs,expected",
        [
            (1, "≈1s"),
            (45, "≈45s"),
            (59, "≈59s"),
            (60, "≈1m00s"),
            (125, "≈2m05s"),
        ],
    )
    def test_includes_approximation_prefix(self, secs: int, expected: str) -> None:
        assert progress.format_eta(secs) == expected

    def test_rounds_float(self) -> None:
        assert progress.format_eta(44.4) == "≈44s"
        assert progress.format_eta(44.6) == "≈45s"


# ---------- estimate_progress ----------


class TestEstimateProgress:
    def test_zero_elapsed_returns_zero(self) -> None:
        assert progress.estimate_progress(0, 60) == 0.0

    def test_midway(self) -> None:
        assert progress.estimate_progress(30, 60) == pytest.approx(0.5)

    def test_caps_at_99_percent_when_at_or_above_expected(self) -> None:
        # API 完了通知を待つ間に 100% と誤解させないため上限 0.99
        assert progress.estimate_progress(60, 60) == pytest.approx(0.99)
        assert progress.estimate_progress(120, 60) == pytest.approx(0.99)

    def test_expected_total_zero_returns_zero(self) -> None:
        assert progress.estimate_progress(10, 0) == 0.0
        assert progress.estimate_progress(10, -5) == 0.0

    def test_negative_elapsed_treated_as_zero(self) -> None:
        assert progress.estimate_progress(-5, 60) == 0.0


# ---------- estimate_eta ----------


class TestEstimateEta:
    def test_returns_remaining(self) -> None:
        assert progress.estimate_eta(0, 60) == 60.0
        assert progress.estimate_eta(30, 60) == 30.0

    def test_none_when_at_or_above_expected(self) -> None:
        assert progress.estimate_eta(60, 60) is None
        assert progress.estimate_eta(120, 60) is None

    def test_none_when_expected_total_zero(self) -> None:
        assert progress.estimate_eta(10, 0) is None
        assert progress.estimate_eta(10, -1) is None


# ---------- format_step ----------


class TestFormatStep:
    def test_basic(self) -> None:
        assert progress.format_step(1, 3, "Generating") == "[Step 1/3] Generating"

    def test_arbitrary_step_index(self) -> None:
        assert progress.format_step(2, 5, "Saving") == "[Step 2/5] Saving"


# ---------- is_tty ----------


class TestIsTty:
    def test_stringio_is_not_tty(self) -> None:
        # io.StringIO は isatty() を持つが False を返す
        assert progress.is_tty(io.StringIO()) is False

    def test_stream_without_isatty(self) -> None:
        # `object()` は isatty 属性を持たない
        assert progress.is_tty(object()) is False  # type: ignore[arg-type]

    def test_stream_whose_isatty_returns_true(self) -> None:
        class FakeTty:
            def isatty(self) -> bool:
                return True

        assert progress.is_tty(FakeTty()) is True  # type: ignore[arg-type]

    def test_stream_with_oserror_isatty(self) -> None:
        class BrokenStream:
            def isatty(self) -> bool:
                raise OSError("closed")

        # OSError は非 TTY 扱いで落ちない
        assert progress.is_tty(BrokenStream()) is False  # type: ignore[arg-type]


# ---------- render_progress_line ----------


class TestRenderProgressLine:
    def test_without_expected_total(self) -> None:
        line = progress.render_progress_line(label="Veo 動画生成中", elapsed=30, tick=0)
        # スピナー + ラベル + 経過時間
        assert line.startswith(progress.SPINNER_FRAMES[0])
        assert "Veo 動画生成中..." in line
        assert "0m30s" in line
        # expected_total なしのときは % / ETA は出さない
        assert "ETA" not in line
        assert "%" not in line

    def test_with_expected_total(self) -> None:
        line = progress.render_progress_line(label="Veo 動画生成中", elapsed=30, expected_total=60, tick=0)
        assert "0m30s" in line
        # 進捗率の頭に "≈" が付き、推定値である旨を明示している
        assert "≈50%" in line or "≈49%" in line or "≈51%" in line
        assert "ETA" in line

    def test_caps_progress_display_below_100(self) -> None:
        # expected_total 到達時でも 100% は表示しない（99% 上限）
        line = progress.render_progress_line(label="Veo 動画生成中", elapsed=120, expected_total=60, tick=0)
        assert "≈99%" in line
        # ETA は "--" にフォールバック
        assert "--" in line

    def test_tick_advances_spinner(self) -> None:
        line0 = progress.render_progress_line(label="x", elapsed=1, tick=0)
        line1 = progress.render_progress_line(label="x", elapsed=1, tick=1)
        assert line0[0] != line1[0]
