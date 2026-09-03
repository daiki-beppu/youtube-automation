from google.genai import types


def test_agentic_media_processing_is_available() -> None:
    media_processing = types.MediaProcessing.AGENTIC

    part = types.Part(media_processing=media_processing)

    assert part.media_processing == media_processing
