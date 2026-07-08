"""固定コメント（オーナーコメント）自動投稿設定の責務別 dataclass（optional）.

`config/channel/pinned-comment.json` のトップレベルキー `pinned_comment` を読み込む。
`comments`（自動返信）とは別概念で、自チャンネルの動画にトップレベルコメントを
1 件投稿する `yt-pinned-comment` CLI が参照する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_HISTORY_FILE = "pinned_comment_history.json"
DEFAULT_DELAY_SEC = 2.5
DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True)
class PinnedComment:
    """`pinned_comment` セクション（optional）.

    - `enabled`: この機能を有効にするか（`comments.enabled` と対称のオプトイン）
    - `history_file`: プロジェクトルートからの相対パスで履歴 JSON を保存
    - `delay_between_posts_sec`: 投稿 API 呼び出し間の sleep 秒
    - `default_language`: `--lang` 省略時に使うテンプレート言語キー
    - `templates`: `{言語: テンプレート文字列}` 形式の辞書。
      プレースホルダ `{scene_phrase}` `{video_title}` `{theme}` `{scene_emoji}` を展開する
    """

    enabled: bool = False
    history_file: str = DEFAULT_HISTORY_FILE
    delay_between_posts_sec: float = DEFAULT_DELAY_SEC
    default_language: str = DEFAULT_LANGUAGE
    templates: dict[str, str] = field(default_factory=dict)
