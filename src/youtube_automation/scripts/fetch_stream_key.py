#!/usr/bin/env python3
"""yt-fetch-stream-key CLI（issue #135 / issue #152）。

YouTube Data API ``liveStreams.list`` でストリームキーを取得し、
``--stdout`` で標準出力、``--vault/--item`` で 1Password に書き込む。

専用 token (``auth/token_streaming.json``) を ``YouTubeOAuthHandler`` に渡し、
既存 upload 用 token (``auth/token.json``) と分離する。

``--stdout`` モードはストリームキーが平文で流れるため、必ず pipe 経由で受けること
（直接 TTY に出力しようとすると WARNING を stderr に出して exit code 2 で中断する）。
GitHub Actions 上では ``::add-mask::<value>`` を先行出力してログマスキングを有効化する。

Usage:
    yt-fetch-stream-key --stdout | <consumer>          # pipe 経由必須
    yt-fetch-stream-key --vault Personal --item YouTube
    yt-fetch-stream-key --vault Personal --item YouTube --stream-id <id>
"""

from __future__ import annotations

import argparse
import os
import sys

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError
from youtube_automation.utils.secrets import write_op_secret

# 契約文字列・マジック値は 1 箇所で定義する
_DEFAULT_STREAM_KEY_TITLE = "Default Stream Key"
_VARIABLE_FRAMERATE = "variable"
_STREAMING_SCOPE = "https://www.googleapis.com/auth/youtube"
_STREAMING_TOKEN_FILENAME = "token_streaming.json"
_DEFAULT_FIELD = "stream_key"


# ----------------------------------------------------------------------------
# 引数パース
# ----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-fetch-stream-key",
        description=(
            "YouTube Live のストリームキーを liveStreams.list API から取得し、標準出力または 1Password に書き込む。"
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="ストリームキーを標準出力に書き出す（CI / Terraform 用、pipe 経由必須）",
    )
    parser.add_argument(
        "--vault",
        help="1Password vault 名（--item と組で指定）",
    )
    parser.add_argument(
        "--item",
        help="1Password item 名（--vault と組で指定）",
    )
    parser.add_argument(
        "--field",
        default=_DEFAULT_FIELD,
        help=f"1Password item の field 名（default: {_DEFAULT_FIELD}）",
    )
    parser.add_argument(
        "--stream-id",
        dest="stream_id",
        help="取得対象 stream ID を明示指定（指定時はフィルタを無視）",
    )
    parser.add_argument(
        "--force-reauth",
        action="store_true",
        help="OAuth トークンを破棄して再認証を強制する",
    )
    return parser


