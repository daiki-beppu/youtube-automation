"""MediaStore の local / R2 adapter。"""

from youtube_automation.infrastructure.media_store.local import LocalMediaStore
from youtube_automation.infrastructure.media_store.r2 import R2MediaStore, R2MediaStoreConfig

__all__ = ["LocalMediaStore", "R2MediaStore", "R2MediaStoreConfig"]
