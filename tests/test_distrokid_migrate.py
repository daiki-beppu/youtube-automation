"""yt-distrokid-migrate CLI のユニットテスト（#813）.

旧 distrokid.json（フラット 6 文字列の profile）を新 schema
（nested songwriter + ai_disclosure、artist_name / apple_music_credit / track_type を drop）
へ in-place 変換する移行ツール。`yt-config-migrate` の dry-run/`--apply`/backup パターンを踏襲した
単一目的 CLI（サブコマンドなし）。

定義する契約（draft が実装する前提）:
- `main(argv) -> int`（`config/channel/distrokid.json` を対象に変換）
- `--target DIR`（既定: CHANNEL_DIR / 祖先探索で解決）
- 引数なし = dry-run（プレビューのみ、書き込みなし）／`--apply` = 実書き込み
- `--backup`（既定 True、`--no-backup` で無効化）で distrokid.json.bak を残す
- songwriter 文字列 "First Last" → {first, last}、3 語以上は middle に中間語
- ai_disclosure は新 schema の default を付与
- 変換後は新 loader（utils.config）で読み込めること
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.cli.distrokid_migrate import main
from youtube_automation.utils.config import load_config
from youtube_automation.utils.config import reset as reset_config


@pytest.fixture(autouse=True)
def _auto_reset(monkeypatch):
    """CHANNEL_DIR を毎テスト前後にクリアし、新 loader シングルトンをリセット."""
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    reset_config()
    yield
    reset_config()


# ----------------------- helpers -----------------------


def _old_distrokid(*, enabled: bool = True, songwriter: str = "Jane Doe") -> dict:
    """PR #803 当時の旧フラット schema の distrokid セクション."""
    return {
        "distrokid": {
            "enabled": enabled,
            "profile": {
                "artist_name": "City Nights",
                "language": "ja",
                "main_genre": "Electronic",
                "songwriter": songwriter,
                "apple_music_credit": "Jane Doe",
                "track_type": "Instrumental",
            },
        }
    }


def _write_distrokid(target: Path, data: dict) -> Path:
    path = target / "config" / "channel" / "distrokid.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _setup_minimal_channel(target: Path) -> None:
    """変換後に新 loader が通るための最小 meta/content/youtube を置く."""
    channel = target / "config" / "channel"
    (channel).mkdir(parents=True, exist_ok=True)
    (channel / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "Test Channel",
                    "short": "TC",
                    "youtube_handle": "@testchannel",
                    "url": "https://youtube.com/@testchannel",
                    "tagline": "Test tagline",
                }
            }
        ),
        encoding="utf-8",
    )
    (channel / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "chiptune", "style": "8-bit", "context": "RPG"},
                "tags": {"base": ["chiptune"], "themes": {"battle": ["battle music"]}},
                "descriptions": {
                    "opening": "{style} {primary} for {context}",
                    "perfect_for": ["gaming"],
                    "hashtags": ["#chiptune"],
                },
                "title": {"template": "{theme} - {activity}"},
            }
        ),
        encoding="utf-8",
    )
    (channel / "youtube.json").write_text(
        json.dumps({"youtube": {"category_id": "10", "privacy_status": "public", "language": "ja"}}),
        encoding="utf-8",
    )


# ----------------------- dry-run -----------------------


def test_migrate_dry_run_does_not_write(tmp_path):
    """Given 旧 schema の distrokid.json
    When 引数なし（dry-run）で実行
    Then rc=0 だがファイルは変更されない。
    """
    path = _write_distrokid(tmp_path, _old_distrokid())
    before = path.read_text(encoding="utf-8")

    rc = main(["--target", str(tmp_path)])

    assert rc == 0
    assert path.read_text(encoding="utf-8") == before


