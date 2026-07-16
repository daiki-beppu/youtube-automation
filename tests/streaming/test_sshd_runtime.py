"""cloud-init が生成する sshd host-key 契約の実行時テスト。"""

from __future__ import annotations

import getpass
import shutil
import socket
import subprocess
import time
from pathlib import Path

import yaml

from tests.helpers.hcl import read_file
from tests.streaming._helpers import _CLOUD_INIT_YAML


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def _generate_key(path: Path, algorithm: str) -> None:
    _run(["ssh-keygen", "-q", "-t", algorithm, "-N", "", "-f", str(path)])


def _host_key_drop_in() -> str:
    cloud_config = yaml.safe_load(read_file(_CLOUD_INIT_YAML))
    entry = next(
        item for item in cloud_config["write_files"] if item["path"] == "/etc/ssh/sshd_config.d/99-hostkey-ed25519.conf"
    )
    return entry["content"]


def _reserve_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_listener(port: int, process: subprocess.Popen[str]) -> None:
    for _ in range(50):
        if process.poll() is not None:
            _, stderr = process.communicate()
            raise AssertionError(f"sshd exited before listening: {stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("sshd did not start listening")


def test_drop_in_enables_only_ed25519_even_when_other_host_keys_exist(tmp_path: Path) -> None:
    sshd = shutil.which("sshd")
    assert sshd is not None, "OpenSSH server is required for the host-key contract test"
    for algorithm in ("ed25519", "rsa", "ecdsa"):
        _generate_key(tmp_path / f"ssh_host_{algorithm}_key", algorithm)

    drop_in = tmp_path / "99-hostkey-ed25519.conf"
    drop_in.write_text(
        _host_key_drop_in().replace("/etc/ssh/ssh_host_ed25519_key", str(tmp_path / "ssh_host_ed25519_key")),
        encoding="utf-8",
    )
    config = tmp_path / "sshd_config"
    config.write_text(f"Include {drop_in}\n", encoding="utf-8")

    effective = _run([sshd, "-T", "-f", str(config)]).stdout.splitlines()
    host_keys = [line.split(maxsplit=1)[1] for line in effective if line.startswith("hostkey ")]

    assert host_keys == [str(tmp_path / "ssh_host_ed25519_key")]


def test_expected_host_key_connects_and_different_key_is_rejected(tmp_path: Path) -> None:
    sshd = shutil.which("sshd")
    assert sshd is not None, "OpenSSH server is required for the host-key contract test"
    host_key = tmp_path / "ssh_host_ed25519_key"
    wrong_host_key = tmp_path / "wrong_host_key"
    client_key = tmp_path / "client_key"
    for key in (host_key, wrong_host_key, client_key):
        _generate_key(key, "ed25519")

    authorized_keys = tmp_path / "authorized_keys"
    authorized_keys.write_text(client_key.with_suffix(".pub").read_text(encoding="utf-8"), encoding="utf-8")
    port = _reserve_port()
    config = tmp_path / "sshd_config"
    config.write_text(
        "\n".join(
            (
                "ListenAddress 127.0.0.1",
                f"Port {port}",
                f"HostKey {host_key}",
                f"PidFile {tmp_path / 'sshd.pid'}",
                f"AuthorizedKeysFile {authorized_keys}",
                "StrictModes no",
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "PubkeyAuthentication yes",
                "UsePAM no",
                "LogLevel ERROR",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _run([sshd, "-t", "-f", str(config)])
    process = subprocess.Popen(
        [sshd, "-D", "-e", "-f", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_listener(port, process)
        destination = f"[{socket.gethostbyname('localhost')}]:{port}"
        expected_known_hosts = tmp_path / "known_hosts"
        wrong_known_hosts = tmp_path / "wrong_known_hosts"
        expected_known_hosts.write_text(
            f"{destination} {host_key.with_suffix('.pub').read_text(encoding='utf-8')}",
            encoding="utf-8",
        )
        wrong_known_hosts.write_text(
            f"{destination} {wrong_host_key.with_suffix('.pub').read_text(encoding='utf-8')}",
            encoding="utf-8",
        )
        base_command = [
            "ssh",
            "-F",
            "none",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=3",
            "-i",
            str(client_key),
            "-p",
            str(port),
        ]
        target = f"{getpass.getuser()}@127.0.0.1"

        accepted = _run(
            [*base_command, "-o", f"UserKnownHostsFile={expected_known_hosts}", target, "true"],
            check=False,
        )
        rejected = _run(
            [*base_command, "-o", f"UserKnownHostsFile={wrong_known_hosts}", target, "true"],
            check=False,
        )

        assert accepted.returncode == 0, accepted.stderr
        assert rejected.returncode != 0
        assert "REMOTE HOST IDENTIFICATION HAS CHANGED" in rejected.stderr
    finally:
        process.terminate()
        process.wait(timeout=5)
