"""``YouTubeAutoUploader`` 系で共有する定数。

``youtube_auto_uploader`` 本体と分割した mixin モジュール双方から参照されるため、
循環 import を避ける目的で依存ゼロのこのモジュールに集約する。値・意味は分割前と同一。
"""

from __future__ import annotations

UPLOAD_SOURCE_EXISTING = "existing_video"
UPLOAD_SOURCE_NEW = "new_upload"
YOUTUBE_VIDEO_URL_PREFIX = "https://www.youtube.com/watch?v="
_REUSABLE_UPLOAD_STATUSES = {"processed", "uploaded"}
