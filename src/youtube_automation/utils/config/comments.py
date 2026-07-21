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

MAX_LENGTH_DEFAULT = 280
CHANNEL_PERSONA_DEFAULT = ""
REQUESTS_PER_MINUTE_DEFAULT = 30
LIVE_CHAT_MAX_LENGTH_DEFAULT = 200
LIVE_CHAT_MAX_REPLIES_PER_HOUR_DEFAULT = 12
LIVE_CHAT_MAX_CONSECUTIVE_PER_USER_DEFAULT = 2
LIVE_CHAT_DAILY_QUOTA_BUDGET_DEFAULT = 1000
LIVE_CHAT_REPLY_QUOTA_COST_DEFAULT = 50


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
class LiveChatConfig:
    """`comments.live_chat` セクション（optional）."""

    enabled: bool = False
    language: str | None = None
    ng_words: list[str] = field(default_factory=list)
    max_length: int = LIVE_CHAT_MAX_LENGTH_DEFAULT
    max_replies_per_hour: int = LIVE_CHAT_MAX_REPLIES_PER_HOUR_DEFAULT
    max_consecutive_per_user: int = LIVE_CHAT_MAX_CONSECUTIVE_PER_USER_DEFAULT
    daily_quota_budget: int = LIVE_CHAT_DAILY_QUOTA_BUDGET_DEFAULT
    reply_quota_cost: int = LIVE_CHAT_REPLY_QUOTA_COST_DEFAULT
    no_broadcast_retry_sec: float = 60.0
    history_file: str = "live_chat_reply_history.json"
    channel_persona: str = CHANNEL_PERSONA_DEFAULT
    model: str | None = None
    codex_timeout_sec: float = 120.0
    process_initial_messages: bool = False

    def __post_init__(self) -> None:
        if self.language is not None and (not isinstance(self.language, str) or not self.language.strip()):
            raise ConfigError("comments.live_chat.language は空でない文字列で指定してください")
        if not isinstance(self.ng_words, list) or any(not isinstance(word, str) for word in self.ng_words):
            raise ConfigError("comments.live_chat.ng_words は文字列の list で指定してください")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise ConfigError("comments.live_chat.model は空でない文字列で指定してください")
        if not self.history_file.strip():
            raise ConfigError("comments.live_chat.history_file は空にできません")
        positive = {
            "max_length": self.max_length,
            "max_replies_per_hour": self.max_replies_per_hour,
            "max_consecutive_per_user": self.max_consecutive_per_user,
            "daily_quota_budget": self.daily_quota_budget,
            "reply_quota_cost": self.reply_quota_cost,
            "no_broadcast_retry_sec": self.no_broadcast_retry_sec,
            "codex_timeout_sec": self.codex_timeout_sec,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ConfigError(f"comments.live_chat.{name} は 0 より大きい値が必要です")


@dataclass(frozen=True)
class Comments:
    """`comments` セクション（optional）.

    - `enabled`: この機能を有効にするか
    - `rules`: 後方互換入力は loader で受けるが、処理では無視し空配列に正規化
    - `language`: 返信言語ヒント。省略時は YouTube API 既定言語を使う
    - `ng_words`: 本文にいずれかが含まれるコメントは除外
    - `max_replies_per_run`: 1 回の実行で返信する上限件数
    - `delay_between_replies_sec`: 返信 API 呼び出し間の sleep 秒
    - `history_file`: プロジェクトルートからの相対パスで履歴 JSON を保存
    - `skip_held_for_review`: `moderationStatus == 'heldForReview'` のコメントを skip するか
    - `generator`: AI ジェネレーター設定。省略時は codex
    """

    enabled: bool = False
    rules: list[object] = field(default_factory=list)
    language: str | None = None
    ng_words: list[str] = field(default_factory=list)
    max_replies_per_run: int = 20
    delay_between_replies_sec: float = 2.0
    history_file: str = "comment_reply_history.json"
    skip_held_for_review: bool = True
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    live_chat: LiveChatConfig = field(default_factory=LiveChatConfig)

    def __post_init__(self) -> None:
        if self.language is not None and not isinstance(self.language, str):
            raise ConfigError("comments.language は文字列でなければなりません")
        if self.language is not None and not self.language.strip():
            raise ConfigError("comments.language は空文字にできません")
