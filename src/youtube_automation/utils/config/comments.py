"""コメント自動返信設定の責務別 dataclass（optional）."""

from __future__ import annotations

from dataclasses import dataclass, field

from youtube_automation.utils.exceptions import ConfigError

PROVIDER_CODEX = "codex"
PROVIDER_GEMINI = "gemini"
VALID_PROVIDERS = (PROVIDER_GEMINI, PROVIDER_CODEX)

FALLBACK_SKIP = "skip"
FALLBACK_RETRY = "retry"
VALID_FALLBACK_VALUES = (FALLBACK_SKIP, FALLBACK_RETRY)

# CommentRule.scope: コメントの階層（top-level / reply）でマッチ対象を絞る (#524)
SCOPE_TOP_LEVEL = "top_level"
SCOPE_REPLY = "reply"
SCOPE_ANY = "any"
VALID_SCOPES = (SCOPE_TOP_LEVEL, SCOPE_REPLY, SCOPE_ANY)

MAX_LENGTH_DEFAULT = 280
CHANNEL_PERSONA_DEFAULT = ""
REQUESTS_PER_MINUTE_DEFAULT = 30
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"


@dataclass(frozen=True)
class GeneratorConfig:
    """`comments.generator` セクション.

    - `provider`: 返信生成プロバイダー。VALID_PROVIDERS のいずれか
    - `model`: provider へ渡すモデル名。provider="gemini" の場合必須
    - `channel_persona`: AI 返信時のチャンネルペルソナ説明
    - `max_length`: 生成テキストの最大文字数。超過時は切り詰め + warn
    - `fallback_on_error`: AI 失敗時の挙動。VALID_FALLBACK_VALUES のいずれか
    - `requests_per_minute`: AI API のレート制限（呼び出し/分）
    """

    provider: str = PROVIDER_CODEX
    model: str | None = None
    channel_persona: str = CHANNEL_PERSONA_DEFAULT
    max_length: int = MAX_LENGTH_DEFAULT
    fallback_on_error: str = FALLBACK_SKIP
    requests_per_minute: int = REQUESTS_PER_MINUTE_DEFAULT

    def __post_init__(self) -> None:
        if self.provider not in VALID_PROVIDERS:
            raise ConfigError(f"GeneratorConfig.provider 無効: {self.provider!r}")
        if self.provider == PROVIDER_GEMINI and not self.model:
            raise ConfigError("GeneratorConfig.provider='gemini' では model が必須です")
        if self.fallback_on_error not in VALID_FALLBACK_VALUES:
            raise ConfigError(f"GeneratorConfig.fallback_on_error 無効: {self.fallback_on_error!r}")


@dataclass(frozen=True)
class CommentRule:
    """コメント返信ルール 1 件.

    - `keywords` のいずれかが本文に部分一致 → match
    - `pattern`（正規表現）のいずれかが本文にマッチ → match
    - 両方指定時はどちらか成立で match
    - `language` は返信言語ヒント。省略時は channel 既定言語を使う
    - `priority` が大きい順に評価し、最初に match したルールが採用される
    - `provider`: ルール単位の provider override。VALID_PROVIDERS のいずれか。
      省略時はグローバルの comments.generator.provider に従う
    - `scope`: マッチ対象のコメント階層。VALID_SCOPES のいずれか (#524)。
      `"top_level"` は top-level コメントのみ、`"reply"` は reply のみ、
      `"any"`（既定）は両方に当たる（#365 以前と等価の後方互換挙動）
    """

    name: str
    keywords: list[str] = field(default_factory=list)
    pattern: str | None = None
    language: str | None = None
    priority: int = 0
    provider: str | None = None
    scope: str = SCOPE_ANY


@dataclass(frozen=True)
class Comments:
    """`comments` セクション（optional）.

    - `enabled`: この機能を有効にするか
    - `rules`: マッチング規則のリスト
    - `ng_words`: 本文にいずれかが含まれるコメントは除外
    - `max_replies_per_run`: 1 回の実行で返信する上限件数
    - `delay_between_replies_sec`: 返信 API 呼び出し間の sleep 秒
    - `history_file`: チャンネルディレクトリからの相対パスで履歴 JSON を保存
    - `skip_held_for_review`: `moderationStatus == 'heldForReview'` のコメントを skip するか
    - `generator`: AI ジェネレーター設定。省略時は codex
    """

    enabled: bool = False
    rules: list[CommentRule] = field(default_factory=list)
    ng_words: list[str] = field(default_factory=list)
    max_replies_per_run: int = 20
    delay_between_replies_sec: float = 2.0
    history_file: str = "comment_reply_history.json"
    skip_held_for_review: bool = True
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)

    def __post_init__(self) -> None:
        for rule in self.rules:
            if rule.provider is not None and rule.provider not in VALID_PROVIDERS:
                raise ConfigError(f"CommentRule.provider 無効: {rule.provider!r}")
            if rule.scope not in VALID_SCOPES:
                raise ConfigError(f"CommentRule.scope 無効: {rule.scope!r}（{VALID_SCOPES} のいずれか）")
