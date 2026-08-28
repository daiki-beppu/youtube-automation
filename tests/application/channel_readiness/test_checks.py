"""Application tests for channel readiness probes."""

from youtube_automation.application.channel_readiness import checks


def test_gcloud_check_uses_injected_run_probe():
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return 0, "Google Cloud SDK 552.0.0\n", ""

    with checks.use_probes(checks.ReadinessProbes(run=run)):
        result = checks.check_gcloud()

    assert result.status == "ok"
    assert calls == [["gcloud", "--version"]]
