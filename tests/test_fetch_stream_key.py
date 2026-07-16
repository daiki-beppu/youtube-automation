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
3. ``write_op_secret``: ``op item edit`` 成功 / item 不在時のみ ``create`` /
   ``op`` 不在・edit/create 失敗・timeout → ``ConfigError``
4. ``_SECRET_REFS`` への ``YOUTUBE_STREAM_KEY`` 登録確認
5. ``YouTubeOAuthHandler`` の ``(scopes, token_path)`` 拡張と既存 callsite との後方互換
6. CLI ``main()`` 統合: ``--stdout`` 出力、``--vault/--item`` で ``write_op_secret`` 経由保存、
   出力先未指定はエラー、``--stream-id`` の伝搬

YouTube Data API / OAuth / op CLI / 1Password はすべて ``unittest.mock`` で差し替える。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.exceptions import ConfigError, ValidationError, YouTubeAPIError
from youtube_automation.utils.secrets import _SECRET_REFS

_VALID_CLIENT_SECRETS_JSON = '{"installed":{"client_id":"x","client_secret":"y","redirect_uris":["http://localhost"]}}'

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

        assert mock_run.call_count == 1
        first_args = mock_run.call_args_list[0].args[0]
        assert "edit" in first_args, f"1st subprocess call should be 'op item edit': {first_args}"

    @pytest.mark.parametrize("stderr", ["item not found", "isn't an item in this vault"])
    def test_should_fall_back_to_create_when_item_is_not_found(self, stderr: str):
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
                    stderr=stderr,
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

    def test_should_fail_without_create_when_edit_permission_is_denied(self):
        """Given ``op item edit`` が item 不在以外で失敗
        When ``write_op_secret``
        Then create に進まず ``ConfigError`` で fail fast する。
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

            with pytest.raises(ConfigError) as exc_info:
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

        message = str(exc_info.value)
        assert "vault=Personal" in message
        assert "item=YouTube" in message
        assert "field=stream_key" in message
        assert "permission denied" in message
        assert mock_run.call_count == 1

    def test_should_fail_without_create_when_edit_times_out(self):
        """Given ``op item edit`` が timeout
        When ``write_op_secret``
        Then create に進まず timeout 詳細付き ``ConfigError`` で fail fast する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["op", "item", "edit"], timeout=10)

            with pytest.raises(ConfigError, match="command timed out after 10 seconds"):
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

        assert mock_run.call_count == 1

    def test_should_raise_config_error_when_create_fails(self):
        """Given item 不在の edit 後に create も失敗
        When ``write_op_secret``
        Then create の stderr 付き ``ConfigError`` で fail fast する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                subprocess.CalledProcessError(returncode=1, cmd=["op"], stderr="item not found"),
                subprocess.CalledProcessError(returncode=1, cmd=["op"], stderr="permission denied"),
            ]

            with pytest.raises(ConfigError, match="op item create .*permission denied"):
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

        assert mock_run.call_count == 2

    def test_should_raise_config_error_when_create_times_out(self):
        """Given item 不在の edit 後に create が timeout
        When ``write_op_secret``
        Then create の timeout 詳細付き ``ConfigError`` で fail fast する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                subprocess.CalledProcessError(returncode=1, cmd=["op"], stderr="item not found"),
                subprocess.TimeoutExpired(cmd=["op", "item", "create"], timeout=10),
            ]

            with pytest.raises(ConfigError, match="op item create .*command timed out after 10 seconds"):
                write_op_secret("Personal", "YouTube", "stream_key", "abc")

        assert mock_run.call_count == 2

    def test_value_is_not_in_argv_on_edit_path(self):
        """Given 任意の secret 値
        When ``write_op_secret`` が ``op item edit`` を呼ぶ
        Then secret 値そのものは argv に含まれない（``ps aux`` / ``/proc/<pid>/cmdline`` 漏えい防止）。

        Issue #151 の core regression guard: argv に value 文字列を埋め込む実装への退行を検出する。
        値の伝搬は stdin 経由（別ケースで担保）。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        edit_argv = mock_run.call_args_list[0].args[0]
        joined = " ".join(edit_argv)
        assert "secret-value-xyz" not in joined, (
            f"raw secret value must not appear in op CLI argv (ps aux exposure): {edit_argv}"
        )

    def test_value_is_not_in_argv_on_create_fallback_path(self):
        """Given ``op item edit`` が失敗（item 不在）
        When ``write_op_secret`` が ``op item create`` にフォールバックする
        Then create argv にも secret 値そのものは含まれない。

        edit / create 双方が同一の漏えい経路を共有しているため、fallback 側も対称に担保する。
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

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        create_argv = mock_run.call_args_list[1].args[0]
        joined = " ".join(create_argv)
        assert "secret-value-xyz" not in joined, (
            f"raw secret value must not appear in op CLI argv on create fallback: {create_argv}"
        )

    def test_value_is_passed_via_stdin_on_edit_path(self):
        """Given 任意の secret 値
        When ``write_op_secret`` が ``op item edit`` を呼ぶ
        Then item JSON は ``subprocess.run(..., input=...)`` の kwargs として渡る。

        argv に乗らないだけでなく、stdin 経由で確実に op プロセスに伝搬していることを独立検証する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        edit_kwargs = mock_run.call_args_list[0].kwargs
        assert json.loads(edit_kwargs["input"]) == {
            "fields": [{"id": "stream_key", "type": "CONCEALED", "value": "secret-value-xyz"}]
        }

    def test_value_is_passed_via_stdin_on_create_fallback_path(self):
        """Given ``op item edit`` が失敗
        When ``write_op_secret`` が ``op item create`` にフォールバックする
        Then create 呼び出しでも PASSWORD item JSON を stdin 配線する。
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

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        create_kwargs = mock_run.call_args_list[1].kwargs
        template = json.loads(create_kwargs["input"])
        assert template["category"] == "PASSWORD"
        assert template["title"] == "YouTube"
        assert {field["id"] for field in template["fields"]} == {"password", "stream_key"}
        assert all(field["value"] == "secret-value-xyz" for field in template["fields"])

    def test_should_omit_stdin_marker_when_edit_reads_json_from_stdin(self):
        """Given ``field="stream_key"``
        When ``write_op_secret`` が argv を構築する
        Then JSON template は stdin から渡し、edit argv に stdin marker は含めない。
        """
        from youtube_automation.utils.secrets import write_op_secret

        field = "stream_key"
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", field, "secret-value-xyz")

        edit_argv = mock_run.call_args_list[0].args[0]
        assert edit_argv == ["op", "item", "edit", "YouTube", "--vault", "Personal"]

    def test_should_include_builtin_password_field_when_creating_password_item(self):
        """PASSWORD item の新規作成には組み込み password field が必要。"""
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                subprocess.CalledProcessError(returncode=1, cmd=["op"], stderr="item not found"),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ]
            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        create_template = json.loads(mock_run.call_args_list[1].kwargs["input"])
        password_field = next(field for field in create_template["fields"] if field["id"] == "password")
        assert password_field["purpose"] == "PASSWORD"

    def test_should_not_duplicate_password_field_when_target_field_is_password(self):
        """Given 書き込み対象自体が組み込み password field
        When PASSWORD item を新規作成する
        Then password field は purpose 付きの 1 件だけになる。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                subprocess.CalledProcessError(returncode=1, cmd=["op"], stderr="item not found"),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ]

            write_op_secret("Personal", "YouTube", "password", "secret-value-xyz")

        create_template = json.loads(mock_run.call_args_list[1].kwargs["input"])
        assert create_template["fields"] == [
            {
                "id": "password",
                "type": "CONCEALED",
                "purpose": "PASSWORD",
                "value": "secret-value-xyz",
            }
        ]

    def test_text_true_is_preserved_for_str_based_stderr_handling(self):
        """Given ``op item edit`` を呼ぶ
        When ``write_op_secret`` が ``subprocess.run`` を呼ぶ
        Then ``text=True`` が kwargs に含まれる。

        ``_op_error_detail`` が stderr を文字列として扱う前提を境界で固定する。
        """
        from youtube_automation.utils.secrets import write_op_secret

        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            write_op_secret("Personal", "YouTube", "stream_key", "secret-value-xyz")

        edit_kwargs = mock_run.call_args_list[0].kwargs
        assert edit_kwargs.get("text") is True, (
            f"text=True must be preserved so stderr remains str: kwargs={edit_kwargs}"
        )


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
        client_secrets.write_text(_VALID_CLIENT_SECRETS_JSON)

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
        client_secrets.write_text(_VALID_CLIENT_SECRETS_JSON)

        with (
            patch.dict(os.environ, {"CLIENT_SECRETS_DIR": str(tmp_path)}),
            patch("youtube_automation.auth.oauth_handler.InstalledAppFlow") as mock_flow_cls,
        ):
            mock_flow = MagicMock()
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_creds.expired = False
            # _save_credentials が file.write(creds.to_json()) を呼ぶため
            # 文字列を返さないと TypeError が伝播する（issue #149 で
            # ``except Exception`` を ``except OSError`` に絞ったため）
            mock_creds.to_json.return_value = "{}"
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

    def test_stdout_and_vault_mutually_exclusive(self, monkeypatch):
        """Given ``--stdout`` と ``--vault/--item`` を同時指定
        When ``main()``
        Then ``SystemExit``（mutex 違反: ``_validate_output_target`` 内
        ``parser.error`` 経由で argparse が exit する）。

        issue #152 で未カバーだった ``stdout=True and has_op_target`` 分岐の回帰テスト。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setattr(
            "sys.argv",
            ["yt-fetch-stream-key", "--stdout", "--vault", "Personal", "--item", "YouTube"],
        )

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

    def test_main_emits_add_mask_under_github_actions(self, capsys, monkeypatch):
        """Given ``GITHUB_ACTIONS=true`` 環境下で ``--stdout``
        When ``main()``
        Then stdout に ``::add-mask::<key>`` 行が出る（CLI 入口 → ``_emit_stdout`` 配線確認）。

        到達経路のリグレッション担保: ``main()`` の出力箇所が
        マスキング対応経路（``_emit_stdout``）を確実に通っていることを保証する。
        """
        from youtube_automation.scripts import fetch_stream_key as fsk

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setattr("sys.argv", ["yt-fetch-stream-key", "--stdout"])

        fake_stream = _make_stream(stream_name="masked-key-42")
        with (
            patch.object(fsk, "get_streaming_credentials", return_value=MagicMock()),
            patch.object(fsk, "list_live_streams", return_value=[fake_stream]),
        ):
            fsk.main()

        captured = capsys.readouterr()
        assert "::add-mask::masked-key-42" in captured.out, (
            f"GHA mask line missing on main()'s stdout: {captured.out!r}"
        )
        assert "masked-key-42" in captured.out


