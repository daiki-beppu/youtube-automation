"""scripts/discover_competitors.py の CLI / レポート出力ユニットテスト

Issue #114 で追加する `yt-discover-competitors` の引数解析・境界変換・出力フォーマットを検証する。

検証対象（plan.md §4.4 CLI / §6.2 テスト方針）:
1. _build_parser: 必須/任意引数、値の型、SystemExit
2. _build_params: argparse.Namespace → DiscoveryParams 変換と入力検証
3. _write_markdown: order.md の出力イメージに準拠したテーブル
4. _write_csv: 期待ヘッダ + データ行
5. main(): discover_competitors を mock した end-to-end（出力ディレクトリ自動作成、Markdown と CSV のペア出力）

YouTube API は touch しない（discover_competitors を mock）。
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts.discover_competitors import (
    _build_params,
    _build_parser,
    _format_count_compact,
    _write_csv,
    _write_markdown,
    main,
)
from youtube_automation.utils.competitor_scoring import (
    CandidateChannel,
    DiscoveryParams,
    ScoreBreakdown,
    ScoredCandidate,
)
from youtube_automation.utils.exceptions import ValidationError

# ----------------------------------------------------------------------------
# テストデータ
# ----------------------------------------------------------------------------


def _make_scored(
    *,
    channel_id: str = "UC_A",
    handle: str = "@channela",
    name: str = "Channel A",
    subscribers: int = 480_000,
    monthly_uploads: float = 8.0,
    avg_views: int = 120_000,
    score_total: float = 0.92,
    reason: str = "キーワード一致率高、最近の更新活発",
    topic_categories: tuple[str, ...] = (),
) -> ScoredCandidate:
    """テスト用の ScoredCandidate を組み立てる"""
    channel = CandidateChannel(
        channel_id=channel_id,
        handle=handle,
        name=name,
        subscribers=subscribers,
        total_videos=120,
        matched_keywords={"lo-fi"},
        recent_videos=[],
        last_posted_at=date.today() - timedelta(days=3),
        topic_categories=topic_categories,
    )
    breakdown = ScoreBreakdown(
        keyword_match=0.9,
        engagement=0.8,
        posting_cadence=0.7,
        subscriber_proximity=0.6,
        total=score_total,
    )
    return ScoredCandidate(
        channel=channel,
        monthly_uploads=monthly_uploads,
        avg_views=avg_views,
        score=breakdown,
        reason=reason,
    )


# ----------------------------------------------------------------------------
# _build_parser
# ----------------------------------------------------------------------------


class TestBuildParser:
    def test_required_keywords_missing_raises_systemexit(self):
        # Given: 必須引数 --keywords を省略
        parser = _build_parser()

        # When/Then
        with pytest.raises(SystemExit):
            parser.parse_args(["--output", "out.md"])

    def test_required_output_missing_raises_systemexit(self):
        # Given: 必須引数 --output を省略
        parser = _build_parser()

        # When/Then
        with pytest.raises(SystemExit):
            parser.parse_args(["--keywords", "lo-fi"])

    def test_minimal_required_arguments_parse(self):
        # Given: 必須のみ
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi study,chill beats", "--output", "research/x.md"])

        # Then
        assert args.keywords == "lo-fi study,chill beats"
        assert args.output == "research/x.md"

    def test_default_filter_values(self):
        # Given: デフォルト値の確認
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md"])

        # Then: plan.md §7.5 のデフォルト値
        assert args.min_subscribers == 0
        assert args.max_subscribers == 10_000_000
        assert args.posted_within_days == 30
        assert args.top == 20
        assert args.per_keyword == 20

    def test_explicit_filter_values_override_defaults(self):
        # Given: 全フラグ指定
        parser = _build_parser()

        # When
        args = parser.parse_args(
            [
                "--keywords",
                "lo-fi",
                "--min-subscribers",
                "10000",
                "--max-subscribers",
                "1000000",
                "--posted-within-days",
                "60",
                "--top",
                "5",
                "--per-keyword",
                "10",
                "--output",
                "out.md",
            ]
        )

        # Then
        assert args.min_subscribers == 10_000
        assert args.max_subscribers == 1_000_000
        assert args.posted_within_days == 60
        assert args.top == 5
        assert args.per_keyword == 10

    def test_verbose_flag(self):
        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md", "-v"])

        # Then
        assert args.verbose is True

    def test_require_music_topic_default_is_true(self):
        # Given: 主要ユースケース（音楽系発掘）に最適化された既定 ON（issue #120）
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md"])

        # Then: BooleanOptionalAction + default=True
        assert args.require_music_topic is True

    def test_require_music_topic_explicit_true(self):
        # Given: 明示 ON 指定
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md", "--require-music-topic"])

        # Then
        assert args.require_music_topic is True

    def test_no_require_music_topic_disables_filter(self):
        # Given: --no-require-music-topic で従来挙動（topic フィルタ無し）に戻す
        parser = _build_parser()

        # When
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md", "--no-require-music-topic"])

        # Then: 後方互換確保（issue #120 §効用）
        assert args.require_music_topic is False


# ----------------------------------------------------------------------------
# _build_params（境界での解決: argparse → DiscoveryParams）
# ----------------------------------------------------------------------------


class TestBuildParams:
    def _ns(self, **overrides):
        # 既定の Namespace を作って override する
        from argparse import Namespace

        defaults = dict(
            keywords="lo-fi study,chill beats,study music",
            min_subscribers=10_000,
            max_subscribers=1_000_000,
            posted_within_days=30,
            top=20,
            per_keyword=20,
            output="research/out.md",
            verbose=False,
            require_music_topic=True,
        )
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_keywords_split_on_comma_and_trimmed(self):
        # Given: スペース付きカンマ区切り
        args = self._ns(keywords="  lo-fi study , chill beats ,study music  ")

        # When
        params = _build_params(args)

        # Then: tuple、トリム済み、空要素なし
        assert isinstance(params, DiscoveryParams)
        assert params.keywords == ("lo-fi study", "chill beats", "study music")

    def test_empty_keywords_raises(self):
        # Given: 空文字
        args = self._ns(keywords="")

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_only_commas_raises(self):
        # Given: カンマだけで実質 0 要素
        args = self._ns(keywords=" , , ")

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_min_greater_than_max_raises(self):
        # Given: min > max
        args = self._ns(min_subscribers=2_000_000, max_subscribers=1_000_000)

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_negative_min_subscribers_raises(self):
        # Given: 負の min_subscribers（不整合な値のサイレントスキップ禁止）
        args = self._ns(min_subscribers=-1)

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_top_zero_raises(self):
        # Given: top=0 は意味がない
        args = self._ns(top=0)

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_posted_within_days_zero_or_negative_raises(self):
        # Given: posted_within_days <= 0
        args = self._ns(posted_within_days=0)

        # When/Then
        with pytest.raises(ValidationError):
            _build_params(args)

    def test_require_music_topic_true_flows_to_params(self):
        # Given: CLI で --require-music-topic 指定 → args.require_music_topic=True
        args = self._ns(require_music_topic=True)

        # When
        params = _build_params(args)

        # Then: 境界での解決原則に沿って args の値がそのまま DiscoveryParams に流れる
        assert params.require_music_topic is True

    def test_require_music_topic_false_flows_to_params(self):
        # Given: CLI で --no-require-music-topic 指定 → args.require_music_topic=False
        args = self._ns(require_music_topic=False)

        # When
        params = _build_params(args)

        # Then: 後方互換確保（topic フィルタ無し）
        assert params.require_music_topic is False


# ----------------------------------------------------------------------------
# _write_markdown
# ----------------------------------------------------------------------------


class TestWriteMarkdown:
    def test_writes_table_with_expected_header(self, tmp_path: Path):
        # Given: 1 件の ScoredCandidate
        scored = [_make_scored()]
        out = tmp_path / "research" / "out.md"
        params = DiscoveryParams(
            keywords=("lo-fi",),
            min_subscribers=10_000,
            max_subscribers=1_000_000,
            posted_within_days=30,
            top=20,
            per_keyword_results=20,
        )

        # When
        _write_markdown(scored, out, params)

        # Then: ファイルが作成され order.md の出力イメージに完全一致するヘッダを含む
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "| rank | channel | subscribers | uploads/月 | 平均再生数 | スコア | 候補理由 |" in content

    def test_renders_rank_starting_from_one(self, tmp_path: Path):
        # Given: 2 件
        scored = [
            _make_scored(channel_id="UC_A", name="Channel A", score_total=0.92),
            _make_scored(channel_id="UC_B", name="Channel B", score_total=0.87),
        ]
        out = tmp_path / "out.md"

        # When
        _write_markdown(scored, out, _make_params_for_render())

        # Then
        content = out.read_text(encoding="utf-8")
        # 1, 2 の rank が表中に出現する
        assert "| 1 |" in content
        assert "| 2 |" in content

    def test_creates_parent_directory_if_missing(self, tmp_path: Path):
        # Given: 親ディレクトリが存在しない
        out = tmp_path / "nested" / "deep" / "out.md"
        assert not out.parent.exists()

        # When
        _write_markdown([_make_scored()], out, _make_params_for_render())

        # Then: 自動作成され書き込みが成功
        assert out.exists()

    def test_score_formatted_with_two_decimals(self, tmp_path: Path):
        # Given
        scored = [_make_scored(score_total=0.876543)]
        out = tmp_path / "out.md"

        # When
        _write_markdown(scored, out, _make_params_for_render())

        # Then: 小数 2 桁
        content = out.read_text(encoding="utf-8")
        assert "0.88" in content

    def test_empty_results_writes_table_with_header_only(self, tmp_path: Path):
        # Given: 結果ゼロは正常終了で空レポート（plan.md §4.7）
        out = tmp_path / "empty.md"

        # When
        _write_markdown([], out, _make_params_for_render())

        # Then: ヘッダだけは出力される
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "| rank | channel | subscribers" in content


# ----------------------------------------------------------------------------
# _write_csv
# ----------------------------------------------------------------------------


_EXPECTED_CSV_COLUMNS = [
    "rank",
    "channel_id",
    "handle",
    "name",
    "subscribers",
    "monthly_uploads",
    "avg_views",
    "total_score",
    "score_keyword",
    "score_engagement",
    "score_posting",
    "score_subscriber",
    "reason",
    "channel_url",
]


class TestWriteCsv:
    def test_csv_header_matches_spec(self, tmp_path: Path):
        # Given: 1 件
        scored = [_make_scored()]
        out_csv = tmp_path / "out.csv"

        # When
        _write_csv(scored, out_csv, _make_params_for_render())

        # Then: ヘッダ列が plan.md §4.4 と一致
        with out_csv.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == _EXPECTED_CSV_COLUMNS

    def test_csv_row_count_matches_input(self, tmp_path: Path):
        # Given: 3 件
        scored = [_make_scored(channel_id=f"UC_{i}", name=f"Channel {i}") for i in range(3)]
        out_csv = tmp_path / "out.csv"

        # When
        _write_csv(scored, out_csv, _make_params_for_render())

        # Then: ヘッダ + 3 データ行
        with out_csv.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 4  # header + 3
        assert rows[0] == _EXPECTED_CSV_COLUMNS

    def test_csv_creates_parent_directory(self, tmp_path: Path):
        # Given: 親ディレクトリが存在しない
        out_csv = tmp_path / "nested" / "deep" / "out.csv"

        # When
        _write_csv([_make_scored()], out_csv, _make_params_for_render())

        # Then
        assert out_csv.exists()

    def test_csv_score_breakdown_columns_populated(self, tmp_path: Path):
        # Given
        scored = [_make_scored()]
        out_csv = tmp_path / "out.csv"

        # When
        _write_csv(scored, out_csv, _make_params_for_render())

        # Then: スコア内訳列に値が入っている
        with out_csv.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["score_keyword"]
        assert row["score_engagement"]
        assert row["score_posting"]
        assert row["score_subscriber"]
        # rank は 1 から
        assert row["rank"] == "1"


# ----------------------------------------------------------------------------
# main() の end-to-end（discover_competitors を mock）
# ----------------------------------------------------------------------------


class TestMain:
    def test_main_writes_markdown_and_csv(self, tmp_path: Path, monkeypatch):
        # Given: discover_competitors を 2 件返すように mock
        scored = [
            _make_scored(channel_id="UC_A", name="Channel A", score_total=0.92),
            _make_scored(channel_id="UC_B", name="Channel B", score_total=0.87),
        ]
        out_md = tmp_path / "research" / "competitors.md"

        argv = [
            "yt-discover-competitors",
            "--keywords",
            "lo-fi study,chill beats",
            "--min-subscribers",
            "10000",
            "--max-subscribers",
            "1000000",
            "--posted-within-days",
            "30",
            "--top",
            "5",
            "--output",
            str(out_md),
        ]
        monkeypatch.setattr("sys.argv", argv)

        with (
            patch(
                "youtube_automation.scripts.discover_competitors.discover_competitors",
                return_value=scored,
            ),
            patch(
                "youtube_automation.scripts.discover_competitors.get_youtube",
                return_value=MagicMock(),
            ),
        ):
            # When
            main()

        # Then: Markdown と CSV のペアが出力される
        assert out_md.exists()
        assert out_md.with_suffix(".csv").exists()

    def test_main_creates_output_dir_when_missing(self, tmp_path: Path, monkeypatch):
        # Given: 親ディレクトリ未作成
        out_md = tmp_path / "newdir" / "out.md"
        argv = [
            "yt-discover-competitors",
            "--keywords",
            "lo-fi",
            "--output",
            str(out_md),
        ]
        monkeypatch.setattr("sys.argv", argv)

        with (
            patch(
                "youtube_automation.scripts.discover_competitors.discover_competitors",
                return_value=[_make_scored()],
            ),
            patch(
                "youtube_automation.scripts.discover_competitors.get_youtube",
                return_value=MagicMock(),
            ),
        ):
            # When
            main()

        # Then
        assert out_md.parent.is_dir()
        assert out_md.exists()

    def test_main_with_empty_results_succeeds(self, tmp_path: Path, monkeypatch):
        # Given: 結果ゼロ（plan.md §4.7 = 警告ログ + 空レポート + 正常終了）
        out_md = tmp_path / "empty.md"
        argv = [
            "yt-discover-competitors",
            "--keywords",
            "no-such-niche",
            "--output",
            str(out_md),
        ]
        monkeypatch.setattr("sys.argv", argv)

        with (
            patch(
                "youtube_automation.scripts.discover_competitors.discover_competitors",
                return_value=[],
            ),
            patch(
                "youtube_automation.scripts.discover_competitors.get_youtube",
                return_value=MagicMock(),
            ),
        ):
            # When/Then: 例外を出さず正常終了する
            main()

        # Then: ファイル自体は生成される（空テーブル）
        assert out_md.exists()
        assert out_md.with_suffix(".csv").exists()


# ----------------------------------------------------------------------------
# _format_count_compact（K/M コンパクト整数表記、Markdown 列の presentation 層ヘルパー）
# ----------------------------------------------------------------------------


class TestFormatCountCompact:
    @pytest.mark.parametrize(
        "count, expected_substring",
        [
            (480_000, "K"),
            (1_200_000, "M"),
            (999, "999"),
        ],
    )
    def test_human_readable_format(self, count: int, expected_substring: str):
        # Given/When
        formatted = _format_count_compact(count)

        # Then: 期待される単位／数値が含まれる
        assert expected_substring in formatted

    def test_format_count_compact_does_not_leak_into_utils_layer(self):
        """family_tag=layering-violation 再発防止。

        K/M 表記への変換は presentation 層（CLI モジュール）の責務であり、
        ドメイン層 (`utils.competitor_discovery` / `utils.competitor_scoring`) からは
        公開されてはならない。leading underscore の関数を別モジュールから cross-module
        import するアンチパターンの再発を防ぐ。
        """
        from youtube_automation.utils import competitor_discovery, competitor_scoring

        assert not hasattr(competitor_discovery, "_format_count_compact")
        assert not hasattr(competitor_discovery, "format_count_compact")
        assert not hasattr(competitor_scoring, "_format_count_compact")
        assert not hasattr(competitor_scoring, "format_count_compact")


# ----------------------------------------------------------------------------
# 補助: 共通の DiscoveryParams 生成
# ----------------------------------------------------------------------------


def _make_params_for_render() -> DiscoveryParams:
    return DiscoveryParams(
        keywords=("lo-fi",),
        min_subscribers=10_000,
        max_subscribers=1_000_000,
        posted_within_days=30,
        top=20,
        per_keyword_results=20,
        require_music_topic=True,
    )


# ----------------------------------------------------------------------------
# skill-config 経由の CLI デフォルト値 (#1669)
# ----------------------------------------------------------------------------


class TestSkillConfigDefaults:
    """`config/skills/discover-competitors.yaml` の上書きが CLI 既定値に反映されること."""

    @pytest.fixture(autouse=True)
    def _reset_skill_config_cache(self):
        from youtube_automation.utils import skill_config

        skill_config.reset("discover-competitors")
        yield
        skill_config.reset("discover-competitors")

    def test_channel_override_changes_parser_defaults(self, tmp_path: Path, monkeypatch) -> None:
        channel = tmp_path / "ch"
        (channel / "config" / "skills").mkdir(parents=True)
        (channel / "config" / "skills" / "discover-competitors.yaml").write_text(
            "search:\n  min_subscribers: 5000\n  top: 10\n", encoding="utf-8"
        )
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        parser = _build_parser()
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md"])

        # Then: 上書きしたキーは override 値、未上書きキーは config.default.yaml の値
        assert args.min_subscribers == 5000
        assert args.top == 10
        assert args.max_subscribers == 10_000_000
        assert args.posted_within_days == 30
        assert args.per_keyword == 20

    def test_cli_flag_wins_over_channel_override(self, tmp_path: Path, monkeypatch) -> None:
        channel = tmp_path / "ch"
        (channel / "config" / "skills").mkdir(parents=True)
        (channel / "config" / "skills" / "discover-competitors.yaml").write_text(
            "search:\n  min_subscribers: 5000\n", encoding="utf-8"
        )
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        parser = _build_parser()
        args = parser.parse_args(["--keywords", "lo-fi", "--output", "out.md", "--min-subscribers", "777"])

        assert args.min_subscribers == 777
