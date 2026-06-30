"""tests/streaming/ パッケージ内で共有するパス定数とヘルパー。

issue #426: ``tests/test_terraform_streaming.py`` (3580 行 / 26 クラス) を責務別
ファイルに分割した際の共有モジュール。
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STREAMING_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"

_VERSIONS_TF = _STREAMING_DIR / "versions.tf"
_VARIABLES_TF = _STREAMING_DIR / "variables.tf"
_MAIN_TF = _STREAMING_DIR / "main.tf"
_OUTPUTS_TF = _STREAMING_DIR / "outputs.tf"
_TFVARS_EXAMPLE = _STREAMING_DIR / "terraform.tfvars.example"
_ROOT_GITIGNORE = _REPO_ROOT / ".gitignore"
_CLOUD_INIT_YAML = _STREAMING_DIR / "cloud-init.yaml"
_SYSTEMD_TFTPL = _STREAMING_DIR / "templates" / "youtube-stream.service.tftpl"
_ENV_TFTPL = _STREAMING_DIR / "templates" / "youtube-stream.env.tftpl"
_LOGROTATE_TFTPL = _STREAMING_DIR / "templates" / "logrotate.conf.tftpl"
_CRON_D_TFTPL = _STREAMING_DIR / "templates" / "cron.d.tftpl"
_STREAMING_README = _STREAMING_DIR / "README.md"
_VIDEO_PREFLIGHT_PY = _STREAMING_DIR / "video_preflight.py"
_STREAMING_SKILL = _REPO_ROOT / ".claude" / "skills" / "streaming" / "SKILL.md"

_SCRIPTS_STREAMING_DIR = _REPO_ROOT / ".claude" / "skills" / "streaming" / "references"
_SWAP_VIDEO_SCRIPT = _SCRIPTS_STREAMING_DIR / "swap_video.sh"
_RUN_FFMPEG_SCRIPT = _SCRIPTS_STREAMING_DIR / "run-ffmpeg.sh"

_TFSTATE_BACKEND_PREFIX = "streaming"
_TFSTATE_GCS_OBJECT = "streaming/default.tfstate"
_DEFAULT_INSTALL_ROOT = "/opt/youtube-stream"
_INSTALL_ROOT_TFTPL = r"\$\{install_root\}"
_INSTALL_ROOT_VAR = r"\$\{var\.install_root\}"


# ---------- ヘルパー ----------


def _extract_yaml_packages_block(text: str) -> str | None:
    """``packages:`` キー直下のリストブロック（インデント行の連続）を 1 つ抜き出す。

    ``packages:`` 行から、次のトップレベルキー（インデント無し行）または EOF までを
    1 つのテキストとして返す。`cloud-init.yaml` の `- ffmpeg` / `- unattended-upgrades`
    などのアイテム判定に使う。マッチしない場合は ``None``。
    """
    match = re.search(
        r"^packages:\s*\n((?:[ \t]+.*\n)+)",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None
