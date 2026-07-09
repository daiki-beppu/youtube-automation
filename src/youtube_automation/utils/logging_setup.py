"""標準化されたログ設定。

Usage:
    from youtube_automation.utils.logging_setup import setup_logging

    logger = setup_logging(__name__)
    logger.info("処理開始")
"""

import logging


def setup_logging(name: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """ログ設定を行い、logger を返す。

    Args:
        name: ロガー名（通常 __name__）
        level: ログレベル

    Returns:
        設定済み Logger インスタンス
    """
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )
    return logging.getLogger(name or __name__)
