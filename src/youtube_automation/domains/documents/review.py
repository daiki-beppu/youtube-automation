"""Provider-neutral review selection manifest and validation policy."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from youtube_automation.core.errors import ReviewSelectionError

ReviewArtifact = Literal["plan", "music-prompt", "thumbnail", "audio", "video"]
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ReviewCandidate:
    id: str
    label: str
    digest: str
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not _CANDIDATE_ID.fullmatch(self.id):
            raise ReviewSelectionError(f"候補IDが不正です: {self.id}")
        if not self.label or len(self.label) > 256:
            raise ReviewSelectionError("候補labelは1〜256文字で指定してください")
        if not _DIGEST.fullmatch(self.digest):
            raise ReviewSelectionError("候補digestはSHA-256で指定してください")
        if any(not key or not value for key, value in self.details):
            raise ReviewSelectionError("候補detailは非空のlabel/value pairで指定してください")


@dataclass(frozen=True)
class SelectionManifest:
    artifact: ReviewArtifact
    token: str
    expires_at: datetime
    artifact_digest: str
    candidates: tuple[ReviewCandidate, ...]

    @classmethod
    def create(
        cls,
        *,
        artifact: ReviewArtifact,
        artifact_digest: str,
        candidates: tuple[ReviewCandidate, ...],
        now: datetime,
        lifetime: timedelta,
        expires_at: datetime | None = None,
    ) -> "SelectionManifest":
        if now.tzinfo is None or now.utcoffset() is None:
            raise ReviewSelectionError("manifest時刻にはtimezoneが必要です")
        if not _DIGEST.fullmatch(artifact_digest):
            raise ReviewSelectionError("artifact digestはSHA-256で指定してください")
        if not candidates or len({candidate.id for candidate in candidates}) != len(candidates):
            raise ReviewSelectionError("候補allowlistは一意な候補を1件以上必要とします")
        expiry = expires_at if expires_at is not None else now + lifetime
        if expiry.tzinfo is None or expiry.utcoffset() is None:
            raise ReviewSelectionError("manifest期限にはtimezoneが必要です")
        return cls(
            artifact=artifact,
            token=secrets.token_urlsafe(32),
            expires_at=expiry,
            artifact_digest=artifact_digest,
            candidates=candidates,
        )

    def validate_selection(
        self, *, token: str, candidate_id: str, artifact_digest: str, now: datetime
    ) -> ReviewCandidate:
        if not secrets.compare_digest(token, self.token):
            raise ReviewSelectionError("selection tokenが一致しません")
        if now >= self.expires_at:
            raise ReviewSelectionError("selection tokenの期限が切れています")
        if not secrets.compare_digest(artifact_digest, self.artifact_digest):
            raise ReviewSelectionError("artifact digestが一致しません")
        candidate = next((item for item in self.candidates if item.id == candidate_id), None)
        if candidate is None:
            raise ReviewSelectionError(f"許可されていない候補です: {candidate_id}")
        return candidate