def test_migrate_dry_run_prints_preview(tmp_path, capsys):
    """Given 旧 schema
    When dry-run
    Then プレビュー（dry-run 表記）を出力する。
    """
    _write_distrokid(tmp_path, _old_distrokid())

    rc = main(["--target", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()


# ----------------------- apply: 変換ロジック -----------------------


def test_migrate_apply_converts_to_new_schema(tmp_path):
    """Given 旧フラット profile
    When --apply
    Then nested songwriter + ai_disclosure を持つ新 schema になる。
    """
    path = _write_distrokid(tmp_path, _old_distrokid(songwriter="Jane Doe"))

    rc = main(["--target", str(tmp_path), "--apply"])

    assert rc == 0
    profile = _read_json(path)["distrokid"]["profile"]
    assert profile["artist"] == "City Nights"
    assert profile["language"] == "ja"
    assert profile["main_genre"] == "Electronic"
    assert profile["songwriter"] == {"first": "Jane", "last": "Doe"}
    assert profile["ai_disclosure"] == {
        "enabled": True,
        "lyrics": True,
        "music": True,
        "recording_scope": "full",
        "partial_audio_type": None,
        "artist_persona": True,
        "apply_to_all": True,
    }


def test_migrate_apply_drops_legacy_fields(tmp_path):
    """Given 旧フラット profile
    When --apply
    Then artist_name は artist に変換され、apple_music_credit / track_type は drop される。
    """
    path = _write_distrokid(tmp_path, _old_distrokid())

    rc = main(["--target", str(tmp_path), "--apply"])

    assert rc == 0
    profile = _read_json(path)["distrokid"]["profile"]
    assert profile["artist"] == "City Nights"
    assert "artist_name" not in profile
    assert "apple_music_credit" not in profile
    assert "track_type" not in profile


@pytest.mark.parametrize("artist", [None, {"name": "City Nights"}, ["City Nights"]])
def test_migrate_rejects_non_string_artist(tmp_path, artist):
    """artist / artist_name は存在するなら string 必須。"""
    data = _old_distrokid()
    data["distrokid"]["profile"]["artist_name"] = artist
    _write_distrokid(tmp_path, data)

    rc = main(["--target", str(tmp_path), "--apply"])

    assert rc == 1


def test_migrate_apply_preserves_enabled_flag(tmp_path):
    """Given enabled=false の旧 schema
    When --apply
    Then enabled フラグは保持される。
    """
    path = _write_distrokid(tmp_path, _old_distrokid(enabled=False))

    rc = main(["--target", str(tmp_path), "--apply"])

    assert rc == 0
    assert _read_json(path)["distrokid"]["enabled"] is False


def test_migrate_songwriter_two_words(tmp_path):
    """Given songwriter="Jane Doe"
    When --apply
    Then {first:"Jane", last:"Doe"}（middle なし）。
    """
    path = _write_distrokid(tmp_path, _old_distrokid(songwriter="Jane Doe"))

    main(["--target", str(tmp_path), "--apply"])

    songwriter = _read_json(path)["distrokid"]["profile"]["songwriter"]
    assert songwriter["first"] == "Jane"
    assert songwriter["last"] == "Doe"
    assert songwriter.get("middle") in (None, "")


def test_migrate_songwriter_three_words_uses_middle(tmp_path):
    """Given songwriter="Jane Q Doe"
    When --apply
    Then 中間語が middle になる。
    """
    path = _write_distrokid(tmp_path, _old_distrokid(songwriter="Jane Q Doe"))

    main(["--target", str(tmp_path), "--apply"])

    songwriter = _read_json(path)["distrokid"]["profile"]["songwriter"]
    assert songwriter["first"] == "Jane"
    assert songwriter["middle"] == "Q"
    assert songwriter["last"] == "Doe"


# ----------------------- backup -----------------------


def test_migrate_apply_creates_backup_by_default(tmp_path):
    """Given 旧 schema
    When --apply（既定 backup）
    Then distrokid.json.bak が残る。
    """
    _write_distrokid(tmp_path, _old_distrokid())

    rc = main(["--target", str(tmp_path), "--apply"])

    assert rc == 0
    assert (tmp_path / "config" / "channel" / "distrokid.json.bak").is_file()


def test_migrate_apply_no_backup(tmp_path):
    """Given 旧 schema
    When --apply --no-backup
    Then .bak は作られない。
    """
    _write_distrokid(tmp_path, _old_distrokid())

    rc = main(["--target", str(tmp_path), "--apply", "--no-backup"])

    assert rc == 0
    assert not (tmp_path / "config" / "channel" / "distrokid.json.bak").is_file()


# ----------------------- idempotency / round-trip -----------------------


def test_migrate_result_loads_with_new_loader(tmp_path, monkeypatch):
    """Given 旧 schema を変換した後
    When 新 loader で読み込む
    Then enabled=true の新 profile として読める（round-trip）。
    """
    _setup_minimal_channel(tmp_path)
    _write_distrokid(tmp_path, _old_distrokid(songwriter="Jane Doe"))

    assert main(["--target", str(tmp_path), "--apply", "--no-backup"]) == 0

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    reset_config()
    config = load_config()

    assert config.distrokid.enabled is True
    assert config.distrokid.profile.language == "ja"
    assert config.distrokid.profile.songwriter.first == "Jane"
    assert config.distrokid.profile.songwriter.last == "Doe"


def test_migrate_already_new_schema_is_noop(tmp_path):
    """Given 既に新 schema の distrokid.json
    When --apply
    Then 破壊せず（nested songwriter を保持）成功する（冪等）。
    """
    new_schema = {
        "distrokid": {
            "enabled": True,
            "profile": {
                "artist": "ABYSS MI",
                "language": "ja",
                "main_genre": "Electronic",
                "songwriter": {"first": "Jane", "last": "Doe"},
                "ai_disclosure": {
                    "enabled": True,
                    "lyrics": True,
                    "music": True,
                    "recording_scope": "full",
                    "partial_audio_type": None,
                    "artist_persona": True,
                    "apply_to_all": True,
                },
            },
        }
    }
    path = _write_distrokid(tmp_path, new_schema)

    rc = main(["--target", str(tmp_path), "--apply", "--no-backup"])

    assert rc == 0
    profile = _read_json(path)["distrokid"]["profile"]
    assert profile["artist"] == "ABYSS MI"
    assert profile["songwriter"] == {"first": "Jane", "last": "Doe"}
    assert profile["ai_disclosure"]["music"] is True
    assert "composition" not in profile["ai_disclosure"]
    assert "artist_name" not in profile


def test_migrate_old_ai_disclosure_composition_renamed_to_music(tmp_path):
    """#877: 旧 ai_disclosure の composition は music にリネームされ、新フィールドが補完される。"""
    old = _old_distrokid()
    old["distrokid"]["profile"]["ai_disclosure"] = {
        "enabled": True,
        "lyrics": False,
        "composition": False,
        "partial_audio_type": None,
    }
    path = _write_distrokid(tmp_path, old)

    rc = main(["--target", str(tmp_path), "--apply", "--no-backup"])

    assert rc == 0
    ai = _read_json(path)["distrokid"]["profile"]["ai_disclosure"]
    assert "composition" not in ai
    assert ai["lyrics"] is False
    assert ai["music"] is False
    assert ai["recording_scope"] == "full"
    assert ai["artist_persona"] is True
    assert ai["apply_to_all"] is True


def test_migrate_old_partial_audio_type_derives_partial_scope(tmp_path):
    """#877: 旧 schema は recording_scope を持たず partial_audio_type のみで partial を表現した。

    recording_scope 未指定 + partial_audio_type 非 null のとき recording_scope="partial" を導出し、
    loader のクロスバリデーション（partial 非 null は recording_scope='partial' 必須）に整合させる。
    """
    old = _old_distrokid()
    old["distrokid"]["profile"]["ai_disclosure"] = {
        "enabled": True,
        "lyrics": True,
        "composition": True,
        "partial_audio_type": "vocals",
    }
    path = _write_distrokid(tmp_path, old)

    rc = main(["--target", str(tmp_path), "--apply", "--no-backup"])

    assert rc == 0
    ai = _read_json(path)["distrokid"]["profile"]["ai_disclosure"]
    assert ai["recording_scope"] == "partial"
    assert ai["partial_audio_type"] == "vocals"


def test_migrate_partial_audio_type_result_loads_with_new_loader(tmp_path, monkeypatch):
    """#877: partial_audio_type 非 null の旧 schema を変換した結果が新 loader で読めること。

    recording_scope を導出しないと loader のクロスバリデーションで ConfigError になる回帰を防ぐ。
    """
    _setup_minimal_channel(tmp_path)
    old = _old_distrokid(songwriter="Jane Doe")
    old["distrokid"]["profile"]["ai_disclosure"] = {
        "enabled": True,
        "lyrics": True,
        "composition": False,
        "partial_audio_type": "instruments",
    }
    _write_distrokid(tmp_path, old)

    assert main(["--target", str(tmp_path), "--apply", "--no-backup"]) == 0

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    reset_config()
    config = load_config()

    ai = config.distrokid.profile.ai_disclosure
    assert ai.recording_scope == "partial"
    assert ai.partial_audio_type == "instruments"
    assert ai.music is False


# ----------------------- 異常系 -----------------------


def test_migrate_missing_distrokid_json_errors(tmp_path, capsys):
    """Given distrokid.json が無い
    When 実行
    Then rc=1（fail-loud、対象不在を握り潰さない）。
    """
    (tmp_path / "config" / "channel").mkdir(parents=True)

    rc = main(["--target", str(tmp_path)])

    assert rc == 1
