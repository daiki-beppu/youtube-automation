from collections.abc import Callable

from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.errors import AutomationError


def run_upload_cli(
    operation: Callable[[], None],
    *,
    failure_message: str,
    interrupt_message: str,
    interrupt_exit_code: int | None,
) -> None:
    try:
        operation()
    except KeyboardInterrupt:
        print(f"\n🛑 {interrupt_message}")
        if interrupt_exit_code is not None:
            raise SystemExit(interrupt_exit_code) from None
    except (AutomationError, OSError, ValueError) as exc:
        print(f"❌ {failure_message}: {redact_sensitive_data(str(exc))}")
        raise SystemExit(1) from None
