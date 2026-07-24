"""Google upload SDK boundary."""

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


def create_media_upload(path: str, *, chunksize: int = -1, resumable: bool = True):
    """Create the SDK media body at the infrastructure boundary."""
    return MediaFileUpload(path, chunksize=chunksize, resumable=resumable)


__all__ = ["HttpError", "MediaFileUpload", "create_media_upload"]