def _validate_output_target(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """出力先の指定を検証する（Fail Fast）。"""
    has_op_target = args.vault is not None or args.item is not None
    if args.stdout and has_op_target:
        parser.error("--stdout と --vault/--item は同時指定できません")
    if not args.stdout and not (args.vault and args.item):
        parser.error("--stdout もしくは --vault と --item の組を指定してください")


# ----------------------------------------------------------------------------
# OAuth / API
# ----------------------------------------------------------------------------


def get_streaming_credentials(force_reauth: bool = False):
    """stream key 取得用の OAuth credentials を返す。

    既存 upload 用 token (``auth/token.json``) と分離するため、
    ``auth/token_streaming.json`` を専用 token として使う。
    scope は write 権限の ``youtube`` のみを要求する
    （``youtube.readonly`` だと streamName がマスクされる挙動の報告あり）。
    """
    token_path = channel_dir() / "auth" / _STREAMING_TOKEN_FILENAME
    handler = YouTubeOAuthHandler(scopes=[_STREAMING_SCOPE], token_path=token_path)
    return handler.authenticate(force_reauth=force_reauth)


def list_live_streams(credentials) -> list[dict]:
    """``liveStreams.list?part=cdn,snippet&mine=true`` を呼んで items を返す。"""
    service = build("youtube", "v3", credentials=credentials)
    try:
        response = service.liveStreams().list(part="cdn,snippet", mine=True).execute()
    except HttpError as err:
        raise YouTubeAPIError.from_http_error(err, "liveStreams.list の呼び出しに失敗しました") from err
    return response.get("items", [])


# ----------------------------------------------------------------------------
# 純関数: stream の選択 / 値の抽出
# ----------------------------------------------------------------------------


def select_stream(streams: list[dict], stream_id: str | None) -> dict:
    """フィルタ優先順に従って 1 件の stream を選ぶ。

    優先順:
        1. ``stream_id`` 明示指定（一致 stream なし → ``ValidationError``）
        2. ``snippet.title == "Default Stream Key"``
        3. ``cdn.frameRate != "variable"`` の最初の永続 stream
        4. list の先頭（フォールバック）

    Raises:
        YouTubeAPIError: ``streams`` が空（API レスポンスが期待を満たさない）
        ValidationError: ``stream_id`` 指定だが一致する stream が無い
    """
    if not streams:
        raise YouTubeAPIError(
            "liveStreams.list が空でした。"
            "YouTube Studio で対象アカウントにライブ配信機能が有効化されているか確認してください。"
        )

    if stream_id is not None:
        for stream in streams:
            if stream.get("id") == stream_id:
                return stream
        raise ValidationError(f"指定した stream_id が liveStreams.list に存在しません: {stream_id}")

    for stream in streams:
        if stream.get("snippet", {}).get("title") == _DEFAULT_STREAM_KEY_TITLE:
            return stream

    for stream in streams:
        if stream.get("cdn", {}).get("frameRate") != _VARIABLE_FRAMERATE:
            return stream

    return streams[0]


def extract_stream_info(stream: dict) -> str:
    """``cdn.ingestionInfo.streamName``（ストリームキー本体）を抽出する。

    Raises:
        YouTubeAPIError: ``streamName`` が欠落している
            （read-only スコープ誤用時のマスク挙動を検出する）
    """
    ingestion_info = stream.get("cdn", {}).get("ingestionInfo", {})
    name = ingestion_info.get("streamName")
    if not name:
        raise YouTubeAPIError(
            "streamName が API レスポンスに含まれていません。"
            f"scope に '{_STREAMING_SCOPE}' (write 権限) が含まれていない可能性があります。"
            " --force-reauth で再認証してください。"
        )
    return name


# ----------------------------------------------------------------------------
# stdout 出力（GHA マスキング + TTY ガード）
# ----------------------------------------------------------------------------


def _emit_stdout(value: str) -> None:
    """``--stdout`` 経路の出力を 1 箇所に閉じ込める（issue #152）。

    - ``GITHUB_ACTIONS == "true"`` のとき ``::add-mask::<value>`` 行を先行出力し、
      GitHub Actions のログマスキングを有効化する。
    - ``sys.stdout`` が TTY のとき、平文露出（bash history / ``set -x``）を防ぐため
      stderr に WARNING を出して ``sys.exit(2)`` で中断する。
    - いずれでもないとき値のみを stdout に出力する（pipe 経由の正常パス）。
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # GitHub Actions のログマスキング
        print(f"::add-mask::{value}")
    if sys.stdout.isatty():
        # TTY 出力は警告を stderr に出して中断
        print("WARNING: stream_key を TTY に出力します。pipe で受けてください。", file=sys.stderr)
        sys.exit(2)
    print(value)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _validate_output_target(args, parser)

    credentials = get_streaming_credentials(force_reauth=args.force_reauth)
    streams = list_live_streams(credentials)
    stream = select_stream(streams, stream_id=args.stream_id)
    stream_name = extract_stream_info(stream)

    if args.stdout:
        _emit_stdout(stream_name)
        return

    write_op_secret(args.vault, args.item, args.field, stream_name)
    print(
        f"✅ ストリームキーを 1Password に保存しました: vault={args.vault} item={args.item} field={args.field}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
