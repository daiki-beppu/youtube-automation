"""scripts/fetch_stream_key.py / 周辺拡張のユニットテスト（issue #135）。

検証範囲（plan.md §テストカバレッジ要件）:

1. ``select_stream`` の純関数振る舞い
   - ``Default Stream Key`` タイトル優先
   - 不在時は ``cdn.frameRate != "variable"`` の先頭
   - 全部 variable のときは list 先頭
   - ``--stream-id`` 明示指定の優先
   - 一致 stream なし → ``ValidationError``
   - 空 list → ``YouTubeAPIError``
2. ``extract_stream_info``: ``streamName`` の抽出 / 欠落時の例外
3. ``write_op_secret``: ``op item edit`` 成功 / ``edit`` 失敗 → ``create`` フォールバック /
   ``op`` 不在 → ``ConfigError`` / 両方失敗 → ``ConfigError``
4. ``_SECRET_REFS`` への ``YOUTUBE_STREAM_KEY`` 登録確認
5. ``YouTubeOAuthHandler`` の ``(scopes, token_path)`` 拡張と既存 callsite との後方互換
6. CLI ``main()`` 統合: ``--stdout`` 出力、``--vault/--item`` で ``write_op_secret`` 経由保存、
   出力先未指定はエラー、``--stream-id`` の伝搬

YouTube Data API / OAuth / op CLI / 1Password はすべて ``unittest.mock`` で差し替える。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.exceptions import ConfigError, ValidationError, YouTubeAPIError
from youtube_automation.utils.secrets import _SECRET_REFS

# ---------------------------------------------------------------------------
# テストデータ
# ---------------------------------------------------------------------------


def _make_stream(
    *,
    stream_id: str = "stream-1",
    title: str = "Stream A",
    framerate: str = "30fps",
    stream_name: str | None = "abc-key-12345",
) -> dict:
    """``liveStreams.list`` レスポンスの 1 件分を組み立てる。

    ``stream_name=None`` を渡すと ``streamName`` キーを含まない辞書を返す
    （read-only スコープ誤用時の挙動を模倣するテスト向け）。
    """
    ingestion_info: dict = {}
    if stream_name is not None:
        ingestion_info["streamName"] = stream_name
    return {
        "id": stream_id,
        "snippet": {"title": title},
        "cdn": {
            "frameRate": framerate,
            "ingestionInfo": ingestion_info,
        },
    }


# ---------------------------------------------------------------------------
# select_stream（純関数）
# ---------------------------------------------------------------------------


class TestSelectStream:
    def test_default_stream_key_title_is_preferred(self):
        """Given 複数 stream のうち 1 件が "Default Stream Key" タイトル
        When ``select_stream(streams, stream_id=None)``
        Then その stream が選ばれる。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        streams = [
            _make_stream(stream_id="s1", title="Custom Stream"),
            _make_stream(stream_id="s2", title="Default Stream Key"),
            _make_stream(stream_id="s3", title="Other"),
        ]

        selected = select_stream(streams, stream_id=None)

        assert selected["id"] == "s2"

    def test_first_persistent_stream_when_default_missing(self):
        """Given Default Stream Key 不在
        When ``select_stream``
        Then ``cdn.frameRate != "variable"`` の最初の永続 stream が選ばれる。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        streams = [
            _make_stream(stream_id="s1", title="A", framerate="variable"),
            _make_stream(stream_id="s2", title="B", framerate="30fps"),
            _make_stream(stream_id="s3", title="C", framerate="60fps"),
        ]

        selected = select_stream(streams, stream_id=None)

        assert selected["id"] == "s2"

    def test_falls_back_to_first_when_all_variable(self):
        """Given 全 stream が variable framerate
        When ``select_stream``
        Then list 先頭が選ばれる（永続候補が 1 つも無いケースの最終フォールバック）。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        streams = [
            _make_stream(stream_id="s1", title="A", framerate="variable"),
            _make_stream(stream_id="s2", title="B", framerate="variable"),
        ]

        selected = select_stream(streams, stream_id=None)

        assert selected["id"] == "s1"

    def test_explicit_stream_id_returns_matching_stream(self):
        """Given Default Stream Key が存在しても
        When ``stream_id="s2"`` を明示
        Then 明示指定が優先され s2 が返る（フィルタ 3 = 明示優先）。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        streams = [
            _make_stream(stream_id="s1", title="Default Stream Key"),
            _make_stream(stream_id="s2", title="Custom"),
        ]

        selected = select_stream(streams, stream_id="s2")

        assert selected["id"] == "s2"

    def test_explicit_stream_id_not_found_raises_validation_error(self):
        """Given list に存在しない stream_id を明示
        When ``select_stream``
        Then ``ValidationError`` を投げる（入力不正）。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        streams = [_make_stream(stream_id="s1")]

        with pytest.raises(ValidationError):
            select_stream(streams, stream_id="nonexistent")

    def test_empty_streams_raises_youtube_api_error(self):
        """Given liveStreams.list が空
        When ``select_stream``
        Then ``YouTubeAPIError`` を投げる（API レスポンスが期待を満たさない）。
        """
        from youtube_automation.scripts.fetch_stream_key import select_stream

        with pytest.raises(YouTubeAPIError):
            select_stream([], stream_id=None)


