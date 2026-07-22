"""scripts/bulk_update_descriptions_from_md.py のユニットテスト.

Issue #276 のリグレッションを担保する:
- `TARGETS` 定数（rjn 固定ハードコード）を排除し、`channel_dir()` 配下の
  `collections/live/*` を動的に解決して任意チャンネル（DF365 / rjn / 他）で
  `yt-bulk-update-desc` が機能する状態を保証する.

検証範囲:
- `discover_collections`: descriptions.md と upload_tracking.json が両方ある
  collection を sorted 順で返す。`channel_dir()` を呼び出しごとに再評価する.
- `main`: `--only` 起点が `discover_collections()` 戻り値に切り替わる.
  既存挙動（dry-run / sleep / UTF-16 100 units 境界 / nothing to do）の維持.
- `load_collection`: モジュールトップ `COLLECTIONS_DIR` 即時評価の解消.
- `extract_md_section`: 既存ユーティリティ.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.configuration import reset
from youtube_automation.utils.exceptions import YouTubeAPIError

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _setup_channel(tmp_path: Path) -> Path:
    """sample_channel をコピーした独立 channel dir を返す."""
    src = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
    dst = tmp_path / "channel"
    shutil.copytree(src, dst)
    return dst


def _make_collection_with_descriptions(
    ch: Path,
    name: str,
    *,
    video_id: str = "VID_DEFAULT",
    title: str = "テストタイトル",
    description: str = "本文",
    tags: list[str] | None = None,
    omit_descriptions: bool = False,
    omit_tracking: bool = False,
    omit_documentation: bool = False,
    omit_video_id: bool = False,
    omit_sections: list[str] | None = None,
) -> Path:
    """`live/<name>/20-documentation/{descriptions.md, upload_tracking.json}` を作成.

    欠落系（ケース 6/7/8/21/22/23）は `omit_*` フラグで variant 化する.
    """
    col = ch / "collections" / "live" / name
    col.mkdir(parents=True)

    if omit_documentation:
        return col

    doc = col / "20-documentation"
    doc.mkdir(parents=True)

    if not omit_tracking:
        cc: dict = {} if omit_video_id else {"video_id": video_id}
        (doc / "upload_tracking.json").write_text(
            json.dumps({"complete_collection": cc}),
            encoding="utf-8",
        )

    if not omit_descriptions:
        omits = set(omit_sections or [])
        sections: list[str] = []
        if "概要欄" not in omits:
            sections.append(f"## Complete Collection 概要欄\n\n```\n{description}\n```\n")
        if "タイトル案" not in omits:
            sections.append(f"## タイトル案\n\n```\n{title}\n```\n")
        if "タグ" not in omits:
            tags_str = ", ".join(tags or ["tag1", "tag2"])
            sections.append(f"## タグ（YouTube タグ欄）\n\n```\n{tags_str}\n```\n")
        (doc / "descriptions.md").write_text("\n".join(sections), encoding="utf-8")

    return col


def _build_youtube_mock(items: list[dict]) -> MagicMock:
    """videos().list().execute() が `items` を返す YouTube モック."""
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = {"items": items}
    yt.videos.return_value.update.return_value.execute.return_value = {"id": "ok"}
    return yt


def _snippet(video_id: str, title: str = "old title", description: str = "old desc") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "10",
            "defaultLanguage": "en",
        },
    }


# ---------------------------------------------------------------------------
# 1. discover_collections — 新規関数
# ---------------------------------------------------------------------------


class TestDiscoverCollections:
    """`collections/live/*` を走査し descriptions.md と upload_tracking.json が
    両方ある collection 名を sorted 順で返す."""

    def test_should_return_collection_when_descriptions_and_tracking_present(self, tmp_path, monkeypatch):
        """両ファイル揃った collection を検出する（plan 要件 #3 / #4）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "20260518-foo-collection")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert "20260518-foo-collection" in result

    def test_should_detect_non_rjn_channel_collection(self, tmp_path, monkeypatch):
        """**Issue #276 直接リグレッション**: rjn 以外の名前（DF365 等）でも検出される."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: DF365 系の命名（旧 TARGETS ハードコードでは絶対に拾えなかった）
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "20260518-df365-midnight-flow-state-collection")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert "20260518-df365-midnight-flow-state-collection" in result

    def test_should_return_sorted_order(self, tmp_path, monkeypatch):
        """戻り値は決定論的に sorted 順（plan 要件 #7）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 故意に登録順を入れ替えて作成
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "c-third")
        _make_collection_with_descriptions(ch, "a-first")
        _make_collection_with_descriptions(ch, "b-second")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert result == ["a-first", "b-second", "c-third"]

    def test_should_return_empty_when_live_directory_absent(self, tmp_path, monkeypatch):
        """`collections/live/` 不在時は `[]` を返す（`live_dir.exists()` ガード）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: collections/live を作らない
        ch = _setup_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert result == []

    def test_should_return_empty_when_live_directory_empty(self, tmp_path, monkeypatch):
        """`collections/live/` が空ディレクトリなら `[]` を返す."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 空 live/
        ch = _setup_channel(tmp_path)
        (ch / "collections" / "live").mkdir(parents=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert result == []

    def test_should_skip_collection_without_descriptions_md(self, tmp_path, monkeypatch):
        """descriptions.md 欠落 collection は silent skip（必要条件側）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "with-both")
        _make_collection_with_descriptions(ch, "no-descriptions", omit_descriptions=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert "with-both" in result
        assert "no-descriptions" not in result

    def test_should_skip_collection_without_upload_tracking_json(self, tmp_path, monkeypatch):
        """upload_tracking.json 欠落 collection は silent skip（必要条件側）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "with-both")
        _make_collection_with_descriptions(ch, "no-tracking", omit_tracking=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert "with-both" in result
        assert "no-tracking" not in result

    def test_should_skip_collection_without_documentation_directory(self, tmp_path, monkeypatch):
        """20-documentation/ ディレクトリごと欠落でも silent skip（両必須欠落エッジ）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "with-both")
        _make_collection_with_descriptions(ch, "no-documentation", omit_documentation=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.discover_collections()

        # Then
        assert "with-both" in result
        assert "no-documentation" not in result

    def test_should_reevaluate_channel_dir_on_each_call(self, tmp_path, monkeypatch):
        """`channel_dir()` を毎回再評価する（plan 暗黙要件 #8）.

        モジュールトップで COLLECTIONS_DIR を即時評価してしまうと別チャンネルに
        切り替えても古いパスが残り、テスト隔離 / マルチチャンネル運用が壊れる.
        """
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: ch_a には collection あり、ch_b には何もなし
        ch_a = _setup_channel(tmp_path / "a")
        _make_collection_with_descriptions(ch_a, "only-in-a")
        ch_b = _setup_channel(tmp_path / "b")

        # When/Then: ch_a 指定で検出される
        monkeypatch.setenv("CHANNEL_DIR", str(ch_a))
        reset()
        assert mod.discover_collections() == ["only-in-a"]

        # When/Then: ch_b に切り替えると検出されない（古いパスが残らない）
        monkeypatch.setenv("CHANNEL_DIR", str(ch_b))
        reset()
        assert mod.discover_collections() == []


# ---------------------------------------------------------------------------
# 2. main — `--only` 起点切り替え
# ---------------------------------------------------------------------------


class TestMainTargetSelection:
    """`main()` の対象選定が `discover_collections()` 起点に切り替わる."""

    def test_should_process_all_discovered_when_only_omitted(self, tmp_path, monkeypatch):
        """`--only` 省略時は検出済み全 collection を処理（plan 要件 #3）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 2 つの collection、両方とも有効
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        _make_collection_with_descriptions(ch, "beta", video_id="V_BETA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        yt_mock = _build_youtube_mock([_snippet("V_ALPHA"), _snippet("V_BETA")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then: 2 件分の update().execute() が呼ばれる
            assert yt_mock.videos.return_value.update.return_value.execute.call_count == 2

    def test_should_filter_by_substring_when_only_given(self, tmp_path, monkeypatch):
        """`--only <substr>` で substring 一致した collection のみ処理（plan 要件 #2）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 3 つの collection
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "20260518-target-x", video_id="V_TARGET")
        _make_collection_with_descriptions(ch, "20260518-other-a", video_id="V_OTHER_A")
        _make_collection_with_descriptions(ch, "20260518-other-b", video_id="V_OTHER_B")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--only", "target"])
        yt_mock = _build_youtube_mock([_snippet("V_TARGET")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then: 1 件のみ処理（V_TARGET）
            update_calls = yt_mock.videos.return_value.update.return_value.execute.call_args_list
            assert len(update_calls) == 1
            # videos().list() に渡される id も V_TARGET 単独
            list_calls = yt_mock.videos.return_value.list.call_args_list
            assert list_calls[0].kwargs["id"] == "V_TARGET"

    def test_should_treat_comma_separated_only_as_or_filter(self, tmp_path, monkeypatch):
        """`--only foo,bar` の comma-split で OR 一致（既存挙動の維持）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha-foo-x", video_id="V_FOO")
        _make_collection_with_descriptions(ch, "beta-bar-y", video_id="V_BAR")
        _make_collection_with_descriptions(ch, "gamma-baz-z", video_id="V_BAZ")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--only", "foo,bar"])
        yt_mock = _build_youtube_mock([_snippet("V_FOO"), _snippet("V_BAR")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then: foo / bar 2 件は処理、baz は除外
            list_calls = yt_mock.videos.return_value.list.call_args_list
            ids_passed = list_calls[0].kwargs["id"]
            assert "V_FOO" in ids_passed
            assert "V_BAR" in ids_passed
            assert "V_BAZ" not in ids_passed

    def test_should_detect_df365_midnight_flow_state_via_only(self, tmp_path, monkeypatch):
        """**Issue #276 直接リグレッション**: DF365 collection が `--only midnight-flow-state` で対象化される.

        旧実装では `TARGETS` ハードコードに含まれず `nothing to do` で終わっていた.
        """
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: DF365 標準命名
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(
            ch,
            "20260515-df365-midnight-flow-state-collection",
            video_id="V_MIDNIGHT",
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--only", "midnight-flow-state"])
        yt_mock = _build_youtube_mock([_snippet("V_MIDNIGHT")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then: API が呼ばれる（"nothing to do" で早期 return しない）
            assert yt_mock.videos.return_value.update.return_value.execute.call_count == 1

    def test_should_log_nothing_to_do_when_no_collections_discovered(self, tmp_path, monkeypatch, caplog):
        """検出 0 件で `"nothing to do"` をログ出力し API を呼ばない."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: live/ なし
        ch = _setup_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)

        with patch.object(mod, "get_youtube") as gy:
            # When
            mod.main()

            # Then
            assert ("INFO", "nothing to do") in [(record.levelname, record.message) for record in caplog.records]
            gy.assert_not_called()

    def test_should_log_nothing_to_do_when_only_matches_nothing(self, tmp_path, monkeypatch, caplog):
        """`--only` ミスマッチで対象 0 件になった場合もログ出力し API 未呼出."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: collection は存在するが --only は別 substring
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--only", "nonexistent"])
        caplog.set_level(logging.INFO, logger=mod.__name__)

        with patch.object(mod, "get_youtube") as gy:
            # When
            mod.main()

            # Then
            assert ("INFO", "nothing to do") in [(record.levelname, record.message) for record in caplog.records]
            gy.assert_not_called()

    def test_console_entrypoint_should_emit_info_logs_to_stderr_without_logger_injection(self, tmp_path):
        """実 console script は logger 設定の手注入なしで INFO を stderr に出す."""
        ch = _setup_channel(tmp_path)
        entrypoint = Path(sys.executable).with_name("yt-bulk-update-desc")
        project_src = Path(__file__).resolve().parents[1] / "src"
        assert entrypoint.is_file()

        result = subprocess.run(
            [entrypoint],
            env={
                **os.environ,
                "CHANNEL_DIR": str(ch),
                "PYTHONPATH": os.pathsep.join(filter(None, (str(project_src), os.environ.get("PYTHONPATH")))),
            },
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == "INFO: nothing to do\n"


# ---------------------------------------------------------------------------
# 3. main — 既存挙動の維持（リグレッションガード）
# ---------------------------------------------------------------------------


class TestMainExecution:
    """既存挙動（execute / dry-run / sleep / UTF-16 100 units 境界）の維持."""

    def test_should_call_videos_update_execute_per_collection(self, tmp_path, monkeypatch, caplog):
        """通常実行で `videos().update().execute()` が collection 数分呼ばれる."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 3 件
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "a", video_id="V1")
        _make_collection_with_descriptions(ch, "b", video_id="V2")
        _make_collection_with_descriptions(ch, "c", video_id="V3")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([_snippet("V1"), _snippet("V2"), _snippet("V3")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then
            assert yt_mock.videos.return_value.update.return_value.execute.call_count == 3
            video_calls = yt_mock.videos.return_value.mock_calls
            list_execute_indices = [
                index for index, mock_call in enumerate(video_calls) if mock_call[0] == "list().execute"
            ]
            update_execute_indices = [
                index for index, mock_call in enumerate(video_calls) if mock_call[0] == "update().execute"
            ]
            assert len(list_execute_indices) == 1
            assert len(update_execute_indices) == 3
            assert max(list_execute_indices) < min(update_execute_indices)
            messages = [record.message for record in caplog.records]
            assert messages.count("\n" + "─" * 60) == 3
            assert "🎬 V1  a" in messages
            assert "   title (old → new):" in messages
            assert "     old title" in messages
            assert "     テストタイトル  [7 units]" in messages
            assert "   description first lines (old → new):" in messages
            assert "     - old desc" in messages
            assert "       …" in messages
            assert "     + 本文" in messages
            assert messages.count("   ✅ updated") == 3
            assert "\n✅ done" in messages

    def test_should_not_call_update_execute_when_dry_run(self, tmp_path, monkeypatch, caplog):
        """`--dry-run` 時は `update().execute()` を呼ばない."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--dry-run"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([_snippet("V_ALPHA")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            # When
            mod.main()

            # Then: update().execute() も sleep も呼ばれない
            yt_mock.videos.return_value.update.return_value.execute.assert_not_called()
            sleep_mock.assert_not_called()
            assert "\n🔍 dry-run; 1 videos would be updated" in [record.message for record in caplog.records]

    def test_should_sleep_0_4_per_successful_update(self, tmp_path, monkeypatch):
        """quota throttle: 更新ごとに `time.sleep(0.4)` を呼ぶ."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 2 件
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "a", video_id="V1")
        _make_collection_with_descriptions(ch, "b", video_id="V2")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        yt_mock = _build_youtube_mock([_snippet("V1"), _snippet("V2")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            # When
            mod.main()

            # Then
            assert sleep_mock.call_count == 2
            for c in sleep_mock.call_args_list:
                assert c == call(0.4)

    def test_should_keep_old_title_when_new_title_exceeds_100_utf16_units(self, tmp_path, monkeypatch, caplog):
        """新タイトル UTF-16 > 100 units 時は old title を保持し description のみ更新."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 101 units の新タイトル（BMP 文字 1 個 = 1 unit）
        long_title = "x" * 101
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(
            ch,
            "alpha",
            video_id="V_ALPHA",
            title=long_title,
            description="new desc",
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock(
            [
                _snippet("V_ALPHA", title="kept old title", description="old desc"),
            ]
        )

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

            # Then
            update_call = yt_mock.videos.return_value.update.call_args_list[0]
            body = update_call.kwargs["body"]
            assert body["snippet"]["title"] == "kept old title"
            assert body["snippet"]["description"] == "new desc"
            assert (
                "WARNING",
                "⚠️  V_ALPHA (alpha): new title is 101 UTF-16 units (>100). "
                "Keeping old title; updating description only.",
            ) in [(record.levelname, record.message) for record in caplog.records]

    def test_should_log_collection_load_failure(self, tmp_path, monkeypatch, caplog):
        """collection 読み込み失敗は collection 名と例外詳細を ERROR に残す."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)

        with (
            patch.object(mod, "load_collection", side_effect=RuntimeError("broken metadata")),
            patch.object(mod, "get_youtube") as gy,
        ):
            mod.main()

        assert ("ERROR", "❌ alpha: broken metadata") in [
            (record.levelname, record.message) for record in caplog.records
        ]
        gy.assert_not_called()

    def test_should_continue_after_semantic_metadata_error(self, tmp_path, monkeypatch, caplog):
        """意味的に不正な collection を記録し、正常な collection は更新する."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha-invalid", omit_video_id=True)
        _make_collection_with_descriptions(ch, "beta-valid", video_id="V_VALID")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([_snippet("V_VALID")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            mod.main()

        assert ("ERROR", "❌ alpha-invalid: no complete_collection.video_id in alpha-invalid") in [
            (record.levelname, record.message) for record in caplog.records
        ]
        assert yt_mock.videos.return_value.list.call_args.kwargs["id"] == "V_VALID"
        assert yt_mock.videos.return_value.update.return_value.execute.call_count == 1

    def test_should_fail_loud_when_tracking_json_is_corrupt(self, tmp_path, monkeypatch):
        """公開 main 経路で破損 JSON を JSONDecodeError のまま伝播させる."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        col = _make_collection_with_descriptions(ch, "alpha")
        (col / "20-documentation" / "upload_tracking.json").write_text("{broken", encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])

        with (
            patch.object(mod, "get_youtube") as get_youtube_mock,
            pytest.raises(json.JSONDecodeError),
        ):
            mod.main()

        get_youtube_mock.assert_not_called()

    def test_should_fail_loud_when_metadata_read_raises_os_error(self, tmp_path, monkeypatch):
        """公開 main 経路で metadata の OSError を握りつぶさず伝播させる."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        col = _make_collection_with_descriptions(ch, "alpha")
        descriptions_path = col / "20-documentation" / "descriptions.md"
        original_read_text = Path.read_text

        def read_text_with_failure(path: Path, *args, **kwargs):
            if path == descriptions_path:
                raise OSError("metadata unavailable")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        monkeypatch.setattr(Path, "read_text", read_text_with_failure)

        with (
            patch.object(mod, "get_youtube") as get_youtube_mock,
            pytest.raises(OSError, match="metadata unavailable"),
        ):
            mod.main()

        get_youtube_mock.assert_not_called()

    def test_should_log_video_not_found_on_youtube(self, tmp_path, monkeypatch, caplog):
        """list 結果に video ID がない場合は ID と collection を ERROR に残す."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_MISSING")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([])

        with patch.object(mod, "get_youtube", return_value=yt_mock):
            mod.main()

        assert ("ERROR", "❌ V_MISSING (alpha): not found on YouTube") in [
            (record.levelname, record.message) for record in caplog.records
        ]
        yt_mock.videos.return_value.update.assert_not_called()

    def test_should_log_http_error_when_update_fails(self, tmp_path, monkeypatch, caplog):
        """videos.update の HttpError はドメイン例外化して詳細を ERROR に残す."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([_snippet("V_ALPHA")])
        response = MagicMock(status=403, reason="Forbidden")
        http_error = HttpError(response, b'{"error": {"message": "quota exceeded"}}')
        yt_mock.videos.return_value.update.return_value.execute.side_effect = http_error

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
            pytest.raises(YouTubeAPIError) as exc_info,
        ):
            mod.main()

        error_records = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_records) == 1
        assert error_records[0].message.startswith(
            "   ❌ update failed: Failed to update video V_ALPHA: <HttpError 403"
        )
        assert "quota exceeded" in error_records[0].message
        assert exc_info.value.status_code == 403
        assert exc_info.value.__cause__ is http_error

    def test_should_convert_list_http_error_and_fail_loud(self, tmp_path, monkeypatch):
        """videos.list の HttpError は status/reason/cause 付き YouTubeAPIError として伝播する."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        yt_mock = _build_youtube_mock([])
        response = MagicMock(status=403, reason="Forbidden")
        http_error = HttpError(
            response,
            b'{"error": {"message": "quota exceeded", "errors": [{"reason": "quotaExceeded"}]}}',
        )
        yt_mock.videos.return_value.list.return_value.execute.side_effect = http_error

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            pytest.raises(YouTubeAPIError) as exc_info,
        ):
            mod.main()

        assert str(exc_info.value).startswith("Failed to fetch current video snippets: <HttpError 403")
        assert exc_info.value.status_code == 403
        assert exc_info.value.reason == "quotaExceeded"
        assert exc_info.value.__cause__ is http_error
        yt_mock.videos.return_value.update.assert_not_called()

    def test_should_continue_after_domain_update_error(self, tmp_path, monkeypatch, caplog):
        """1 件の更新 API failure を記録し、後続動画の更新と throttle を継続する."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        _make_collection_with_descriptions(ch, "beta", video_id="V_BETA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        caplog.set_level(logging.INFO, logger=mod.__name__)
        yt_mock = _build_youtube_mock([_snippet("V_ALPHA"), _snippet("V_BETA")])
        response = MagicMock(status=403, reason="Forbidden")
        http_error = HttpError(response, b'{"error": {"message": "quota exceeded"}}')
        yt_mock.videos.return_value.update.return_value.execute.side_effect = [http_error, {"id": "V_BETA"}]

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep") as sleep_mock,
            pytest.raises(YouTubeAPIError) as exc_info,
        ):
            mod.main()

        assert yt_mock.videos.return_value.update.return_value.execute.call_count == 2
        assert sleep_mock.call_args_list == [call(0.4), call(0.4)]
        assert exc_info.value.status_code == 403
        assert exc_info.value.__cause__ is http_error
        messages = [record.message for record in caplog.records]
        assert any(message.startswith("   ❌ update failed: Failed to update video V_ALPHA") for message in messages)
        assert messages.count("   ✅ updated") == 1
        assert "\n✅ done" not in messages


# ---------------------------------------------------------------------------
# 4. main — snippet fallback 契約
# ---------------------------------------------------------------------------


class TestMainSnippetFallbacks:
    """snippet 欠落値の既存契約を公開 main 経路で固定する."""

    def test_should_preserve_remote_tags_when_markdown_tags_are_absent(self, tmp_path, monkeypatch):
        """説明文だけの更新で既存 YouTube tags を消さない."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA", omit_sections=["タグ"])
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        item = _snippet("V_ALPHA")
        item["snippet"]["tags"] = ["remote-tag"]
        yt_mock = _build_youtube_mock([item])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            mod.main()

        body = yt_mock.videos.return_value.update.call_args.kwargs["body"]
        assert body["snippet"]["tags"] == ["remote-tag"]

    def test_should_default_category_to_music_when_remote_category_is_absent(self, tmp_path, monkeypatch):
        """remote snippet に categoryId がない場合は Music category 10 を送る."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        item = _snippet("V_ALPHA")
        del item["snippet"]["categoryId"]
        yt_mock = _build_youtube_mock([item])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            mod.main()

        body = yt_mock.videos.return_value.update.call_args.kwargs["body"]
        assert body["snippet"]["categoryId"] == "10"

    def test_should_omit_default_language_when_remote_value_is_absent(self, tmp_path, monkeypatch):
        """remote 値欠落時は defaultLanguage を推測・注入しない."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        item = _snippet("V_ALPHA")
        del item["snippet"]["defaultLanguage"]
        yt_mock = _build_youtube_mock([item])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            mod.main()

        body = yt_mock.videos.return_value.update.call_args.kwargs["body"]
        assert "defaultLanguage" not in body["snippet"]


# ---------------------------------------------------------------------------
# 5. load_collection — COLLECTIONS_DIR 即時評価の解消
# ---------------------------------------------------------------------------


class TestLoadCollection:
    """`load_collection()` が `channel_dir()` を毎回再評価する."""

    def test_should_reevaluate_channel_dir_on_each_call(self, tmp_path, monkeypatch):
        """`CHANNEL_DIR` 切り替え後に呼んだ場合、新しいパスから読み込む."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 同名 collection を 2 チャンネル用意。中身の title だけ違える
        ch_a = _setup_channel(tmp_path / "a")
        _make_collection_with_descriptions(ch_a, "same-name", video_id="V_A", title="title in A", description="desc A")
        ch_b = _setup_channel(tmp_path / "b")
        _make_collection_with_descriptions(ch_b, "same-name", video_id="V_B", title="title in B", description="desc B")

        # When: A 指定でロード
        monkeypatch.setenv("CHANNEL_DIR", str(ch_a))
        reset()
        result_a = mod.load_collection("same-name")

        # When: B 指定でロード
        monkeypatch.setenv("CHANNEL_DIR", str(ch_b))
        reset()
        result_b = mod.load_collection("same-name")

        # Then
        assert result_a["video_id"] == "V_A"
        assert result_a["title"] == "title in A"
        assert result_b["video_id"] == "V_B"
        assert result_b["title"] == "title in B"

    def test_should_raise_when_video_id_missing(self, tmp_path, monkeypatch):
        """`complete_collection.video_id` 欠落で `RuntimeError`（既存エラーパス）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", omit_video_id=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When/Then
        with pytest.raises(RuntimeError, match="no complete_collection.video_id"):
            mod.load_collection("alpha")

    def test_should_raise_when_description_section_missing(self, tmp_path, monkeypatch):
        """`Complete Collection 概要欄` セクション欠落で `RuntimeError`."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 概要欄 セクションだけ欠落
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", omit_sections=["概要欄"])
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When/Then
        with pytest.raises(RuntimeError) as excinfo:
            mod.load_collection("alpha")

        message = str(excinfo.value)
        assert "descriptions.md parse failed in alpha" in message
        assert "期待する見出し（完全一致）" in message
        assert ("不足/不一致の見出し:\n  - ## Complete Collection 概要欄") in message
        assert "検出した ## 見出し" in message
        assert "修正例" in message
        assert "/video-description を再実行" in message

    def test_should_raise_when_title_section_missing(self, tmp_path, monkeypatch):
        """`タイトル案` セクション欠落で `RuntimeError`."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: タイトル案 セクションだけ欠落
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", omit_sections=["タイトル案"])
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When/Then
        with pytest.raises(RuntimeError) as excinfo:
            mod.load_collection("alpha")

        message = str(excinfo.value)
        assert "descriptions.md parse failed in alpha" in message
        assert "期待する見出し（完全一致）" in message
        assert ("不足/不一致の見出し:\n  - ## タイトル案") in message
        assert "検出した ## 見出し" in message
        assert "修正例" in message
        assert "/video-description を再実行" in message

    def test_should_strip_double_quotes_from_tags(self, tmp_path, monkeypatch):
        """ダブルクォートで囲まれたタグから引用符を除去する (#1096)."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(
            ch,
            "alpha",
            video_id="V_ALPHA",
            tags=['"lofi beats"', '"jazz"', '"study music"'],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        result = mod.load_collection("alpha")

        # Then
        assert result["tags"] == ["lofi beats", "jazz", "study music"]


# ---------------------------------------------------------------------------
# 5. extract_md_section
# ---------------------------------------------------------------------------


class TestBuildSnippetUpdateBody:
    """`build_snippet_update_body` — read-modify-write で mutable キーのみ保持する."""

    def test_should_preserve_default_audio_language(self):
        """old_snippet に defaultAudioLanguage があれば body に引き継がれる (defaultAudioLanguage 消失防止)."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        old_snippet = {
            "title": "old title",
            "description": "old desc",
            "categoryId": "10",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "ja",
        }

        # When
        body = mod.build_snippet_update_body("V1", old_snippet, "new title", "new desc", ["tag1"])

        # Then
        assert body["snippet"]["defaultAudioLanguage"] == "ja"

    def test_should_omit_default_language_when_absent_from_old_snippet(self):
        """old_snippet に defaultLanguage が無ければ body にも含めない（"en" 注入の再発防止）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: defaultLanguage 未設定
        old_snippet = {
            "title": "old title",
            "description": "old desc",
            "categoryId": "10",
        }

        # When
        body = mod.build_snippet_update_body("V1", old_snippet, "new title", "new desc", ["tag1"])

        # Then
        assert "defaultLanguage" not in body["snippet"]

    def test_should_exclude_readonly_snippet_keys(self):
        """old_snippet の read-only キー（publishedAt / thumbnails 等）は body に含めない."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: read-only フィールドが混ざった old_snippet
        old_snippet = {
            "title": "old title",
            "description": "old desc",
            "categoryId": "10",
            "publishedAt": "2020-01-01T00:00:00Z",
            "channelId": "UCxxxx",
            "thumbnails": {"default": {"url": "https://example.com/x.jpg"}},
            "channelTitle": "My Channel",
            "localized": {"title": "old title", "description": "old desc"},
            "liveBroadcastContent": "none",
        }

        # When
        body = mod.build_snippet_update_body("V1", old_snippet, "new title", "new desc", ["tag1"])

        # Then
        for readonly_key in (
            "publishedAt",
            "channelId",
            "thumbnails",
            "channelTitle",
            "localized",
            "liveBroadcastContent",
        ):
            assert readonly_key not in body["snippet"]

    def test_should_override_title_description_tags_with_arguments(self):
        """title/description/tags は引数の値で上書きされる（old_snippet の値を無視する）."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        old_snippet = {
            "title": "old title",
            "description": "old desc",
            "tags": ["old-tag"],
            "categoryId": "10",
        }

        # When
        body = mod.build_snippet_update_body("V1", old_snippet, "new title", "new desc", ["new-tag-1", "new-tag-2"])

        # Then
        assert body["id"] == "V1"
        assert body["snippet"]["title"] == "new title"
        assert body["snippet"]["description"] == "new desc"
        assert body["snippet"]["tags"] == ["new-tag-1", "new-tag-2"]


class TestExtractMdSection:
    """`load_collection` の Error テスト経路の前提となる補助 utility."""

    def test_should_return_fenced_body_when_header_matches(self):
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        md = "## Complete Collection 概要欄\n\n```\nhello world\n```\n"

        # When
        result = mod.extract_md_section(md, "Complete Collection 概要欄")

        # Then
        assert result == "hello world"

    def test_should_return_none_when_header_missing(self):
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        md = "## Other Section\n\n```\nbody\n```\n"

        # When
        result = mod.extract_md_section(md, "Complete Collection 概要欄")

        # Then
        assert result is None


# ---------------------------------------------------------------------------
# quota 記録（Issue #2058）
# ---------------------------------------------------------------------------


class TestQuotaLogging:
    """dry-run / apply / failure で quota 記録が固定されること（Issue #2058）."""

    @staticmethod
    def _quota_calls(quota_mock) -> list[tuple[str, str, float]]:
        return [(c.args[0], c.args[1], c.args[2]) for c in quota_mock.call_args_list]

    def test_dry_run_records_only_issued_read_request(self, tmp_path, monkeypatch):
        """dry-run では実際に発行した videos.list だけが記録される."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "alpha", video_id="V_ALPHA")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc", "--dry-run"])
        yt_mock = _build_youtube_mock([_snippet("V_ALPHA")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod, "log_quota") as quota_mock,
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

        # Then: videos.list 1 件のみ（update は発行されないので記録されない）
        assert self._quota_calls(quota_mock) == [("youtube-data-api", "videos.list", 1)]

    def test_apply_records_read_and_update_as_separate_operations(self, tmp_path, monkeypatch):
        """apply では read（videos.list）と videos.update が別 operation として記録される."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: 2 件
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "a", video_id="V1")
        _make_collection_with_descriptions(ch, "b", video_id="V2")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        yt_mock = _build_youtube_mock([_snippet("V1"), _snippet("V2")])

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod, "log_quota") as quota_mock,
            patch.object(mod.time, "sleep"),
        ):
            # When
            mod.main()

        # Then: リクエスト回数と記録件数が一致（videos.list ×1 + videos.update ×2）
        assert self._quota_calls(quota_mock) == [
            ("youtube-data-api", "videos.list", 1),
            ("youtube-data-api", "videos.update", 50),
            ("youtube-data-api", "videos.update", 50),
        ]
        update_metadata = [c.kwargs["metadata"] for c in quota_mock.call_args_list[1:]]
        assert update_metadata == [{"video_id": "V1"}, {"video_id": "V2"}]

    def test_update_failure_records_quota_then_raises_original_error(self, tmp_path, monkeypatch):
        """update 失敗時も quota を記録した上で、元のドメイン例外契約が維持される."""
        from youtube_automation.scripts import bulk_update_descriptions_from_md as mod

        # Given: V1 失敗 / V2 成功
        ch = _setup_channel(tmp_path)
        _make_collection_with_descriptions(ch, "a", video_id="V1")
        _make_collection_with_descriptions(ch, "b", video_id="V2")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-desc"])
        yt_mock = _build_youtube_mock([_snippet("V1"), _snippet("V2")])
        resp = MagicMock()
        resp.status = 403
        http_err = HttpError(resp=resp, content=b'{"error": {"errors": [{"reason": "forbidden"}]}}')
        yt_mock.videos.return_value.update.return_value.execute.side_effect = [http_err, {"id": "ok"}]

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod, "log_quota") as quota_mock,
            patch.object(mod.time, "sleep"),
        ):
            # When/Then: 部分進捗（V2 は更新）後に最初の失敗が raise される
            with pytest.raises(YouTubeAPIError):
                mod.main()

        # Then: 失敗した update も含め全リクエストが記録される
        assert self._quota_calls(quota_mock) == [
            ("youtube-data-api", "videos.list", 1),
            ("youtube-data-api", "videos.update", 50),
            ("youtube-data-api", "videos.update", 50),
        ]
