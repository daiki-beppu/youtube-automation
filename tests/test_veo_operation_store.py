"""utils.veo_operation_store の単体テスト。

Issue #453: Ctrl+C 中断時に operation_id を永続化して再開可能にする。
store モジュールは pure I/O（google.genai 非依存）。
channel_root=tmp_path を kwarg で直接注入してテストする（conftest の CHANNEL_DIR 設定不要）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from youtube_automation.utils import veo_operation_store as store

# ---------------------------------------------------------------------------
# image_sha256
# ---------------------------------------------------------------------------


def test_image_sha256_tracks_content_and_reads_multiple_chunks(tmp_path: Path) -> None:
    image_path = tmp_path / "main.png"
    content = b"a" * (1024 * 1024) + b"second-chunk"
    image_path.write_bytes(content)

    assert store.image_sha256(image_path) == hashlib.sha256(content).hexdigest()

    image_path.write_bytes(content + b"-changed")
    assert store.image_sha256(image_path) == hashlib.sha256(content + b"-changed").hexdigest()


# ---------------------------------------------------------------------------
# state_path
# ---------------------------------------------------------------------------


class TestStatePath:
    """state_path() の決定的パス計算."""

    def test_returns_path_under_tmp_veo_operations(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "collections" / "foo" / "10-assets" / "loop.mp4"

        # When
        result = store.state_path(output_path, channel_root=tmp_path)

        # Then
        assert result.parts[-3] == "tmp"
        assert result.parts[-2] == "veo-operations"
        assert result.suffix == ".json"

    def test_hash_prefix_is_16_chars(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"

        # When
        result = store.state_path(output_path, channel_root=tmp_path)

        # Then: stem は sha1 の先頭 16 文字（ _HASH_LEN = 16 ）
        assert len(result.stem) == 16

    def test_hash_is_deterministic_for_same_output(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "foo" / "loop.mp4"

        # When
        first = store.state_path(output_path, channel_root=tmp_path)
        second = store.state_path(output_path, channel_root=tmp_path)

        # Then
        assert first == second

    def test_different_outputs_produce_different_keys(self, tmp_path: Path) -> None:
        # Given
        out_a = tmp_path / "a" / "loop.mp4"
        out_b = tmp_path / "b" / "loop.mp4"

        # When
        key_a = store.state_path(out_a, channel_root=tmp_path).stem
        key_b = store.state_path(out_b, channel_root=tmp_path).stem

        # Then
        assert key_a != key_b


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    """save() の書き込み・構造テスト."""

    @staticmethod
    def _image_path(tmp_path: Path) -> Path:
        image_path = tmp_path / "main.png"
        image_path.write_bytes(b"test-image")
        return image_path

    def test_creates_state_file(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"

        # When
        saved = store.save(
            output_path,
            self._image_path(tmp_path),
            "projects/veo/12345",
            "veo-3.1-fast",
            channel_root=tmp_path,
        )

        # Then
        assert saved.exists()

    def test_state_json_contains_required_keys(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"
        operation_name = "projects/veo/12345"
        model = "veo-3.1-fast"

        # When
        image_path = self._image_path(tmp_path)
        saved = store.save(output_path, image_path, operation_name, model, channel_root=tmp_path)
        data = json.loads(saved.read_text(encoding="utf-8"))

        # Then
        assert data["operation_name"] == operation_name
        assert data["output_path"] == str(output_path.resolve())
        assert data["model"] == model
        assert data["input_image_sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()

    def test_submitted_at_is_not_in_saved_state(self, tmp_path: Path) -> None:
        """submitted_at は state schema に含まれない（未使用フィールドによる契約膨張の防止）。"""
        # Given
        output_path = tmp_path / "loop.mp4"

        # When
        saved = store.save(output_path, self._image_path(tmp_path), "op-name", "veo-3.1-fast", channel_root=tmp_path)
        data = json.loads(saved.read_text(encoding="utf-8"))

        # Then: 使われていないフィールドは state に含まれない
        assert "submitted_at" not in data

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        # Given: tmp_path/tmp/veo-operations/ は未作成
        output_path = tmp_path / "loop.mp4"
        ops_dir = tmp_path / "tmp" / "veo-operations"
        assert not ops_dir.exists()

        # When
        store.save(output_path, self._image_path(tmp_path), "op-name", "model", channel_root=tmp_path)

        # Then
        assert ops_dir.exists()

    def test_atomic_write_replaces_complete_state_and_preserves_old_state_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_path = tmp_path / "loop.mp4"
        image_path = self._image_path(tmp_path)
        store.save(output_path, image_path, "op-old", "model", channel_root=tmp_path)

        saved = store.save(output_path, image_path, "op-new", "model", channel_root=tmp_path)
        assert store.load(output_path, channel_root=tmp_path)["operation_name"] == "op-new"
        tmp_remnant = saved.with_suffix(saved.suffix + ".tmp")
        assert not tmp_remnant.exists()

        store.save(output_path, image_path, "op-protected", "model", channel_root=tmp_path)
        original_write_text = Path.write_text

        def fail_tmp_write(path: Path, *args, **kwargs):
            if path == tmp_remnant:
                raise OSError("disk full")
            return original_write_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_tmp_write)
        with pytest.raises(OSError, match="disk full"):
            store.save(output_path, image_path, "op-lost", "model", channel_root=tmp_path)

        assert store.load(output_path, channel_root=tmp_path)["operation_name"] == "op-protected"
        assert not tmp_remnant.exists()

    def test_save_returns_path_to_state_file(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"
        expected = store.state_path(output_path, channel_root=tmp_path)

        # When
        result = store.save(output_path, self._image_path(tmp_path), "op-name", "model", channel_root=tmp_path)

        # Then
        assert result == expected

    def test_overwrite_existing_state(self, tmp_path: Path) -> None:
        """2 回 save しても壊れず最新データが残る."""
        # Given
        output_path = tmp_path / "loop.mp4"
        image_path = self._image_path(tmp_path)
        store.save(output_path, image_path, "op-old", "model", channel_root=tmp_path)

        # When
        saved = store.save(output_path, image_path, "op-new", "model", channel_root=tmp_path)
        data = json.loads(saved.read_text(encoding="utf-8"))

        # Then
        assert data["operation_name"] == "op-new"


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    """load() の読み込み・異常系テスト."""

    def test_returns_none_when_no_state(self, tmp_path: Path) -> None:
        # Given: state ファイルなし
        output_path = tmp_path / "loop.mp4"

        # When
        result = store.load(output_path, channel_root=tmp_path)

        # Then
        assert result is None

    def test_returns_dict_after_save(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"
        image_path = tmp_path / "main.png"
        image_path.write_bytes(b"test-image")
        store.save(output_path, image_path, "projects/veo/99", "veo-3.1-fast", channel_root=tmp_path)

        # When
        result = store.load(output_path, channel_root=tmp_path)

        # Then
        assert isinstance(result, dict)
        assert result["operation_name"] == "projects/veo/99"

    def test_returns_none_on_json_corruption(self, tmp_path: Path, capsys) -> None:
        # Given: state ファイルが壊れた JSON
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{ not valid json !!!}", encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)

        # Then: None を返して上位に例外を漏らさない
        assert result is None

    def test_read_os_error_propagates_and_preserves_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{}", encoding="utf-8")
        original_read_text = Path.read_text

        def fail_state_read(path: Path, *args, **kwargs):
            if path == state_file:
                raise PermissionError("state is unreadable")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_state_read)

        with pytest.raises(PermissionError, match="state is unreadable"):
            store.load(output_path, channel_root=tmp_path)

        assert state_file.exists()

    def test_prints_warn_on_json_corruption(self, tmp_path: Path, capsys) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("broken", encoding="utf-8")

        # When
        store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: [Warn] が stdout に出る
        assert "[Warn]" in out

    def test_load_does_not_mutate_saved_data(self, tmp_path: Path) -> None:
        """load の返り値を mutate しても次回 load に影響しない（イミュータブル保証）."""
        # Given
        output_path = tmp_path / "loop.mp4"
        image_path = tmp_path / "main.png"
        image_path.write_bytes(b"test-image")
        store.save(output_path, image_path, "op-original", "model", channel_root=tmp_path)

        # When: 返り値を mutate
        data = store.load(output_path, channel_root=tmp_path)
        assert data is not None
        data["operation_name"] = "mutated"

        # Then: 次回 load は元の値のまま
        reloaded = store.load(output_path, channel_root=tmp_path)
        assert reloaded is not None
        assert reloaded["operation_name"] == "op-original"

    def test_returns_none_on_missing_required_key(self, tmp_path: Path, capsys) -> None:
        """必須キーが欠落した state は None を返し、state ファイルを削除する（ai-review-001）。"""
        # Given: operation_name を欠落させた state を直接書き込む
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        incomplete = {
            "model": "veo-3.1-fast",
            "output_path": str(output_path.resolve()),
            "input_image_sha256": "test-hash",
        }
        state_file.write_text(json.dumps(incomplete), encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()

    def test_returns_none_on_output_path_mismatch(self, tmp_path: Path, capsys) -> None:
        """output_path が一致しない state は None を返し、state ファイルを削除する（ai-review-001）。"""
        # Given: output_path を別のパスで保存する（ハッシュ衝突を意図的に作る）
        output_path = tmp_path / "loop.mp4"
        other_path = tmp_path / "other.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        # output_path のハッシュキーを使いつつ、中身は other_path を指す不整合 state
        mismatched = {
            "operation_name": "projects/veo/mismatch",
            "model": "veo-3.1-fast",
            "output_path": str(other_path.resolve()),
            "input_image_sha256": "test-hash",
        }
        state_file.write_text(json.dumps(mismatched), encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()

    @pytest.mark.parametrize(
        "empty_field",
        ["operation_name", "model", "input_image_sha256"],
    )
    def test_accepts_empty_non_path_string_fields(self, tmp_path: Path, empty_field: str) -> None:
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "operation_name": "projects/veo/99",
            "model": "veo-3.1-fast",
            "output_path": str(output_path.resolve()),
            "input_image_sha256": "test-hash",
        }
        data[empty_field] = ""
        state_file.write_text(json.dumps(data), encoding="utf-8")

        assert store.load(output_path, channel_root=tmp_path) == data
        assert state_file.exists()

    def test_empty_output_path_is_mismatch_and_removes_state(self, tmp_path: Path, capsys) -> None:
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "operation_name": "",
                    "model": "",
                    "output_path": "",
                    "input_image_sha256": "",
                }
            ),
            encoding="utf-8",
        )

        assert store.load(output_path, channel_root=tmp_path) is None
        assert "output_path が不一致" in capsys.readouterr().out
        assert not state_file.exists()

    def test_returns_none_when_operation_name_is_not_str(self, tmp_path: Path, capsys) -> None:
        """operation_name が非文字列の state は None を返し、state ファイルを削除する（ai-review-004）。"""
        # Given: operation_name を整数で書き込む
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        invalid = {
            "operation_name": 12345,  # 非文字列
            "model": "veo-3.1-fast",
            "output_path": str(output_path.resolve()),
            "input_image_sha256": "test-hash",
        }
        state_file.write_text(json.dumps(invalid), encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()

    def test_returns_none_when_model_is_not_str(self, tmp_path: Path, capsys) -> None:
        """model が非文字列の state は None を返し、state ファイルを削除する（ai-review-004）。"""
        # Given: model を None で書き込む
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        invalid = {
            "operation_name": "projects/veo/99",
            "model": None,  # 非文字列
            "output_path": str(output_path.resolve()),
            "input_image_sha256": "test-hash",
        }
        state_file.write_text(json.dumps(invalid), encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()

    def test_returns_none_when_input_image_hash_is_not_str(self, tmp_path: Path, capsys) -> None:
        """input_image_sha256 が非文字列の state は削除する。"""
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        invalid = {
            "operation_name": "projects/veo/99",
            "model": "veo-3.1-fast",
            "output_path": str(output_path.resolve()),
            "input_image_sha256": 123,
        }
        state_file.write_text(json.dumps(invalid), encoding="utf-8")

        result = store.load(output_path, channel_root=tmp_path)

        assert result is None
        assert "input_image_sha256" in capsys.readouterr().out
        assert not state_file.exists()

    def test_returns_none_when_output_path_is_not_str(self, tmp_path: Path, capsys) -> None:
        """output_path が非文字列の state は None を返し、state ファイルを削除する（ai-review-006）。"""
        # Given: output_path を整数で書き込む（壊れた state）
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        invalid = {
            "operation_name": "projects/veo/99",
            "model": "veo-3.1-fast",
            "output_path": 123,  # 非文字列
            "input_image_sha256": "test-hash",
        }
        state_file.write_text(json.dumps(invalid), encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する（TypeError にならない）
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()

    def test_returns_none_and_removes_legacy_state_without_input_image_hash(self, tmp_path: Path, capsys) -> None:
        """入力画像識別子がない旧 state は安全側で破棄する。"""
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_state = {
            "operation_name": "projects/veo/legacy",
            "model": "veo-3.1-fast",
            "output_path": str(output_path.resolve()),
        }
        state_file.write_text(json.dumps(legacy_state), encoding="utf-8")

        result = store.load(output_path, channel_root=tmp_path)

        assert result is None
        assert "input_image_sha256" in capsys.readouterr().out
        assert not state_file.exists()

    def test_returns_none_when_state_is_json_array(self, tmp_path: Path, capsys) -> None:
        """state が JSON array ([]) の場合は None を返し、state ファイルを削除する（ai-review-005）。"""
        # Given: state が配列の有効 JSON
        output_path = tmp_path / "loop.mp4"
        state_file = store.state_path(output_path, channel_root=tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("[]", encoding="utf-8")

        # When
        result = store.load(output_path, channel_root=tmp_path)
        out = capsys.readouterr().out

        # Then: None を返し、[Warn] を出力し、state ファイルを削除する
        assert result is None
        assert "[Warn]" in out
        assert not state_file.exists()


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    """clear() の削除テスト."""

    def test_removes_existing_state(self, tmp_path: Path) -> None:
        # Given
        output_path = tmp_path / "loop.mp4"
        store.save(output_path, TestSave._image_path(tmp_path), "op-name", "model", channel_root=tmp_path)
        assert store.state_path(output_path, channel_root=tmp_path).exists()

        # When
        store.clear(output_path, channel_root=tmp_path)

        # Then
        assert not store.state_path(output_path, channel_root=tmp_path).exists()
        assert store.load(output_path, channel_root=tmp_path) is None

    def test_noop_when_no_state(self, tmp_path: Path) -> None:
        """state ファイルが存在しなくても例外を上げない."""
        # Given
        output_path = tmp_path / "loop.mp4"

        # When / Then: 例外なし
        store.clear(output_path, channel_root=tmp_path)