# ---------------------------------------------------------------------------
# extract_stream_info（純関数）
# ---------------------------------------------------------------------------


class TestExtractStreamInfo:
    def test_extracts_stream_name(self):
        """Given 完全な stream dict
        When ``extract_stream_info``
        Then ``streamName``（ストリームキー本体）を返す。
        """
        from youtube_automation.scripts.fetch_stream_key import extract_stream_info

        stream = _make_stream(stream_name="key-xyz-789")

        name = extract_stream_info(stream)

        assert name == "key-xyz-789"

    def test_missing_stream_name_raises_youtube_api_error(self):
        """Given ``cdn.ingestionInfo.streamName`` が欠落
        When ``extract_stream_info``
        Then ``YouTubeAPIError`` を投げる（read-only スコープ誤用時のマスク挙動を検出）。
        """
        from youtube_automation.scripts.fetch_stream_key import extract_stream_info

        stream = _make_stream(stream_name=None)

        with pytest.raises(YouTubeAPIError):
            extract_stream_info(stream)


# ---------------------------------------------------------------------------
# write_op_secret（utils/secrets.py の新関数）
# ---------------------------------------------------------------------------


class TestWriteOpSecret:
    def test_op_item_edit_success(self):
        """Given op CLI が PATH 上にある
        When ``write_op_secret`` を呼ぶ
        Then ``op item edit`` が呼ばれて例外なしで完了する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", "stream_key", "abc-key-12345")

        assert mock_run.call_count >= 1
        # 1 回目のコマンドが ``op item edit`` であること
        first_args = mock_run.call_args_list[0].args[0]
        assert "edit" in first_args, f"1st subprocess call should be 'op item edit': {first_args}"

    def test_op_item_edit_fails_falls_back_to_create(self):
        """Given ``op item edit`` が失敗（item 不存在）
        When ``write_op_secret``
        Then ``op item create`` にフォールバックして書き込みが完了する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["op", "item", "edit"],
                    stderr="item not found",
                ),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ]

            write_op_secret("Personal", "YouTube", "stream_key", "abc-key-12345")

        assert mock_run.call_count == 2, "edit 失敗 → create フォールバックで 2 回呼ばれる想定"
        second_args = mock_run.call_args_list[1].args[0]
        assert "create" in second_args, f"2nd subprocess call should be 'op item create': {second_args}"

    def test_op_unavailable_raises_config_error(self):
        """Given ``op`` CLI が PATH 上に無い
        When ``write_op_secret``
        Then ``ConfigError``（外部ツール不在）。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with patch("youtube_automation.utils.secrets.shutil.which", return_value=None):
            with pytest.raises(ConfigError):
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

    def test_both_edit_and_create_fail_raises_config_error(self):
        """Given ``op item edit`` と ``op item create`` の両方が失敗
        When ``write_op_secret``
        Then ``ConfigError``（書き込み経路がすべて失敗）。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["op"],
                stderr="permission denied",
            )

            with pytest.raises(ConfigError):
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

    def test_value_is_passed_to_op_subprocess(self):
        """Given 任意の secret 値
        When ``write_op_secret``
        Then subprocess の引数に ``"<field>=<value>"`` 形式で値が渡る。

        値の流れが op コマンド引数まで伝搬していることを保証する（隠れた解決経路の禁止）。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        all_args = mock_run.call_args_list[0].args[0]
        joined = " ".join(all_args)
        assert "secret-value-xyz" in joined, f"value not propagated to op CLI args: {all_args}"
        assert "stream_key" in joined, f"field not propagated to op CLI args: {all_args}"


# ---------------------------------------------------------------------------
# _SECRET_REFS への登録確認
# ---------------------------------------------------------------------------


class TestSecretRefsRegistration:
    def test_youtube_stream_key_is_registered_in_secret_refs(self):
        """Given ``_SECRET_REFS``
        When ``YOUTUBE_STREAM_KEY`` を引く
        Then 登録されている。
        """
        assert "YOUTUBE_STREAM_KEY" in _SECRET_REFS, (
            "YOUTUBE_STREAM_KEY が _SECRET_REFS に未登録（terraform / op read で参照不能）"
        )

    def test_youtube_stream_key_uri_is_op_format(self):
        """Given 登録 URI
        When 値を読む
        Then ``op://`` で始まる 1Password 参照 URI である。
        """
        ref = _SECRET_REFS["YOUTUBE_STREAM_KEY"]
        assert ref.startswith("op://"), f"1Password 参照 URI 形式でない: {ref}"


# ---------------------------------------------------------------------------
# YouTubeOAuthHandler の (scopes, token_path) 拡張
# ---------------------------------------------------------------------------


class TestOAuthHandlerExtension:
    """`YouTubeOAuthHandler.__init__` に ``scopes`` / ``token_path`` を追加した拡張の検証。

    既存 3 callsite は引数なしのまま動作する必要がある（後方互換）。
    """

    def test_default_constructor_uses_token_json_when_auth_dir_passed(self, tmp_path: Path):
        """Given ``auth_dir`` のみ指定
        When 既存 callsite が ``YouTubeOAuthHandler(auth_dir=...)`` 相当で構築
        Then ``token_file`` は ``auth_dir/"token.json"`` のまま（後方互換）。
        """
        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()

        handler = YouTubeOAuthHandler(auth_dir=str(auth_dir))

        assert handler.token_file == auth_dir / "token.json"

    def test_default_constructor_no_args_keeps_existing_scopes(self):
        """Given 既存 callsite の引数なし呼び出し（``oauth_handler.py:214`` /
        ``analytics_system.py:62`` / ``youtube_service.py:42``）
        When ``YouTubeOAuthHandler()``
        Then ``SCOPES`` クラス属性は元の 4 件のまま（broaden しない）。
        """
        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        # クラス属性 SCOPES は引き続き 4 件で機能（既存のデフォルトとして残す）
        assert "https://www.googleapis.com/auth/youtube" in YouTubeOAuthHandler.SCOPES
        assert "https://www.googleapis.com/auth/youtube.force-ssl" in YouTubeOAuthHandler.SCOPES
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in YouTubeOAuthHandler.SCOPES
        assert "https://www.googleapis.com/auth/yt-analytics-monetary.readonly" in YouTubeOAuthHandler.SCOPES

        # インスタンス化自体も引数なしで通る（既存 callsite が壊れないこと）
        handler = YouTubeOAuthHandler()
        assert handler.token_file.name == "token.json"

    def test_custom_token_path_overrides_default(self, tmp_path: Path):
        """Given ``token_path`` を指定
        When ``YouTubeOAuthHandler(token_path=...)``
        Then ``token_file`` は指定値を保持する。
        """
        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        custom_token = tmp_path / "auth" / "token_streaming.json"
        custom_token.parent.mkdir(parents=True)

        handler = YouTubeOAuthHandler(token_path=custom_token)

        assert handler.token_file == custom_token

    def test_custom_scopes_propagate_to_credentials_loader(self, tmp_path: Path):
        """Given ``scopes`` と ``token_path`` を指定し token ファイルが存在
        When ``authenticate()``
        Then ``Credentials.from_authorized_user_file`` に指定した scopes が渡る。

        ``self._scopes`` のような実装詳細に依存せず、観測可能な API 呼び出しで検証する。
        """
        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        custom_scopes = ["https://www.googleapis.com/auth/youtube"]
        token_file = tmp_path / "token_streaming.json"
        token_file.write_text("{}")
        client_secrets = tmp_path / "client_secrets.json"
        client_secrets.write_text("{}")

        with (
            patch.dict(os.environ, {"CLIENT_SECRETS_DIR": str(tmp_path)}),
            patch("youtube_automation.auth.oauth_handler.Credentials") as mock_creds_cls,
        ):
            mock_creds = MagicMock()
            mock_creds.expired = False
            mock_creds.valid = True
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds

            handler = YouTubeOAuthHandler(scopes=custom_scopes, token_path=token_file)
            handler.authenticate()

        mock_creds_cls.from_authorized_user_file.assert_called_once_with(str(token_file), custom_scopes)

    def test_custom_scopes_propagate_to_installed_app_flow(self, tmp_path: Path):
        """Given ``scopes`` を指定し token ファイルが存在しない（新規認証パス）
        When ``authenticate()``
        Then ``InstalledAppFlow.from_client_secrets_file`` に指定した scopes が渡る。
        """
        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        custom_scopes = ["https://www.googleapis.com/auth/youtube"]
        token_file = tmp_path / "token_streaming.json"  # 存在させない
        client_secrets = tmp_path / "client_secrets.json"
        client_secrets.write_text("{}")

        with (
            patch.dict(os.environ, {"CLIENT_SECRETS_DIR": str(tmp_path)}),
            patch("youtube_automation.auth.oauth_handler.InstalledAppFlow") as mock_flow_cls,
        ):
            mock_flow = MagicMock()
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_creds.expired = False
            mock_flow.run_local_server.return_value = mock_creds
            mock_flow_cls.from_client_secrets_file.return_value = mock_flow

            handler = YouTubeOAuthHandler(scopes=custom_scopes, token_path=token_file)
            handler.authenticate()

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(str(client_secrets), custom_scopes)


# ---------------------------------------------------------------------------
# CLI ``main()`` 統合
# ---------------------------------------------------------------------------


class TestCli:
    def test_stdout_prints_stream_key(self, capsys, monkeypatch):
        """Given ``--stdout``
        When ``main()``
        Then 抽出した streamName が標準出力に出力される（CI / Terraform 用途）。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setattr("sys.argv", ["yt-fetch-stream-key", "--stdout"])

        fake_stream = _make_stream(
            stream_id="s1",
            title="Default Stream Key",
            stream_name="my-stream-key-1234",
        )
        with (
            patch.object(fsk, "get_streaming_credentials", return_value=MagicMock()),
            patch.object(fsk, "list_live_streams", return_value=[fake_stream]),
        ):
            fsk.main()

        captured = capsys.readouterr()
        assert "my-stream-key-1234" in captured.out

    def test_vault_item_invokes_write_op_secret(self, monkeypatch):
        """Given ``--vault Personal --item YouTube``
        When ``main()``
        Then ``write_op_secret(vault, item, "stream_key", <key>)`` が呼ばれる。

        ``--field`` 未指定時のデフォルトが ``"stream_key"`` であることも合わせて担保する。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setattr(
            "sys.argv",
            ["yt-fetch-stream-key", "--vault", "Personal", "--item", "YouTube"],
        )

        fake_stream = _make_stream(stream_name="abc-key-99999")
        with (
            patch.object(fsk, "get_streaming_credentials", return_value=MagicMock()),
            patch.object(fsk, "list_live_streams", return_value=[fake_stream]),
            patch.object(fsk, "write_op_secret") as mock_write,
        ):
            fsk.main()

        mock_write.assert_called_once_with("Personal", "YouTube", "stream_key", "abc-key-99999")

    def test_no_output_target_raises_system_exit(self, monkeypatch):
        """Given ``--stdout`` も ``--vault/--item`` も指定なし
        When ``main()``
        Then ``SystemExit``（exit code 非 0）。

        argparse の必須選択チェック（mutually_exclusive_group required=True）または
        明示バリデーションのいずれでも SystemExit を期待する。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setattr("sys.argv", ["yt-fetch-stream-key"])

        with pytest.raises(SystemExit):
            fsk.main()

    def test_stream_id_flag_is_passed_to_select_stream(self, monkeypatch):
        """Given ``--stream-id explicit-id``
        When ``main()``
        Then ``select_stream`` に ``stream_id="explicit-id"`` が渡る。

        フラグが末端まで伝搬していること（隠れた解決の禁止）を保証する。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setattr(
            "sys.argv",
            ["yt-fetch-stream-key", "--stdout", "--stream-id", "explicit-id"],
        )

        fake_stream = _make_stream(stream_id="explicit-id", stream_name="key-1")
        streams = [fake_stream]

        with (
            patch.object(fsk, "get_streaming_credentials", return_value=MagicMock()),
            patch.object(fsk, "list_live_streams", return_value=streams),
            patch.object(fsk, "select_stream", wraps=fsk.select_stream) as mock_select,
        ):
            fsk.main()

        # select_stream(streams, stream_id="explicit-id") の呼び出しを確認
        call_args = mock_select.call_args
        # 位置引数とキーワード引数の両方を許容
        kwargs = call_args.kwargs
        args = call_args.args
        passed_id = kwargs.get("stream_id") if "stream_id" in kwargs else (args[1] if len(args) > 1 else None)
        assert passed_id == "explicit-id", f"stream_id flag not propagated: args={args} kwargs={kwargs}"
