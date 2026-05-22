"""コメント自動返信設定の責務別 dataclass（optional）."""

from __future__ import annotations

from dataclasses import dataclass, field

SUPPORTED_REPLY_GENERATORS = ("template", "gemini")
SUPPORTED_GENERATOR_ERROR_FALLBACKS = ("template", "skip")


@dataclass(frozen=True)
class GeneratorConfig:
    """返信 generator の既定設定."""

    type: str = "template"
    model: str = ""
    channel_persona: str = ""
    max_length: int = 280
    fallback_on_error: str = "template"
    min_interval_sec: float = 0.0


@dataclass(frozen=True)
class CommentRule:
    """コメント返信ルール 1 件.

    - `keywords` のいずれかが本文に部分一致 → match
    - `pattern`（正規表現）のいずれかが本文にマッチ → match
    - 両方指定時はどちらか成立で match
    - `language` はテンプレート辞書を引くときのキー。省略時は channel 既定言語を使う
    - `priority` が大きい順に評価し、最初に match したルールが採用される
    """

    name: str
    keywords: list[str] = field(default_factory=list)
    pattern: str | None = None
    template_key: str = "default"
    language: str | None = None
    priority: int = 0
    generator: str | None = None


@dataclass(frozen=True)
class Comments:
    """`comments` セクション（optional）.

    - `enabled`: この機能を有効にするか
    - `rules`: マッチング規則のリスト
    - `templates`: `{言語: {template_key: テンプレート文字列}}` 形式の辞書
    - `ng_words`: 本文にいずれかが含まれるコメントは除外
    - `max_replies_per_run`: 1 回の実行で返信する上限件数
    - `delay_between_replies_sec`: 返信 API 呼び出し間の sleep 秒
    - `history_file`: チャンネルディレクトリからの相対パスで履歴 JSON を保存
    - `skip_held_for_review`: `moderationStatus == 'heldForReview'` のコメントを skip するか
    """

    enabled: bool = False
    rules: list[CommentRule] = field(default_factory=list)
    templates: dict[str, dict[str, str]] = field(default_factory=dict)
    ng_words: list[str] = field(default_factory=list)
    max_replies_per_run: int = 20
    delay_between_replies_sec: float = 2.0
    history_file: str = "comment_reply_history.json"
    skip_held_for_review: bool = True
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
