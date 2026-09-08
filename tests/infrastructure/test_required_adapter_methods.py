"""Explicit adapter inheritance must not silently inherit an empty operation."""

from pathlib import Path
from types import new_class

import pytest

from youtube_automation.domains.cloud_stage_policy import StageReadiness
from youtube_automation.domains.media.image import ImageGenerationRequest, ImageGenerationResult, ImageProvider
from youtube_automation.domains.notifications import NotificationNotifier
from youtube_automation.domains.suno.downloaded.models import PromptEntriesReader, SunoModeInferer
from youtube_automation.infrastructure.notifications.discord import SecretResolver, WebhookSender
from youtube_automation.infrastructure.retry import ExecutableRequest, execute_with_retry


@pytest.mark.parametrize(
    "protocol",
    [
        StageReadiness,
        ImageProvider,
        NotificationNotifier,
        PromptEntriesReader,
        SunoModeInferer,
        SecretResolver,
        WebhookSender,
        ExecutableRequest,
    ],
)
def test_missing_adapter_operation_rejects_explicit_implementation(protocol: type) -> None:
    incomplete = new_class("IncompleteAdapter", (protocol,))
    with pytest.raises(TypeError, match="abstract"):
        incomplete()


def test_complete_explicit_request_executes_through_retry_boundary() -> None:
    class Request(ExecutableRequest[str]):
        def execute(self) -> str:
            return "complete"

    assert execute_with_retry(Request(), "request failed") == "complete"


def test_complete_explicit_readiness_exposes_properties() -> None:
    class Readiness(StageReadiness):
        @property
        def status(self) -> str:
            return "ready"

        @property
        def collection(self) -> Path:
            return Path("collection")

    value = Readiness()
    assert (value.status, value.collection) == ("ready", Path("collection"))


def test_structural_image_provider_still_satisfies_runtime_protocol() -> None:
    class Provider:
        name = "local"
        supported_aspect_ratios = ("16:9",)

        def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
            return ImageGenerationResult(success=True, saved_path=req.output_path)

    provider = Provider()
    assert isinstance(provider, ImageProvider)
    request = ImageGenerationRequest("sample", Path("image.png"), "16:9", "1K")
    assert provider.generate(request).saved_path == request.output_path
