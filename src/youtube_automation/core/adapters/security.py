"""Security adapter boundary for domain modules."""

from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data

__all__ = ["redact_sensitive_data"]
