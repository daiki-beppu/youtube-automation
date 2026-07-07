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

    def __post_init__(self) -> None:
        if self.language is not None and not isinstance(self.language, str):
            raise ConfigError("comments.language は文字列でなければなりません")
        if self.language is not None and not self.language.strip():
            raise ConfigError("comments.language は空文字にできません")
