"""yt-channel-init CLI のユニット / 結合テスト (tmp_path ベース).

設計参考: `tests/test_config_migrate.py` のスタイルを踏襲する。
- `_auto_reset` autouse fixture で `CHANNEL_DIR` を外し、新 loader シングルトンをリセット。
- `main(argv)` 直接呼び出し → 戻り値 `rc` と stdout/stderr を assert。
- 期待 JSON は読み戻して scalar 値と必須キー存在を中心に検証 (DRY)。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from youtube_automation.cli.channel_init import (
    _resolve_target_dir,
    main,
)
from youtube_automation.utils.exceptions import ConfigError

# ----------------------- Fixtures / constants -----------------------


CHANNEL_DIR_FILES: tuple[str, ...] = (
    "meta.json",
    "content.json",
    "youtube.json",
    "analytics.json",
    "playlists.json",
    "workflow.json",
    "audio.json",
)

GITKEEP_DIRS: tuple[str, ...] = (
    "auth",
    "collections",
    "data",
    "docs/benchmarks",
    "research",
)


@pytest.fixture(autouse=True)
def _auto_reset(monkeypatch):
    """conftest が向ける `CHANNEL_DIR` を毎テスト前後にクリア + 新 loader シングルトンをリセット."""
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


# ----------------------- Helpers -----------------------


def _required_args(
    target: Path,
    *,
    short: str = "DEMO",
    name: str = "Demo Channel",
    extra: list[str] | None = None,
) -> list[str]:
    """必須引数を組み立てた argv リストを返す."""
    argv = ["--target", str(target), "--short", short, "--name", name]
    if extra:
        argv.extend(extra)
    return argv


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _channel_dir(target: Path) -> Path:
    return target / "config" / "channel"


# ===================== Case 1: 7 config ファイル全件生成 =====================


def test_main_creates_all_config_files_when_target_is_empty(tmp_path):
    # Given: 空のターゲットディレクトリ
    # When: 必須引数のみで main を実行
    rc = main(_required_args(tmp_path))

    # Then: rc=0 で 7 ファイル全てが生成される
    assert rc == 0
    channel_dir = _channel_dir(tmp_path)
    for name in CHANNEL_DIR_FILES:
        assert (channel_dir / name).is_file(), f"missing config file: {name}"


# ===================== Case 2: 5 ディレクトリ + .gitkeep =====================


def test_main_creates_canonical_directories_with_gitkeep_when_target_is_empty(tmp_path):
    # Given: 空のターゲットディレクトリ
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: 5 つのディレクトリと .gitkeep が配置される
    assert rc == 0
    for rel in GITKEEP_DIRS:
        d = tmp_path / rel
        assert d.is_dir(), f"missing directory: {rel}"
        assert (d / ".gitkeep").is_file(), f"missing .gitkeep in {rel}"


# ===================== Case 3: --short / --name が meta.json に反映 =====================


def test_meta_json_reflects_short_and_name_args(tmp_path):
    # Given: --short / --name を指定
    # When: main を実行
    rc = main(_required_args(tmp_path, short="ABC", name="Awesome BGM"))

    # Then: meta.json の channel.name / channel.short に反映される
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["name"] == "Awesome BGM"
    assert meta["channel"]["short"] == "ABC"


# ===================== Case 4: --genre / --style / --context が content.json に反映 =====================


def test_content_json_reflects_genre_style_context_args(tmp_path):
    # Given: --genre / --style / --context を明示指定
    extra = ["--genre", "chiptune", "--style", "8-bit", "--context", "RPG"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: content.json の genre セクションに反映
    assert rc == 0
    content = _read_json(_channel_dir(tmp_path) / "content.json")
    assert content["genre"]["primary"] == "chiptune"
    assert content["genre"]["style"] == "8-bit"
    assert content["genre"]["context"] == "RPG"


# ===================== Case 5: genre/style/context のデフォルト "TBD" =====================


def test_content_json_uses_tbd_defaults_when_genre_style_context_omitted(tmp_path):
    # Given: --genre / --style / --context を省略
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: 3 つとも "TBD" が入る
    assert rc == 0
    content = _read_json(_channel_dir(tmp_path) / "content.json")
    assert content["genre"]["primary"] == "TBD"
    assert content["genre"]["style"] == "TBD"
    assert content["genre"]["context"] == "TBD"


# ===================== Case 6: youtube.json 固定値 =====================


def test_youtube_json_has_expected_defaults(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: SKILL.md Step 4 と同等の固定値
    assert rc == 0
    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert youtube["youtube"]["category_id"] == "10"
    assert youtube["youtube"]["privacy_status"] == "public"
    assert youtube["youtube"]["language"] == "en"


# ===================== Case 7: analytics.json benchmark セクションの既定 =====================


def test_analytics_json_has_default_benchmark_parameters(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: benchmark セクションに SKILL.md Step 4 と同等のキーが揃う
    assert rc == 0
    analytics = _read_json(_channel_dir(tmp_path) / "analytics.json")
    bm = analytics["benchmark"]
    assert bm["channels"] == []
    assert "scan_recent" in bm
    assert "min_views" in bm
    assert "freshness_days" in bm
    assert "analyze_thumbnails" in bm


# ===================== Case 8: playlists / workflow / audio は空テンプレ =====================


def test_empty_template_files_are_generated_as_valid_json(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: 3 ファイルとも json.loads 可能で空テンプレ相当
    assert rc == 0
    for name in ("playlists.json", "workflow.json", "audio.json"):
        path = _channel_dir(tmp_path) / name
        assert path.is_file()
        data = _read_json(path)
        assert isinstance(data, dict)


# ===================== Case 9: stdout サマリーに created ラベル =====================


def test_stdout_summary_lists_created_files_and_directories(tmp_path, capsys):
    # Given: 空のターゲット
    # When: main 実行
    rc = main(_required_args(tmp_path))
    out = capsys.readouterr().out

    # Then: サマリーに各ファイル名 + ディレクトリ名 + created ラベル
    assert rc == 0
    assert "created" in out
    # 代表的なファイル名・ディレクトリ名が出力されている
    assert "meta.json" in out
    assert "analytics.json" in out
    assert "auth" in out
    assert "docs/benchmarks" in out


# ===================== Case 10: 冪等性（2 回実行で skip） =====================


def test_main_is_idempotent_and_skips_existing_files_on_second_run(tmp_path, capsys):
    # Given: 1 回目で全て作成済み
    assert main(_required_args(tmp_path)) == 0
    capsys.readouterr()  # clear

    # When: 同じ引数で 2 回目を実行
    rc = main(_required_args(tmp_path))
    out = capsys.readouterr().out

    # Then: rc=0、サマリーは skip 主体
    assert rc == 0
    assert "skip" in out
    # 既存ファイルは内容が壊れていない
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["name"] == "Demo Channel"


# ===================== Case 11: --force で既存ファイルを上書き =====================


def test_force_flag_overwrites_existing_files_with_new_values(tmp_path):
    # Given: 1 回目で "Old Name" 生成
    assert main(_required_args(tmp_path, name="Old Name")) == 0
    meta1 = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta1["channel"]["name"] == "Old Name"

    # When: --force 付きで "New Name" を指定
    rc = main(_required_args(tmp_path, name="New Name", extra=["--force"]))

    # Then: rc=0、meta.json が上書きされる
    assert rc == 0
    meta2 = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta2["channel"]["name"] == "New Name"


# ===================== Case 12: 日本語 --name が UTF-8 raw 出力 =====================


def test_japanese_name_is_written_as_raw_utf8(tmp_path):
    # Given: 日本語の --name
    name = "テストチャンネル"

    # When: main 実行
    rc = main(_required_args(tmp_path, name=name))

    # Then: ファイルテキストに raw UTF-8、末尾改行付き、json.loads 可
    assert rc == 0
    path = _channel_dir(tmp_path) / "meta.json"
    text = path.read_text(encoding="utf-8")
    assert name in text  # raw UTF-8（\uXXXX エスケープではない）
    assert text.endswith("\n"), "末尾改行が必要"
    data = json.loads(text)
    assert data["channel"]["name"] == name


# ===================== Case 13: CHANNEL_DIR 環境変数からターゲット解決 =====================


def test_target_resolves_from_channel_dir_env_var(tmp_path, monkeypatch):
    # Given: CHANNEL_DIR 環境変数を tmp_path に設定、--target は省略
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    # When: --target なしで main 実行
    rc = main(["--short", "DEMO", "--name", "Demo Channel"])

    # Then: tmp_path 配下に生成される
    assert rc == 0
    assert (_channel_dir(tmp_path) / "meta.json").is_file()


# ===================== Case 14: CWD からターゲット解決 =====================


def test_target_resolves_from_cwd_when_target_and_env_omitted(tmp_path, monkeypatch):
    # Given: CWD を tmp_path に変更、--target / CHANNEL_DIR とも省略
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    # When: --target なしで main 実行
    rc = main(["--short", "DEMO", "--name", "Demo Channel"])

    # Then: CWD 配下 (tmp_path) に生成
    assert rc == 0
    assert (_channel_dir(tmp_path) / "meta.json").is_file()


# ===================== Case 15: pyproject.toml entry point 登録 =====================


def test_pyproject_registers_yt_channel_init_entry_point():
    # Given: リポジトリルートの pyproject.toml
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"

    # When: [project.scripts] を読む
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]

    # Then: yt-channel-init エントリが登録されている
    assert "yt-channel-init" in scripts
    assert scripts["yt-channel-init"] == "youtube_automation.cli.channel_init:main"


# ===================== Case 16: ディレクトリ既存・.gitkeep 不在 =====================


def test_main_adds_gitkeep_when_directory_exists_without_it(tmp_path):
    # Given: auth/ ディレクトリのみ手動作成（.gitkeep なし）
    (tmp_path / "auth").mkdir()

    # When: main 実行
    rc = main(_required_args(tmp_path))

    # Then: .gitkeep が作成される、ディレクトリ自体は保持
    assert rc == 0
    assert (tmp_path / "auth").is_dir()
    assert (tmp_path / "auth" / ".gitkeep").is_file()


# ===================== Case 17: 一部 config 既存・残りのみ新規 =====================


def test_main_preserves_existing_files_and_creates_only_missing_ones(tmp_path):
    # Given: meta.json のみカスタム内容で既存
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    existing_meta = {"channel": {"name": "Existing", "short": "EX"}}
    (channel_dir / "meta.json").write_text(
        json.dumps(existing_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # When: main 実行（--force なし）
    rc = main(_required_args(tmp_path))

    # Then: meta.json は保持、他のファイルは新規生成
    assert rc == 0
    meta = _read_json(channel_dir / "meta.json")
    assert meta == existing_meta
    for name in CHANNEL_DIR_FILES:
        if name == "meta.json":
            continue
        assert (channel_dir / name).is_file()


# ===================== Case 18: 差分あり + --force なし → diff 出力 + 変更なし =====================


def test_existing_file_with_diff_outputs_unified_diff_to_stderr_and_keeps_file(
    tmp_path, capsys
):
    # Given: meta.json に異なる内容を仕込む
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    original_text = json.dumps(
        {"channel": {"name": "Other", "short": "OT"}}, indent=2, ensure_ascii=False
    ) + "\n"
    (channel_dir / "meta.json").write_text(original_text, encoding="utf-8")

    # When: 異なる --name で --force なし実行
    rc = main(_required_args(tmp_path, name="Demo Channel", short="DEMO"))
    err = capsys.readouterr().err

    # Then: rc=0、unified diff が stderr に、ファイル内容は変わらない
    assert rc == 0
    assert "---" in err and "+++" in err
    assert (channel_dir / "meta.json").read_text(encoding="utf-8") == original_text


# ===================== Case 19: 内容一致時は silent skip（diff 出力なし） =====================


def test_existing_file_with_same_content_is_silently_skipped(tmp_path, capsys):
    # Given: 1 回目で生成し、stderr を clear
    assert main(_required_args(tmp_path)) == 0
    capsys.readouterr()

    # When: 同じ引数で 2 回目実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: rc=0、stderr に unified diff マーカーが出ない
    assert rc == 0
    assert "---" not in err
    assert "+++" not in err


# ===================== Case 20: --force 経路では diff を stderr に流さない =====================


def test_force_overwrite_does_not_emit_unified_diff(tmp_path, capsys):
    # Given: 異なる内容で meta.json を仕込む
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    (channel_dir / "meta.json").write_text(
        json.dumps({"channel": {"name": "Old", "short": "OT"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    # When: --force で上書き
    rc = main(_required_args(tmp_path, extra=["--force"]))
    err = capsys.readouterr().err

    # Then: rc=0、stderr に unified diff マーカーが出ない（overwrite ログのみ）
    assert rc == 0
    assert "---" not in err
    assert "+++" not in err


# ===================== Case 21: --short にハイフン・数字混じり =====================


def test_short_arg_accepts_hyphen_and_digit_opaque_string(tmp_path):
    # Given: ハイフン・数字混じりの --short
    # When: main 実行
    rc = main(_required_args(tmp_path, short="BGM-01"))

    # Then: そのまま meta.json に反映される（バリデーション過剰なし）
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["short"] == "BGM-01"


# ===================== Case 22: docs/benchmarks/.gitkeep が parent 不在から作成 =====================


def test_nested_directory_gitkeep_is_created_from_missing_parent(tmp_path):
    # Given: docs/ も存在しない空ターゲット
    assert not (tmp_path / "docs").exists()

    # When: main 実行
    rc = main(_required_args(tmp_path))

    # Then: docs/benchmarks/.gitkeep が 1 ステップで作成される
    assert rc == 0
    assert (tmp_path / "docs" / "benchmarks").is_dir()
    assert (tmp_path / "docs" / "benchmarks" / ".gitkeep").is_file()


# ===================== Case 23: scaffold 出力 → load_config() が成功する (Integration) =====================


def test_scaffold_output_is_loadable_by_new_config_loader(tmp_path, monkeypatch):
    """3 モジュール横断 Integration: cli → loader → dataclass."""
    # Given: scaffold を実行して 7 config を生成
    assert main(_required_args(tmp_path, short="DEMO", name="Demo Channel")) == 0

    # When: CHANNEL_DIR を scaffold ターゲットに向けて load_config()
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    from youtube_automation.utils.config import load_config, reset

    reset()
    config = load_config()

    # Then: ConfigError を出さず、scaffold で渡した値が読み取れる
    assert config.meta.channel_name == "Demo Channel"
    assert config.meta.channel_short == "DEMO"
    assert config.youtube.api.category_id == "10"
    assert config.youtube.api.privacy_status == "public"
    assert config.youtube.api.language == "en"


# ===================== Case 24: --short 欠落で SystemExit =====================


def test_main_exits_when_short_is_missing(tmp_path, capsys):
    # Given/When: --short を省略
    with pytest.raises(SystemExit):
        main(["--target", str(tmp_path), "--name", "Demo Channel"])

    # Then: stderr に該当引数名が出る
    err = capsys.readouterr().err
    assert "--short" in err or "short" in err


# ===================== Case 25: --name 欠落で SystemExit =====================


def test_main_exits_when_name_is_missing(tmp_path, capsys):
    # Given/When: --name を省略
    with pytest.raises(SystemExit):
        main(["--target", str(tmp_path), "--short", "DEMO"])

    # Then: stderr に該当引数名が出る
    err = capsys.readouterr().err
    assert "--name" in err or "name" in err


# ===================== Case 26: --target 不在パスで rc=1 =====================


def test_main_returns_error_when_target_path_does_not_exist(tmp_path, capsys):
    # Given: 存在しないターゲットパス
    missing = tmp_path / "does-not-exist"

    # When: main 実行
    rc = main(_required_args(missing))
    err = capsys.readouterr().err

    # Then: rc=1, stderr にエラーメッセージ, ファイル未生成
    assert rc == 1
    assert err.strip() != ""
    assert not (missing / "config").exists()


# ===================== Case 27: CHANNEL_DIR が存在しないパスで ConfigError =====================


def test_resolve_target_dir_raises_when_channel_dir_env_missing(tmp_path, monkeypatch):
    # Given: CHANNEL_DIR が存在しないパスを指す
    missing = tmp_path / "no-such-dir"
    monkeypatch.setenv("CHANNEL_DIR", str(missing))

    # When/Then: _resolve_target_dir(None) で ConfigError
    with pytest.raises(ConfigError):
        _resolve_target_dir(None)
