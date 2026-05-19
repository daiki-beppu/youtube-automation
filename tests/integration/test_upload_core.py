"""YouTubeUploadCore の統合テスト（Khorikov 準拠）

公開 API（upload_video, set_thumbnail）の振る舞いを検証する。
mock は管理下にない依存（YouTube API）にのみ使用。
プライベートメソッドの直接テストは行わない。
"""

from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.utils.exceptions import UploadError, YouTubeAPIError

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_core_with_mock_youtube():
    """YouTube API を mock した YouTubeUploadCore を返す。"""
    with patch("youtube_automation.utils.upload_core.get_youtube") as mock_get_youtube:
        mock_youtube = MagicMock()
        mock_get_youtube.return_value = mock_youtube

        from youtube_automation.utils.upload_core import YouTubeUploadCore

        core = YouTubeUploadCore()
        core.initialize()

        return core, mock_youtube


def _make_http_error(status: int, message: bytes = b"error") -> HttpError:
    """指定ステータスの HttpError を生成する。"""
    resp = Response({"status": status})
    return HttpError(resp, message)


# ---------------------------------------------------------------------------
# upload_video: 動画アップロード
# ---------------------------------------------------------------------------


class TestUploadVideo:
    def test_uploads_video_and_returns_id(self, tmp_path):
        """ハッピーパス: 動画アップロードが成功し video_id を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.return_value = (None, {"id": "abc123"})

        result = core.upload_video(str(video), {"snippet": {}, "status": {}})

        assert result == "abc123"

    def test_returns_none_for_missing_file(self):
        """存在しないファイルを指定すると None を返す"""
        core, _ = _make_core_with_mock_youtube()

        result = core.upload_video("/nonexistent/video.mp4", {"snippet": {}})

        assert result is None

    def test_raises_api_error_on_http_error(self, tmp_path):
        """YouTube API の HttpError は YouTubeAPIError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_youtube.videos.return_value.insert.side_effect = _make_http_error(403)

        with pytest.raises(YouTubeAPIError):
            core.upload_video(str(video), {"snippet": {}})

    def test_raises_upload_error_on_os_error(self, tmp_path):
        """ファイルアクセスエラーは UploadError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = OSError("disk error")

        with pytest.raises(UploadError):
            core.upload_video(str(video), {"snippet": {}})


# ---------------------------------------------------------------------------
# set_thumbnail: サムネイル設定
# ---------------------------------------------------------------------------


class TestSetThumbnail:
    def test_sets_thumbnail_for_small_image(self, tmp_path):
        """2MB 以下の画像はそのままアップロードされ True を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        result = core.set_thumbnail("video123", str(thumb))

        assert result is True

    def test_returns_false_when_file_inaccessible(self):
        """ファイルアクセスエラー時は False を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        mock_youtube.thumbnails.return_value.set.return_value.execute.side_effect = OSError("disk")

        # OSError は set_thumbnail 内で catch され False を返す
        result = core.set_thumbnail("video123", "/nonexistent/thumb.jpg")

        assert result is False

    def test_raises_api_error_on_http_error(self, tmp_path):
        """YouTube API エラーは YouTubeAPIError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        mock_youtube.thumbnails.return_value.set.return_value.execute.side_effect = _make_http_error(403)

        with pytest.raises(YouTubeAPIError):
            core.set_thumbnail("video123", str(thumb))


