"""セットアップ入口がチャンネルルート dotenv を管理しないことの contract test."""

from pathlib import Path

from youtube_automation.cli import channel_init_templates, doctor

ROOT = Path(__file__).resolve().parents[1]
CHANNEL_NEW_REFERENCES = ROOT / ".claude" / "skills" / "channel-new" / "references"


def test_doctor_has_no_env_file_check_or_writer() -> None:
    assert not hasattr(doctor, "check_env_file")
    assert not hasattr(doctor, "write_env_defaults")


def test_channel_init_does_not_generate_env() -> None:
    assert Path(".env") not in channel_init_templates.ROOT_TEXT_TEMPLATES


def test_gcp_setup_scripts_do_not_accept_or_write_env_file() -> None:
    for name in ("gcp-bootstrap.sh", "gcp-terraform-apply.sh"):
        source = (CHANNEL_NEW_REFERENCES / name).read_text(encoding="utf-8")
        assert "--env-file" not in source
        assert "ENV_FILE" not in source
        assert "write_env_var" not in source


def test_canonical_and_bundled_terraform_contracts_match_without_env_outputs() -> None:
    canonical = ROOT / "infra" / "terraform" / "gcp"
    bundled = CHANNEL_NEW_REFERENCES / "terraform-gcp"
    for name in ("outputs.tf", "variables.tf"):
        canonical_text = (canonical / name).read_text(encoding="utf-8")
        assert canonical_text == (bundled / name).read_text(encoding="utf-8")
        assert 'output "env_vars"' not in canonical_text
        assert 'variable "location"' not in canonical_text
