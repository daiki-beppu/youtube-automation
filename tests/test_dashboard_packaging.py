from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest


@pytest.mark.slow
def test_candidate_wheel_starts_dashboard_with_bundled_assets(tmp_path: Path) -> None:
    wheel_value = os.environ.get("YTA_CANDIDATE_WHEEL")
    if not wheel_value:
        pytest.skip("YTA_CANDIDATE_WHEEL is required for candidate wheel smoke")
    wheel = Path(wheel_value).resolve()
    environment = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(environment)], check=True, capture_output=True, text=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    command = environment / ("Scripts/yt-dashboard.exe" if os.name == "nt" else "bin/yt-dashboard")
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([]), encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [str(command), "--registry", str(registry), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    body = response.read().decode("utf-8")
                    assert response.status == 200
                    assert "YouTube Analytics Dashboard" in body
                    break
            except OSError:
                time.sleep(0.1)
        else:
            stdout, stderr = process.communicate(timeout=2)
            pytest.fail(f"installed yt-dashboard did not start\nstdout={stdout}\nstderr={stderr}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