# ---------------------------------------------------------------------------
# リトライ動作: 公開メソッド upload_video 経由で検証
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    def test_retries_and_succeeds_on_transient_server_error(self, tmp_path):
        """5xx エラー後にリトライし、最終的に成功する"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = [
            _make_http_error(503),
            (None, {"id": "retry_ok"}),
        ]

        with patch("youtube_automation.utils.upload_core.time.sleep"):
            result = core.upload_video(str(video), {"snippet": {}})

        assert result == "retry_ok"


# ---------------------------------------------------------------------------
# resumable upload の resume / 通知挙動 (issue #381 P0-5)
# ---------------------------------------------------------------------------


_SESS_PREV = "https://upload.googleapis.com/SESS_PREV"
_SESS_NEW = "https://upload.googleapis.com/SESS_NEW"
_SESS_NEXT = "https://upload.googleapis.com/SESS_NEXT"


def _make_insert_request_with_uri_lifecycle(
    chunks,
    *,
    initial_uri=None,
    uri_after_each_chunk=None,
):
    """next_chunk の戻り値と resumable_uri の遷移をシミュレートする MagicMock を返す.

    Args:
        chunks: next_chunk の side_effect として渡すリスト
            （戻り値 tuple (status, response) または HttpError 等の例外）
        initial_uri: テスト開始時の `resumable_uri`（resume scenario 用に事前値を仕込む）
        uri_after_each_chunk: 各 chunk 後に resumable_uri を書き換える値のリスト
            （None なら書き換えなし）。googleapiclient が next_chunk 内部で
            resumable_uri を更新する挙動を模倣する。
    """
    insert_request = MagicMock()
    insert_request.resumable_uri = initial_uri
    insert_request._in_error_state = False

    if uri_after_each_chunk is None:
        # シンプルケース: next_chunk side_effect だけセット
        insert_request.next_chunk.side_effect = chunks
        return insert_request

    # 各 chunk 後に resumable_uri を更新するため side_effect 関数を構築
    call_index = {"i": 0}

    def _next_chunk_side_effect(*args, **kwargs):
        i = call_index["i"]
        call_index["i"] += 1
        # chunk 取得前の URI を更新（googleapiclient が server レスポンスから書く順序）
        if i < len(uri_after_each_chunk) and uri_after_each_chunk[i] is not None:
            insert_request.resumable_uri = uri_after_each_chunk[i]
        value = chunks[i]
        if isinstance(value, Exception):
            raise value
        return value

    insert_request.next_chunk.side_effect = _next_chunk_side_effect
    return insert_request


class TestResumableUploadResume:
    """resumable upload の resume kwargs と通知コールバックの振る舞いを検証する."""

    def test_should_preserve_legacy_behavior_when_no_resume_kwargs_are_passed(self, tmp_path):
        """既存テスト互換: kwargs 全省略時はコールバックなしで video_id を返す."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle([(None, {"id": "v1"})])
        mock_youtube.videos.return_value.insert.return_value = insert_request

        # When
        result = core.upload_video(str(video), {"snippet": {}, "status": {}})

        # Then
        assert result == "v1"
        assert insert_request._in_error_state is False

    def test_should_notify_session_uri_after_first_next_chunk(self, tmp_path):
        """plan 要件 #2: 初回 next_chunk 直後に on_session_uri_changed が発火する."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle(
            [(None, {"id": "v1"})],
            uri_after_each_chunk=[_SESS_NEW],
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_session_uri_changed = MagicMock()

        # When
        result = core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            resume_session_uri=None,
            on_session_uri_changed=on_session_uri_changed,
        )

        # Then
        assert result == "v1"
        on_session_uri_changed.assert_called_once_with(_SESS_NEW)

    def test_should_resume_from_persisted_uri_and_mark_error_state(self, tmp_path):
        """plan 要件 #4 + #5: 永続化 URI を resumable_uri に注入し _in_error_state を立てる."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle([(None, {"id": "v1"})])
        mock_youtube.videos.return_value.insert.return_value = insert_request

        # When
        core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            resume_session_uri=_SESS_PREV,
        )

        # Then
        assert insert_request.resumable_uri == _SESS_PREV
        assert insert_request._in_error_state is True

    def test_should_invoke_on_upload_complete_after_successful_upload(self, tmp_path):
        """plan 要件 #6: アップロード成功後 on_upload_complete が引数なしで呼ばれる."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle([(None, {"id": "v1"})])
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_upload_complete = MagicMock()

        # When
        result = core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            on_upload_complete=on_upload_complete,
        )

        # Then
        assert result == "v1"
        on_upload_complete.assert_called_once_with()

    def test_should_re_notify_on_uri_change_after_308_progress_update(self, tmp_path):
        """plan 要件 #3: 各 chunk 後の URI 更新（308）も冪等に保存される."""
        # Given: 1 chunk 目で URI=SESS_NEW、2 chunk 目で URI=SESS_NEXT に更新後成功
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        status_obj = MagicMock()
        status_obj.progress.return_value = 0.5

        insert_request = _make_insert_request_with_uri_lifecycle(
            [(status_obj, None), (None, {"id": "v1"})],
            uri_after_each_chunk=[_SESS_NEW, _SESS_NEXT],
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_session_uri_changed = MagicMock()

        # When
        result = core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            on_session_uri_changed=on_session_uri_changed,
        )

        # Then
        assert result == "v1"
        calls = [call.args for call in on_session_uri_changed.call_args_list]
        assert calls == [(_SESS_NEW,), (_SESS_NEXT,)]

    def test_should_not_re_notify_when_uri_is_unchanged_across_chunks(self, tmp_path):
        """plan 要件 #3 冪等性: 複数 chunk 中 URI 据置ならコールバック発火は初回のみ."""
        # Given: 全 chunk で同じ URI を維持
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        status_obj = MagicMock()
        status_obj.progress.return_value = 0.3

        insert_request = _make_insert_request_with_uri_lifecycle(
            [(status_obj, None), (status_obj, None), (None, {"id": "v1"})],
            uri_after_each_chunk=[_SESS_NEW, _SESS_NEW, _SESS_NEW],
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_session_uri_changed = MagicMock()

        # When
        core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            on_session_uri_changed=on_session_uri_changed,
        )

        # Then
        assert on_session_uri_changed.call_count == 1
        on_session_uri_changed.assert_called_once_with(_SESS_NEW)

    def test_should_accept_none_callbacks_without_raising(self, tmp_path):
        """コールバック全部 None でも例外を投げず video_id を返す（後方互換）."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle(
            [(None, {"id": "v1"})],
            uri_after_each_chunk=[_SESS_NEW],
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request

        # When
        result = core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            resume_session_uri=None,
            on_session_uri_changed=None,
            on_upload_complete=None,
        )

        # Then
        assert result == "v1"

    @pytest.mark.parametrize("status", [410, 404])
    def test_should_clear_session_and_return_none_on_session_expired(self, tmp_path, status):
        """plan 要件 #7: 410/404 は session 失効とみなし URI クリア + None 返却."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle(
            [_make_http_error(status)],
            initial_uri=_SESS_PREV,
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_session_uri_changed = MagicMock()

        # When
        result = core.upload_video(
            str(video),
            {"snippet": {}, "status": {}},
            resume_session_uri=_SESS_PREV,
            on_session_uri_changed=on_session_uri_changed,
        )

        # Then: session 失効なので None 返却 + クリア通知
        assert result is None
        on_session_uri_changed.assert_called_with(None)

    def test_should_treat_503_as_transient_retry_without_clearing_session(self, tmp_path):
        """plan 要件 #7 境界: 503 は session 失効ではなく既存 retry に乗る."""
        # Given: 503 後に成功
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        insert_request = _make_insert_request_with_uri_lifecycle(
            [_make_http_error(503), (None, {"id": "retry_ok"})],
            uri_after_each_chunk=[None, _SESS_NEW],
        )
        mock_youtube.videos.return_value.insert.return_value = insert_request
        on_session_uri_changed = MagicMock()

        # When
        with patch("youtube_automation.utils.upload_core.time.sleep"):
            result = core.upload_video(
                str(video),
                {"snippet": {}, "status": {}},
                on_session_uri_changed=on_session_uri_changed,
            )

        # Then: 成功し、session クリア (None 通知) は発火していない
        assert result == "retry_ok"
        clear_calls = [c for c in on_session_uri_changed.call_args_list if c.args == (None,)]
        assert clear_calls == []

    def test_should_propagate_non_session_http_error_as_youtube_api_error_on_insert_setup(self, tmp_path):
        """videos().insert() 自体が HttpError(403) を投げる場合は既存通り YouTubeAPIError 化."""
        # Given
        core, mock_youtube = _make_core_with_mock_youtube()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")
        mock_youtube.videos.return_value.insert.side_effect = _make_http_error(403)

        # When/Then
        with pytest.raises(YouTubeAPIError):
            core.upload_video(
                str(video),
                {"snippet": {}, "status": {}},
                resume_session_uri=_SESS_PREV,
            )
