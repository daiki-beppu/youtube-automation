"""コメント自動返信設定の責務別 dataclass（optional）.

`comments.generator.type` / `CommentRule.generator` / `fallback_on_error` の有効値定数と
各設定セクションの dataclass を定義する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from youtube_automation.utils.exceptions import ConfigError

GENERATOR_TYPE_TEMPLATE = "template"
GENERATOR_TYPE_GEMINI = "gemini"
VALID_GENERATOR_TYPES = (GENERATOR_TYPE_TEMPLATE, GENERATOR_TYPE_GEMINI)

FALLBACK_TEMPLATE = "template"
FALLBACK_SKIP = "skip"
VALID_FALLBACK_VALUES = (FALLBACK_TEMPLATE, FALLBACK_SKIP)

MAX_LENGTH_DEFAULT = 280
CHANNEL_PERSONA_DEFAULT = ""


@dataclass(frozen=True)
class GeneratorConfig:
    """`comments.generator` セクション.

    - `type`: バックエンド種別。VALID_GENERATOR_TYPES のいずれか
    - `model`: Gemini モデル名。type="gemini" の場合必須
    - `channel_persona`: AI 返信時のチャンネルペルソナ説明
    - `max_length`: 生成テキストの最大文字数。超過時は切り詰め + warn
    - `fallback_on_error`: AI 失敗時の挙動。VALID_FALLBACK_VALUES のいずれか
    - `requests_per_minute`: AI API のレート制限（呼び出し/分）
    """

    type: str
    model: str | None
    channel_persona: str
    max_length: int
    fallback_on_error: str
    requests_per_minute: int

    def __post_init__(self) -> None:
        if self.type not in VALID_GENERATOR_TYPES:
            raise ConfigError(f"GeneratorConfig.type 無効: {self.type!r}")
        if self.type == GENERATOR_TYPE_GEMINI and not self.model:
            raise ConfigError("GeneratorConfig.type='gemini' では model が必須です")
        if self.fallback_on_error not in VALID_FALLBACK_VALUES:
            raise ConfigError(f"GeneratorConfig.fallback_on_error 無効: {self.fallback_on_error!r}")


@dataclass(frozen=True)
class CommentRule:
    """コメント返信ルール 1 件.

    - `keywords` のいずれかが本文に部分一致 → match
    - `pattern`（正規表現）のいずれかが本文にマッチ → match
    - 両方指定時はどちらか成立で match
    - `language` はテンプレート辞書を引くときのキー。省略時は channel 既定言語を使う
    - `priority` が大きい順に評価し、最初に match したルールが採用される
    - `generator`: ルール単位のジェネレーター override。VALID_GENERATOR_TYPES のいずれか。
      省略時はグローバルの comments.generator.type に従う
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
    - `generator`: AI ジェネレーター設定。省略時はテンプレートのみ
    """

    enabled: bool = False
    rules: list[CommentRule] = field(default_factory=list)
    templates: dict[str, dict[str, str]] = field(default_factory=dict)
    ng_words: list[str] = field(default_factory=list)
    max_replies_per_run: int = 20
    delay_between_replies_sec: float = 2.0
    history_file: str = "comment_reply_history.json"
    skip_held_for_review: bool = True
    generator: GeneratorConfig | None = None

    def __post_init__(self) -> None:
        uses_gemini = any(r.generator == GENERATOR_TYPE_GEMINI for r in self.rules)
        if uses_gemini and (self.generator is None or self.generator.type != GENERATOR_TYPE_GEMINI):
            raise ConfigError(
                "comments.rules に generator='gemini' があるため comments.generator.type='gemini' (+model) が必須です"
            )
