"""scripts/generate_loop_video.py の CLI 引数パーサ・制御フローのユニットテスト

Issue #129: `--model` choices 撤廃の regression（既存 11 ケース）
Issue #358: `--motion-targets` / `--static-targets` の構造化プロンプト対応と
            `resolve_prompt` の優先順位制御
Issue #451: `--skip-existing` フラグ追加、`--smooth` の post-process 専用化
           （`main()` 制御フロー検証 + `resolve_collection_paths` の pure 化検証）
Issue #1747: 既定 prompt_template から強度断定（subtle 等）を除去し、
             動きの強度は motion_targets の文言のみで制御する regression

検証対象:
1. `_build_parser`: `--skip-existing` / 構造化プロンプト系を含む全フラグの parse
2. `resolve_prompt`: 純関数の優先順位制御（CLI > config > default）
3. `resolve_collection_paths`: pure 化（rename 副作用ゼロ・validation ゼロ）
4. `_backup_existing_loop`: 既存 `loop.mp4` を `loop-v{n}.mp4` へ rename
5. `main()`: smooth 早期分岐 / skip-existing 早期分岐 / 通常経路の 3 分岐

外部 IO（Vertex AI / load_skill_config / load_dotenv / 実 stdin 等）は touch しない。
Veo 実 API は再課金リスクのため絶対に叩かない（全ケース mock）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import DEFAULT, patch

import pytest

from youtube_automation.scripts.generate_loop_video import (
    _build_parser,
    resolve_collection_paths,
    resolve_prompt,
)
from youtube_automation.utils.veo_generator import DEFAULT_PROMPT

# NOTE: `_backup_existing_loop` は本 issue で新規追加される関数。
# write_tests phase では未実装のため、module top では import せず、
# テスト関数内で lazy import する（既存 11 ケースの parser regression を
# collection 段階でブロックしないため）。

# ---------------------------------------------------------------------------
# 定数: マジックストリングを 1 箇所に集約
# ---------------------------------------------------------------------------

ASSETS_DIR = "10-assets"
MAIN_PNG = "main.png"
MAIN_JPG = "main.jpg"
LOOP_MP4 = "loop.mp4"
LOOP_V1 = "loop-v1.mp4"
LOOP_V2 = "loop-v2.mp4"
LOOP_V3 = "loop-v3.mp4"

# `patch.multiple` で `main()` の境界を一括 mock する対象モジュール
_TARGET_MODULE = "youtube_automation.scripts.generate_loop_video"


def _make_collection(tmp_path: Path, *, name: str = "20260519-loop-foo") -> Path:
    """tmp_path 配下にコレクションディレクトリと `10-assets/` を作って返す。"""
    col = tmp_path / name
    (col / ASSETS_DIR).mkdir(parents=True)
    return col


def _write_image(col: Path, filename: str = MAIN_PNG) -> Path:
    """`10-assets/<filename>` に空ファイルを置く。"""
    path = col / ASSETS_DIR / filename
    path.write_bytes(b"\x00")
    return path


def _write_loop_mp4(col: Path, filename: str = LOOP_MP4, *, payload: bytes = b"loop") -> Path:
    """`10-assets/<filename>` に空ファイルを置く。"""
    path = col / ASSETS_DIR / filename
    path.write_bytes(payload)
    return path


# ---------------------------------------------------------------------------
# 1. _build_parser regression (#129) と --skip-existing 追加 (#451)
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argument_parser(self):
        # Given/When
        parser = _build_parser()

        # Then
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_accepts_lite_preview_model(self):
        # Given: Issue #129 のメインケース。preview モデルを CLI から指定可能。
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-lite-generate-preview"])

        # Then
        assert args.model == "veo-3.1-lite-generate-preview"

    def test_parser_accepts_arbitrary_model_string(self):
        # Given: choices 撤廃の証跡。Veo の preview/GA リリースサイクルに追従するため
        # 未知モデル文字列も argparse 段階では弾かない（API 側でエラーになる前提）。
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "some-future-model-id"])

        # Then
        assert args.model == "some-future-model-id"

    def test_parser_accepts_legacy_fast_model(self):
        # Given: 旧 model（fast）の regression
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-fast-generate-001"])

        # Then
        assert args.model == "veo-3.1-fast-generate-001"

    def test_parser_accepts_legacy_quality_model(self):
        # Given: 旧 model（quality）の regression
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-generate-001"])

        # Then
        assert args.model == "veo-3.1-generate-001"

    def test_parser_model_default_is_none(self):
        # Given: --model 未指定時は None。main() 側の
        # `args.model or veo_config.get("model", DEFAULT_MODEL)` 解決順序を壊さない。
        parser = _build_parser()

        # When
        args = parser.parse_args([])

        # Then
        assert args.model is None

    def test_parser_help_lists_lite_preview_model(self):
        # Given: SKILL.md と config.default.yaml の選択肢列挙と整合する形で
        # CLI help にも preview モデルを例示する。
        parser = _build_parser()

        # When
        help_text = parser.format_help()

        # Then
        assert "veo-3.1-lite-generate-preview" in help_text

    def test_parser_help_lists_legacy_models(self):
        # Given: help 文字列で旧 2 モデルも引き続き例示されている（discoverability 維持）。
        parser = _build_parser()

        # When
        help_text = parser.format_help()

        # Then
        assert "veo-3.1-fast-generate-001" in help_text
        assert "veo-3.1-generate-001" in help_text

    def test_parser_collection_is_optional(self):
        # Given: collection は positional だが nargs="?" で optional（CWD 解決経路を残す）。
        # この既存挙動を model 変更で壊さない regression。
        parser = _build_parser()

        # When
        args = parser.parse_args([])

        # Then
        assert args.collection is None

    def test_parser_collection_accepted_when_provided(self):
        # Given: collection 引数を渡すルート
        parser = _build_parser()

        # When
        args = parser.parse_args(["collections/example", "--model", "veo-3.1-lite-generate-preview"])

        # Then
        assert args.collection == "collections/example"
        assert args.model == "veo-3.1-lite-generate-preview"

    def test_parser_other_flags_still_parse(self):
        # Given: --prompt / --smooth / --crossfade / -y は今回触らない。regression。
        parser = _build_parser()

        # When
        args = parser.parse_args(
            [
                "--prompt",
                "test prompt",
                "--smooth",
                "--crossfade",
                "0.8",
                "-y",
            ]
        )

        # Then
        assert args.prompt == "test prompt"
        assert args.smooth is True
        assert args.crossfade == 0.8
        assert args.yes is True

    def test_parser_accepts_motion_and_static_targets(self):
        # Issue #358: 構造化プロンプト用 CLI 引数
        parser = _build_parser()

        args = parser.parse_args(
            [
                "--motion-targets",
                "leaves,steam",
                "--static-targets",
                "character,two animals (count remains 2)",
            ]
        )

        assert args.motion_targets == "leaves,steam"
        assert args.static_targets == "character,two animals (count remains 2)"

    def test_parser_motion_static_default_none(self):
        # 未指定時は None
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.motion_targets is None
        assert args.static_targets is None

    # --- Issue #451: --skip-existing フラグ ---

    def test_parser_skip_existing_is_true_when_flag_passed(self):
        # Given: 新規 --skip-existing フラグの parse 確認（R1 直接検証）
        parser = _build_parser()

        # When
        args = parser.parse_args(["--skip-existing"])

        # Then
        assert args.skip_existing is True

    def test_parser_skip_existing_defaults_to_false(self):
        # Given: フラグ未指定時の default 挙動。既存利用者の挙動を壊さない regression。
        parser = _build_parser()

        # When
        args = parser.parse_args([])

        # Then
        assert args.skip_existing is False


# ---------- resolve_prompt (Issue #358) ----------


_TEMPLATE = (
    "Static composition. The scene is a living painting: {static_clause} remain exactly as in the source image. "
    "The only motion is {motion_clause} — subtle. {base_rules} Loop seamlessly."
)
_BASE_RULES = "Preserve the original lighting."


def _args(prompt=None, motion=None, static=None) -> argparse.Namespace:
    return argparse.Namespace(prompt=prompt, motion_targets=motion, static_targets=static)


class TestResolvePrompt:
    def test_prompt_overrides_everything(self):
        # 優先順位 1: --prompt は最強
        veo_config = {
            "motion_targets": ["leaves"],
            "static_targets": ["character"],
            "prompt_template": _TEMPLATE,
            "base_rules": _BASE_RULES,
            "default_prompt": "default value",
        }
        args = _args(prompt="custom full prompt", motion="x,y", static="z")

        result = resolve_prompt(args, veo_config)

        assert result == "custom full prompt"

    def test_cli_structured_overrides_skill_config_structured(self):
        # 優先順位 2: CLI structured が skill-config の structured / default_prompt より優先
        veo_config = {
            "motion_targets": ["from-config-motion"],
            "static_targets": ["from-config-static"],
            "prompt_template": _TEMPLATE,
            "base_rules": _BASE_RULES,
            "default_prompt": "should not be used",
        }
        args = _args(motion="from-cli-motion", static="from-cli-static")

        result = resolve_prompt(args, veo_config)

        assert "from-cli-motion" in result
        assert "from-cli-static" in result
        assert "from-config-motion" not in result
        assert "should not be used" not in result

    def test_cli_motion_only_with_empty_static_uses_fallback(self):
        # CLI で motion のみ指定 → static は "the rest of the scene" にフォールバック
        veo_config = {
            "prompt_template": _TEMPLATE,
            "base_rules": "",
            "default_prompt": "should not be used",
        }
        args = _args(motion="leaves")

        result = resolve_prompt(args, veo_config)

        assert "leaves" in result
        assert "the rest of the scene" in result

    def test_skill_config_structured_used_when_cli_unspecified(self):
        # 優先順位 3: CLI 未指定で skill-config の structured が非空
        veo_config = {
            "motion_targets": ["config-motion"],
            "static_targets": ["config-static"],
            "prompt_template": _TEMPLATE,
            "base_rules": "",
            "default_prompt": "should not be used",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert "config-motion" in result
        assert "config-static" in result
        assert "should not be used" not in result

    def test_default_prompt_used_when_structured_empty(self):
        # 優先順位 4: structured 系すべて空 → default_prompt
        veo_config = {
            "motion_targets": [],
            "static_targets": [],
            "prompt_template": _TEMPLATE,
            "default_prompt": "channel default prompt",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == "channel default prompt"

    def test_hardcoded_default_used_when_no_config(self):
        # 優先順位 5: skill-config が完全に空
        veo_config: dict = {}
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == DEFAULT_PROMPT

    def test_structured_skipped_when_template_missing(self):
        # prompt_template が無い場合は structured 構築をスキップして default_prompt
        veo_config = {
            "motion_targets": ["leaves"],
            "static_targets": ["character"],
            "default_prompt": "fallback default",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == "fallback default"

    def test_cli_static_only_falls_through_to_skill_config(self, capsys):
        # CLI で static のみ指定 → CLI structured 試行 → motion 空で ValueError →
        # skill-config の motion_targets が非空ならそちらを採用するが、
        # static は CLI 側を優先したいケースは現仕様では非サポート（warning 後 fallback）
        veo_config = {
            "motion_targets": [],
            "static_targets": [],
            "prompt_template": _TEMPLATE,
            "default_prompt": "channel default",
        }
        args = _args(static="character")

        result = resolve_prompt(args, veo_config)

        # CLI motion 空 → structured 構築失敗 → default_prompt
        assert result == "channel default"
        captured = capsys.readouterr()
        assert "CLI structured prompt 構築失敗" in captured.out

    def test_prompt_with_structured_warns(self, capsys):
        # --prompt 指定 + --motion-targets 指定 → warning 出して --prompt 優先
        veo_config = {"prompt_template": _TEMPLATE}
        args = _args(prompt="full", motion="leaves", static="character")

        result = resolve_prompt(args, veo_config)

        assert result == "full"
        captured = capsys.readouterr()
        assert "--prompt が指定されたため" in captured.out


# ---------- 強度制御は motion_targets の文言のみで行う (Issue #1747) ----------

# 同梱 default config を実物のまま検証する（外部 IO ではなくリポジトリ内資産の読み取り）。
_LOOP_VIDEO_DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[1] / ".claude" / "skills" / "loop-video" / "config.default.yaml"
)

# 既定 template が付加してはいけない強度断定語（issue #1747 の regression 対象）
_INTENSITY_SOFTENERS = ("subtle", "gentle", "barely perceptible")


def _default_veo_config() -> dict:
    import yaml

    with _LOOP_VIDEO_DEFAULT_CONFIG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["veo"]


class TestMotionIntensityControlledByTargets:
    """既定 prompt_template が {motion_clause} に強度断定を付加しないことの regression。

    旧 template は「— subtle, gentle, barely perceptible, natural.」を必ず付加し、
    "clearly rolling ocean waves" 等の強い動き指定と自己矛盾して Veo がほぼ静止画を
    生成していた（issue #1747）。強度は motion_targets の文言だけで制御する。
    """

    def test_strong_motion_targets_are_not_softened_by_default_template(self):
        # 要件 1: 強い動き指定 → subtle 等の強度断定が prompt に混入しない
        veo_config = _default_veo_config()
        args = _args(motion="clearly rolling ocean waves", static="the boat (count remains 1)")

        result = resolve_prompt(args, veo_config)

        assert "clearly rolling ocean waves" in result
        for softener in _INTENSITY_SOFTENERS:
            assert softener not in result, f"既定 template が強度断定 {softener!r} を付加している"

    def test_unspecified_targets_fall_back_to_subtle_default_prompt(self):
        # 要件 2: motion_targets 未指定 → 従来同等の静的シーン向け default_prompt（後方互換）
        veo_config = _default_veo_config()
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == veo_config["default_prompt"]
        assert "subtle" in result  # 静的シーン向けの微動意図が保たれている

    def test_subtle_wording_in_motion_targets_still_effective(self):
        # 強度語を motion_targets 側に書けば従来どおり微動指定になる
        veo_config = _default_veo_config()
        args = _args(motion="subtle steam rising from coffee")

        result = resolve_prompt(args, veo_config)

        assert "subtle steam rising from coffee" in result

    def test_channel_prompt_template_override_still_applied(self):
        # 要件 3: チャンネル側 prompt_template 上書きは引き続き有効
        # （チャンネル判断で強度文言を template に戻すことも可能）
        veo_config = _default_veo_config()
        veo_config["prompt_template"] = (
            "Channel override: the only motion is {motion_clause} — extremely subtle. {base_rules}"
        )
        veo_config["base_rules"] = "Channel rules."
        args = _args(motion="ocean waves")

        result = resolve_prompt(args, veo_config)

        assert result == "Channel override: the only motion is ocean waves — extremely subtle. Channel rules."


# ---------------------------------------------------------------------------
# 2. resolve_collection_paths: pure 化（副作用ゼロ・validation ゼロ）
# ---------------------------------------------------------------------------


class TestResolveCollectionPaths:
    """plan §3 で pure 化対象。rename 副作用は `_backup_existing_loop` に切り出す前提。"""

    def test_returns_main_png_and_loop_mp4_for_collection(self, tmp_path):
        # Given: 10-assets/main.png のみを配置
        col = _make_collection(tmp_path)
        png = _write_image(col, MAIN_PNG)

        # When
        image_path, output_path = resolve_collection_paths(col)

        # Then
        assert image_path == png
        assert output_path == col / ASSETS_DIR / LOOP_MP4

    def test_falls_back_to_main_jpg_when_main_png_missing(self, tmp_path):
        # Given: main.jpg のみ（png 不在）
        col = _make_collection(tmp_path)
        jpg = _write_image(col, MAIN_JPG)

        # When
        image_path, output_path = resolve_collection_paths(col)

        # Then
        assert image_path == jpg
        assert output_path == col / ASSETS_DIR / LOOP_MP4

    def test_returns_paths_without_raising_when_both_images_missing(self, tmp_path):
        # Given: png/jpg いずれも不在（pure: validation は呼出側の責務）
        col = _make_collection(tmp_path)

        # When
        image_path, output_path = resolve_collection_paths(col)

        # Then: raise せず Path を返す。両不在時は main.png path を返す（test-design.md #4b）。
        # validation（exists 確認 → exit 1）は呼出側 `main()` の責務であり、
        # ここでは「pure な path 算出」の不変条件のみ固定する。
        assert image_path == col / ASSETS_DIR / MAIN_PNG
        assert output_path == col / ASSETS_DIR / LOOP_MP4

    def test_does_not_rename_existing_loop_mp4(self, tmp_path):
        # Given: 既存 loop.mp4 がある状態（pure 化の最重要 invariant）
        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"original")

        # When
        resolve_collection_paths(col)

        # Then: loop.mp4 はそのまま、loop-v1.mp4 は生成されない（副作用ゼロ）
        assert loop.exists()
        assert loop.read_bytes() == b"original"
        assert not (col / ASSETS_DIR / LOOP_V1).exists()


# ---------------------------------------------------------------------------
# 3. _backup_existing_loop: rename ロジック抽出
# ---------------------------------------------------------------------------


class TestBackupExistingLoop:
    """plan §3: 既存 `loop.mp4` を `loop-v{n}.mp4` へ番号衝突回避で rename する。"""

    def test_renames_loop_mp4_to_loop_v1_when_no_backup_exists(self, tmp_path):
        from youtube_automation.scripts.generate_loop_video import _backup_existing_loop

        # Given: loop.mp4 のみ
        col = _make_collection(tmp_path)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"original")

        # When
        _backup_existing_loop(loop)

        # Then: loop.mp4 は消え、loop-v1.mp4 が作られている
        assert not loop.exists()
        v1 = col / ASSETS_DIR / LOOP_V1
        assert v1.exists()
        assert v1.read_bytes() == b"original"

    def test_picks_loop_v2_when_v1_already_taken(self, tmp_path):
        from youtube_automation.scripts.generate_loop_video import _backup_existing_loop

        # Given: loop.mp4 と既存 loop-v1.mp4
        col = _make_collection(tmp_path)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"current")
        _write_loop_mp4(col, LOOP_V1, payload=b"prev1")

        # When
        _backup_existing_loop(loop)

        # Then: loop-v2.mp4 に退避され、v1 は既存内容を保持
        v1 = col / ASSETS_DIR / LOOP_V1
        v2 = col / ASSETS_DIR / LOOP_V2
        assert not loop.exists()
        assert v1.read_bytes() == b"prev1"
        assert v2.exists()
        assert v2.read_bytes() == b"current"

    def test_picks_loop_v3_when_v1_and_v2_already_taken(self, tmp_path):
        from youtube_automation.scripts.generate_loop_video import _backup_existing_loop

        # Given: loop.mp4 + v1 + v2 すべて存在
        col = _make_collection(tmp_path)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"current")
        _write_loop_mp4(col, LOOP_V1, payload=b"prev1")
        _write_loop_mp4(col, LOOP_V2, payload=b"prev2")

        # When
        _backup_existing_loop(loop)

        # Then: loop-v3.mp4 へ退避（複数段衝突の境界値）
        v3 = col / ASSETS_DIR / LOOP_V3
        assert not loop.exists()
        assert v3.exists()
        assert v3.read_bytes() == b"current"


# ---------------------------------------------------------------------------
# 4. main(): --skip-existing 早期分岐
# ---------------------------------------------------------------------------


def _patch_main_boundaries():
    """`main()` の外部境界を一括 patch するヘルパー（patch.multiple のラッパ）。

    返り値はコンテキストマネージャ。`as mocks:` で `mocks["..."]` を取り出して操作する。

    patch 対象（test-design.md §4 モック戦略）:
      - generate_loop_video: Veo 呼出本体。`call_count == 0` を主に検証
      - smooth_loop: post-process。crossfade 伝搬等を検証
      - create_genai_client: Veo クライアント生成。non-call で課金経路遮断を立証
      - load_dotenv, find_dotenv: 外部依存遮断
      - load_config: skill-config 読み込み遮断（戻り値は空 dict を default）
    """
    return patch.multiple(
        _TARGET_MODULE,
        generate_loop_video=DEFAULT,
        smooth_loop=DEFAULT,
        create_genai_client=DEFAULT,
        load_dotenv=DEFAULT,
        find_dotenv=DEFAULT,
        load_config=DEFAULT,
    )


def _set_default_mocks(mocks: dict) -> None:
    """全 mock の return_value を「成功」相当に固定する。"""
    mocks["load_config"].return_value = {}
    mocks["generate_loop_video"].return_value = True
    mocks["smooth_loop"].return_value = None


class TestMainSkipExisting:
    """完了条件 1: 既存 `loop.mp4` がある状態で再実行しても Veo を呼ばない。"""

    def test_skips_veo_and_exits_zero_when_skip_existing_and_loop_mp4_exists(self, tmp_path, monkeypatch):
        # Given: 既存 loop.mp4 + --skip-existing
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--skip-existing"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: Veo 非呼出 + クライアント非生成 + exit 0（IR2）
            assert mocks["generate_loop_video"].call_count == 0
            assert mocks["create_genai_client"].call_count == 0
            assert excinfo.value.code == 0

    def test_does_not_create_backup_when_skipping(self, tmp_path, monkeypatch):
        # Given: 既存 loop.mp4 + --skip-existing
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"keep")
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--skip-existing"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: loop.mp4 はそのまま残り、loop-v1.mp4 は作られない（R2）
            assert loop.exists()
            assert loop.read_bytes() == b"keep"
            assert not (col / ASSETS_DIR / LOOP_V1).exists()
            assert excinfo.value.code == 0

    def test_runs_normal_path_when_skip_existing_set_but_loop_mp4_absent(self, tmp_path, monkeypatch):
        # Given: --skip-existing 指定だが loop.mp4 不在 → 通常 Veo 経路へフォールスルー
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(
            sys,
            "argv",
            ["yt-generate-loop-video", str(col), "--skip-existing", "-y"],
        )

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: Veo は呼ばれ、exit 0（フラグ単独で挙動破壊しない regression）
            assert mocks["generate_loop_video"].call_count == 1
            assert excinfo.value.code == 0

    def test_skip_path_runs_before_image_validation(self, tmp_path, monkeypatch):
        # Given: --skip-existing + loop.mp4 ありで、main.png / main.jpg いずれも欠如
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        # NOTE: 入力画像（main.png/jpg）を意図的に置かない
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--skip-existing"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: image validation より前で early-return → exit 0
            assert mocks["generate_loop_video"].call_count == 0
            assert mocks["create_genai_client"].call_count == 0
            assert excinfo.value.code == 0


# ---------------------------------------------------------------------------
# 5. main(): --smooth 早期分岐（post-process 専用 mode）
# ---------------------------------------------------------------------------


class TestMainSmooth:
    """完了条件 2: `--smooth` 単独で post-process のみ実行できる。"""

    def test_runs_smooth_loop_and_skips_veo_when_loop_mp4_exists(self, tmp_path, monkeypatch):
        # Given: 既存 loop.mp4 + --smooth
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: smooth_loop のみ呼ばれ、Veo は非呼出、exit 0
            assert mocks["smooth_loop"].call_count == 1
            assert mocks["generate_loop_video"].call_count == 0
            assert mocks["create_genai_client"].call_count == 0
            assert excinfo.value.code == 0

    def test_does_not_prompt_for_confirmation_in_smooth_mode(self, tmp_path, monkeypatch):
        # Given: --smooth 経路では Veo 用の "生成しますか？" prompt を出さない（IR3）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        # `input()` が呼ばれたら即 fail（Veo 確認 prompt は誤誘導なので出してはならない）
        def _fail_on_input(*_args, **_kwargs):
            pytest.fail("input() was called in --smooth mode (Veo 用 prompt は出してはならない)")

        monkeypatch.setattr("builtins.input", _fail_on_input)

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When/Then: -y 無しでも exit 0 で正常終了する
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 0

    def test_passes_crossfade_value_to_smooth_loop(self, tmp_path, monkeypatch):
        # Given: --crossfade 0.8 を CLI 経由で指定
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        loop = _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(
            sys,
            "argv",
            ["yt-generate-loop-video", str(col), "--smooth", "--crossfade", "0.8"],
        )

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: smooth_loop に loop.mp4 path と crossfade=0.8 が伝搬する
            assert excinfo.value.code == 0
            call = mocks["smooth_loop"].call_args
            positional = list(call.args)
            kwargs = call.kwargs

            # 第 1 引数は loop.mp4 path（positional or keyword）
            output_arg = positional[0] if positional else kwargs.get("output_path")
            assert output_arg == loop

            # crossfade 値は 0.8（positional 2nd or kwargs["crossfade"]）
            crossfade_value = positional[1] if len(positional) >= 2 else kwargs.get("crossfade")
            assert crossfade_value == 0.8

    def test_exits_with_code_1_when_loop_mp4_is_absent(self, tmp_path, monkeypatch):
        # Given: --smooth 指定だが loop.mp4 が存在しない（IR1: post-process 専用の入力欠如）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        # loop.mp4 を意図的に置かない
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When/Then: エラー握りつぶし禁止 → SystemExit(1)
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 1

            # smooth_loop も Veo も呼ばれてはならない（無音破壊回避）
            assert mocks["smooth_loop"].call_count == 0
            assert mocks["generate_loop_video"].call_count == 0


# ---------------------------------------------------------------------------
# 6. main(): --smooth と --skip-existing の優先順位
# ---------------------------------------------------------------------------


class TestMainSmoothPrecedence:
    """plan §3.3: 両指定時は `--smooth`（明示アクション）> `--skip-existing`（no-op）。"""

    def test_smooth_takes_precedence_over_skip_existing(self, tmp_path, monkeypatch):
        # Given: --smooth と --skip-existing を同時指定 + 既存 loop.mp4
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(
            sys,
            "argv",
            ["yt-generate-loop-video", str(col), "--smooth", "--skip-existing"],
        )

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: smooth_loop が呼ばれ、Veo は非呼出、exit 0
            assert mocks["smooth_loop"].call_count == 1
            assert mocks["generate_loop_video"].call_count == 0
            assert mocks["create_genai_client"].call_count == 0
            assert excinfo.value.code == 0


# ---------------------------------------------------------------------------
# 7. main(): 通常経路 regression（フラグ無し）
# ---------------------------------------------------------------------------


class TestMainNormal:
    """フラグ未指定時の従来挙動。`_backup_existing_loop` の結合確認も含む。"""

    def test_calls_veo_and_backs_up_existing_loop_when_no_flags(self, tmp_path, monkeypatch):
        # Given: 既存 loop.mp4 + フラグ無し（-y で confirm スキップ）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        loop = _write_loop_mp4(col, LOOP_MP4, payload=b"original")
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: Veo 呼出 + 既存 loop.mp4 は loop-v1.mp4 に退避済み + exit 0
            assert mocks["generate_loop_video"].call_count == 1
            assert not loop.exists()
            v1 = col / ASSETS_DIR / LOOP_V1
            assert v1.exists()
            assert v1.read_bytes() == b"original"
            assert excinfo.value.code == 0

    def test_calls_veo_when_no_flags_and_no_existing_loop(self, tmp_path, monkeypatch):
        # Given: 既存 loop.mp4 なし + フラグ無し（通常経路の起点 regression）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)

            # When
            with pytest.raises(SystemExit) as excinfo:
                mod.main()

            # Then: Veo は 1 回呼ばれ exit 0、loop-v1.mp4 は生成されない
            assert mocks["generate_loop_video"].call_count == 1
            assert not (col / ASSETS_DIR / LOOP_V1).exists()
            assert excinfo.value.code == 0


# ---------------------------------------------------------------------------
# 8. main(): compression skill-config の伝播 (Issue #175)
# ---------------------------------------------------------------------------


class TestMainCompressionPropagation:
    """skill-config の `compression:` セクションが Veo / smooth 双方に伝播する。"""

    def test_compression_config_propagates_to_generate_loop_video(self, tmp_path, monkeypatch):
        # Given: skill-config に compression.crf=24 を上書き
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        compression = {"enabled": True, "crf": 24, "preset": "veryslow"}

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"veo": {}, "compression": compression}

            # When
            with pytest.raises(SystemExit):
                mod.main()

            # Then: generate_loop_video が compression= kwarg で呼ばれる
            assert mocks["generate_loop_video"].call_count == 1
            assert mocks["generate_loop_video"].call_args.kwargs.get("compression") == compression

    def test_compression_config_propagates_to_smooth_loop(self, tmp_path, monkeypatch):
        # Given: --smooth + skill-config compression.crf=22
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        compression = {"enabled": True, "crf": 22, "preset": "slow"}

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"veo": {}, "compression": compression}

            # When
            with pytest.raises(SystemExit):
                mod.main()

            # Then: smooth_loop が crf=22 / preset="slow" で呼ばれる
            assert mocks["smooth_loop"].call_count == 1
            kwargs = mocks["smooth_loop"].call_args.kwargs
            assert kwargs.get("crf") == 22
            assert kwargs.get("preset") == "slow"

    def test_smooth_falls_back_to_legacy_crf_when_compression_disabled(self, tmp_path, monkeypatch):
        # Given: --smooth + compression.enabled=false → smooth_loop は従来デフォルト (CRF 18)
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {
                "veo": {},
                "compression": {"enabled": False, "crf": 22, "preset": "slow"},
            }

            # When
            with pytest.raises(SystemExit):
                mod.main()

            # Then: 互換性確保のため CRF 18 / slow に倒れる
            assert mocks["smooth_loop"].call_count == 1
            kwargs = mocks["smooth_loop"].call_args.kwargs
            assert kwargs.get("crf") == 18
            assert kwargs.get("preset") == "slow"


# ---------------------------------------------------------------------------
# 9. main(): トップレベル enabled ゲート (Issue #577)
# ---------------------------------------------------------------------------


class TestMainEnabledGate:
    """skill-config の トップレベル `enabled: false` で全経路を fail-loud 停止する。

    `enabled` 未指定時は default `true` で従来挙動（regression）。
    `compression.enabled`（FFmpeg 圧縮の on/off）とは別概念であることに注意。
    """

    def test_disabled_fails_loud_and_skips_veo(self, tmp_path, monkeypatch, capsys):
        # Given: skill-config が enabled: false（このチャンネルはループ動画化を停止）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"enabled": False}

            # When/Then: fail-loud で exit 1。Veo もクライアント生成も呼ばれない（課金経路遮断）
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 1
            assert mocks["generate_loop_video"].call_count == 0
            assert mocks["create_genai_client"].call_count == 0

        # メッセージは設定確認を促す（issue 指定文言）
        err = capsys.readouterr().err
        assert "無効化されています" in err
        assert "config/skills/loop-video.yaml::enabled" in err

    def test_disabled_blocks_smooth_path(self, tmp_path, monkeypatch):
        # Given: enabled: false + --smooth（課金は無いが全経路ブロックの確認）
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        _write_loop_mp4(col, LOOP_MP4)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "--smooth"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"enabled": False}

            # When/Then: smooth 早期分岐より前で停止 → exit 1、smooth_loop 非呼出
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 1
            assert mocks["smooth_loop"].call_count == 0

    def test_enabled_absent_defaults_to_true(self, tmp_path, monkeypatch):
        # Given: トップレベル enabled 未指定（既存チャンネル相当）→ default true
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"veo": {}}

            # When/Then: 従来通り Veo 呼出 + exit 0（regression）
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 0
            assert mocks["generate_loop_video"].call_count == 1

    def test_enabled_true_runs_normally(self, tmp_path, monkeypatch):
        # Given: enabled: true 明示
        from youtube_automation.scripts import generate_loop_video as mod

        col = _make_collection(tmp_path)
        _write_image(col, MAIN_PNG)
        monkeypatch.setattr(sys, "argv", ["yt-generate-loop-video", str(col), "-y"])

        with _patch_main_boundaries() as mocks:
            _set_default_mocks(mocks)
            mocks["load_config"].return_value = {"enabled": True, "veo": {}}

            # When/Then: Veo 呼出 + exit 0
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 0
            assert mocks["generate_loop_video"].call_count == 1