# ---------------------------------------------------------------------------
# _emit_stdout（GHA マスキング / TTY ガード / 通常出力）
# ---------------------------------------------------------------------------


class TestEmitStdout:
    """``_emit_stdout(value)`` の純関数振る舞い検証（issue #152）。

    挙動仕様（``order.md`` §マスキング）:
    - ``GITHUB_ACTIONS == "true"`` のとき stdout に ``::add-mask::<value>`` を出す
    - ``sys.stdout.isatty()`` が True のとき stderr に WARNING を出して ``sys.exit(2)``
    - いずれにも該当しないとき stdout に ``<value>`` のみを出す

    観測可能な振る舞い（stdout / stderr / exit code）のみを検証し、
    ``os.environ.get`` の呼び出し回数のような実装詳細には依存しない。
    """

    def test_emits_add_mask_line_when_github_actions_is_true(self, capsys, monkeypatch):
        """Given ``GITHUB_ACTIONS="true"`` + 非TTY（capsys デフォルト）
        When ``_emit_stdout("my-key-1234")``
        Then stdout に ``::add-mask::my-key-1234`` 行 → ``my-key-1234`` 行 の順で出る。

        順序まで担保するため ``splitlines()`` 一致で検証する。
        """
        from youtube_automation.scripts.fetch_stream_key import _emit_stdout

        monkeypatch.setenv("GITHUB_ACTIONS", "true")

        _emit_stdout("my-key-1234")

        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines == ["::add-mask::my-key-1234", "my-key-1234"], (
            f"expected GHA mask line followed by value line, got: {lines!r}"
        )

    def test_does_not_emit_add_mask_when_github_actions_is_unset(self, capsys, monkeypatch):
        """Given ``GITHUB_ACTIONS`` 未設定 + 非TTY
        When ``_emit_stdout("plain-value")``
        Then ``::add-mask::`` プレフィックス行は出ず、値のみ出る（既存挙動の維持）。
        """
        from youtube_automation.scripts.fetch_stream_key import _emit_stdout

        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

        _emit_stdout("plain-value")

        captured = capsys.readouterr()
        assert "::add-mask::" not in captured.out, f"unexpected GHA mask prefix when env unset: {captured.out!r}"
        assert "plain-value" in captured.out

    def test_does_not_emit_add_mask_when_github_actions_is_not_literally_true(self, capsys, monkeypatch):
        """Given ``GITHUB_ACTIONS="false"``（``"true"`` 完全一致でない）+ 非TTY
        When ``_emit_stdout("plain-value")``
        Then ``::add-mask::`` 行は出ない。

        ``order.md`` の ``== "true"`` 仕様の境界検証。誤判定で平文露出するリスクの予防。
        """
        from youtube_automation.scripts.fetch_stream_key import _emit_stdout

        monkeypatch.setenv("GITHUB_ACTIONS", "false")

        _emit_stdout("plain-value")

        captured = capsys.readouterr()
        assert "::add-mask::" not in captured.out, (
            f"GHA mask prefix should not appear when env != 'true': {captured.out!r}"
        )
        assert "plain-value" in captured.out

    def test_exits_with_code_2_when_stdout_is_a_tty(self, capsys, monkeypatch):
        """Given ``sys.stdout.isatty()`` が True
        When ``_emit_stdout("tty-key")``
        Then ``SystemExit(code=2)`` + stderr に WARNING + stdout に値が出ない。

        TTY 経由での平文露出を防止する異常パス。``GITHUB_ACTIONS`` を未設定にして
        マスク行による偽陽性（stdout に "tty-key" を含む可能性）を排除する。
        """
        from youtube_automation.scripts.fetch_stream_key import _emit_stdout

        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)

        with pytest.raises(SystemExit) as exc:
            _emit_stdout("tty-key")

        assert exc.value.code == 2, f"expected exit code 2, got: {exc.value.code!r}"

        captured = capsys.readouterr()
        assert "WARNING" in captured.err, f"warning must be emitted to stderr on TTY: {captured.err!r}"
        assert "tty-key" not in captured.out, f"value must not appear on TTY stdout: {captured.out!r}"
