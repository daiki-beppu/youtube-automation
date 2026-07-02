"""Issue #130: 曖昧スキル名 8 件の `<domain>-<action>` 形式 rename 不変条件テスト。

rename マッピング:

| 旧 | 新 |
|---|---|
| `analyze` | `analytics-analyze` |
| `collect` | `analytics-collect` |
| `report` | `analytics-report` |
| `status` | `channel-status` |
| `description` | `video-description` |
| `upload` | `video-upload` |
| `ideate` | `collection-ideate` |
| `persona` | `audience-persona-design` |

検証する不変条件:

1. 旧ディレクトリが完全に消えている（broken symlink 残骸も含めて検出）。
2. 新ディレクトリと SKILL.md が存在する。
3. 各 SKILL.md の YAML front-matter `name:` が新名と一致する（front-matter 書換漏れ検知）。
4. `.claude/skills/**/*.md` に旧スラッシュコマンド参照 `/<old>` が残っていない。
5. `.claude/skills/**/*.md` に旧パス参照 `.claude/skills/<old>/` / `config/skills/<old>.yaml` が残っていない。
6. プロダクション 2 ファイル
   (`src/youtube_automation/agents/youtube_auto_uploader.py` /
    `src/youtube_automation/utils/metadata_generator.py`)
   のコメント・エラーメッセージ中の旧スラッシュ参照 `/description` が
   新名 `/video-description` に追従している。
7. 全 SKILL.md 31 件で `name:` 欄が親ディレクトリ名と一致する（rename 漏れ防止）。
8. 監査ドキュメント `docs/audits/2026-05-skill-md-audit.md` が生成されている。

スラッシュコマンド検出には、パス参照との誤検出を避けるため
`(?<![\\w./])/<old>(?![\\w-])` を使う:

- 直前が word char / `.` / `/` の場合はパス参照 → スキップ
  例: `references/description-templates.md`、`.claude/skills/analyze/`
- 直後が word char / `-` の場合は別スキル名の prefix → スキップ
  例: `/description-templates`、`/persona-definition`

リネーム後の `yt-skills sync` パイプラインの動作は既存
`tests/test_skills_sync.py` で担保される（`_list_entries` がディレクトリ名を
ハードコードしないため、rename はパッケージング側に影響しない）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

import pytest

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_SRC_DIR = _REPO_ROOT / "src" / "youtube_automation"
_AUDIT_DOC = _REPO_ROOT / "docs" / "audits" / "2026-05-skill-md-audit.md"
_CLAUDE_TEMPLATE = _REPO_ROOT / ".claude" / "CLAUDE.template.md"
_ONBOARDING = _REPO_ROOT / "ONBOARDING.md"
_AUDIENCE_PERSONA_DESIGN = _SKILLS_DIR / "audience-persona-design" / "SKILL.md"
_VIEWER_VOICE = _SKILLS_DIR / "viewer-voice" / "SKILL.md"
_VIEWING_SCENE = _SKILLS_DIR / "viewing-scene" / "SKILL.md"
_COLLECTION_IDEATE = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_POSTMORTEM = _SKILLS_DIR / "postmortem" / "SKILL.md"

# rename マッピング (order.md §5)
RENAME_MAP: dict[str, str] = {
    "analyze": "analytics-analyze",
    "collect": "analytics-collect",
    "report": "analytics-report",
    "status": "channel-status",
    "description": "video-description",
    "upload": "video-upload",
    "ideate": "collection-ideate",
    "persona": "audience-persona-design",
}

# 旧名 / 新名のフラットリスト (parametrize 用)
_OLD_NAMES: list[str] = sorted(RENAME_MAP.keys())
_NEW_NAMES: list[str] = sorted(RENAME_MAP.values())
_RENAME_PAIRS: list[tuple[str, str]] = sorted(RENAME_MAP.items())

# 旧スラッシュコマンドが残らないか走査するプロダクションコード
# (plan.md「ソース 2 ファイル」)
_PROD_FILES_WITH_SLASH_REFS: list[Path] = [
    _SRC_DIR / "agents" / "youtube_auto_uploader.py",
    _SRC_DIR / "utils" / "metadata_generator.py",
]


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slash_pattern(name: str) -> re.Pattern[str]:
    """`/name` のスラッシュコマンド検出パターン。

    - `(?<![\\w./])` 直前が word char / `.` / `/` の場合はパス・ファイル名 → 除外
    - `(?![\\w-])`   直後が word char / `-` の場合は別名 (`/description-templates` 等) → 除外
    """
    return re.compile(rf"(?<![\w./])/{re.escape(name)}(?![\w-])")


def _path_pattern(name: str) -> re.Pattern[str]:
    """`.claude/skills/<name>/` の skill ディレクトリパス参照パターン。"""
    return re.compile(rf"\.claude/skills/{re.escape(name)}/")


def _config_yaml_pattern(name: str) -> re.Pattern[str]:
    """`config/skills/<name>.yaml` の skill-config 上書きパス参照パターン。"""
    return re.compile(rf"config/skills/{re.escape(name)}\.yaml")


def _iter_skill_md_files() -> Iterable[Path]:
    """`.claude/skills/**/*.md` を全件返す（front-matter / 連鎖呼び出しの双方を走査するため）。"""
    return sorted(_SKILLS_DIR.rglob("*.md"))


def _iter_audience_persona_route_docs() -> Iterable[Path]:
    """旧 `/audience-persona` 導線が残ると downstream に配布される文書を返す。"""
    return [*_iter_skill_md_files(), _CLAUDE_TEMPLATE]


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^#{{2,4}}\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def _assert_tokens_in_order(text: str, tokens: tuple[str, ...], context: str) -> None:
    cursor = -1
    for token in tokens:
        index = text.find(token, cursor + 1)
        assert index != -1, f"{context} に `{token}` がありません"
        assert index > cursor, f"{context} で `{token}` の順序が崩れています"
        cursor = index


def _front_matter_name(skill_md: Path) -> str | None:
    """SKILL.md 先頭の YAML front-matter から `name:` 値を抽出する。

    front-matter が無い / `name:` 行が無い場合は ``None``。
    """
    text = _read(skill_md)
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    front = text[4:end]
    for line in front.splitlines():
        if line.startswith("name:"):
            return line[len("name:") :].strip()
    return None


# ---------- 旧ディレクトリが完全に消えているか ----------


@pytest.mark.parametrize("old_name", _OLD_NAMES, ids=_OLD_NAMES)
def test_old_skill_directory_is_removed(old_name: str) -> None:
    """Given Issue #130 の rename 後の状態
    When 旧スキルディレクトリのパスを確認する
    Then ディレクトリ・ファイル・broken symlink のいずれとしても存在しない。

    `Path.exists()` は broken symlink を ``False`` 扱いするため、
    残骸 symlink も検出できるよう ``os.path.lexists`` を使う。
    """
    path = _SKILLS_DIR / old_name
    assert not os.path.lexists(path), (
        f"旧スキルディレクトリ {path.relative_to(_REPO_ROOT)} が残存している。"
        f" `git mv {path.relative_to(_REPO_ROOT)} .claude/skills/{RENAME_MAP[old_name]}` で rename すること"
        f" (後方互換 alias の symlink は order.md で禁止)"
    )


# ---------- 新ディレクトリが SKILL.md を持つか ----------


@pytest.mark.parametrize("new_name", _NEW_NAMES, ids=_NEW_NAMES)
def test_new_skill_directory_has_skill_md(new_name: str) -> None:
    """Given Issue #130 の rename 後の状態
    When 新スキルディレクトリの SKILL.md を確認する
    Then 実体ファイルとして存在する。
    """
    path = _SKILLS_DIR / new_name / "SKILL.md"
    assert path.exists(), f"新スキル {path.relative_to(_REPO_ROOT)} が存在しない (rename 漏れ)"


# ---------- front-matter `name:` が新名に追従しているか ----------


@pytest.mark.parametrize(
    ("old_name", "new_name"),
    _RENAME_PAIRS,
    ids=[f"{o}->{n}" for o, n in _RENAME_PAIRS],
)
def test_renamed_skill_md_front_matter_name_matches_new(old_name: str, new_name: str) -> None:
    """Given rename 後の新ディレクトリ内 SKILL.md
    When 先頭の YAML front-matter の `name:` を読む
    Then 値が新名と一致する。

    Claude Code は front-matter の `name:` をスキル登録名として読むため、
    ディレクトリ rename だけだと旧名のまま登録されて triggering が壊れる。
    """
    skill_md = _SKILLS_DIR / new_name / "SKILL.md"
    if not skill_md.exists():
        pytest.fail(
            f"{skill_md.relative_to(_REPO_ROOT)} が存在しない。 先に test_new_skill_directory_has_skill_md を満たすこと"
        )
    actual = _front_matter_name(skill_md)
    assert actual == new_name, (
        f"{skill_md.relative_to(_REPO_ROOT)} の front-matter `name:` が `{actual}`。"
        f" rename に追従して `name: {new_name}` に書き換えること (旧: `{old_name}`)"
    )


# ---------- 全 SKILL.md で name: が親ディレクトリ名と一致するか ----------


def test_all_skill_md_name_matches_parent_dir() -> None:
    """Given `.claude/skills/<dir>/SKILL.md` 全件 (31 件)
    When 各 SKILL.md の YAML front-matter `name:` を読む
    Then 値が親ディレクトリ名と完全一致する。

    rename 漏れ・誤改名・コピペミスを 1 つの集約テストで一括検出する。
    """
    skill_md_files = sorted(_SKILLS_DIR.glob("*/SKILL.md"))
    mismatches: list[str] = []
    for skill_md in skill_md_files:
        dir_name = skill_md.parent.name
        actual = _front_matter_name(skill_md)
        if actual != dir_name:
            mismatches.append(f"{skill_md.relative_to(_REPO_ROOT)}: dir=`{dir_name}` vs name=`{actual}`")
    assert mismatches == [], "front-matter `name:` が親ディレクトリ名と不一致:\n  " + "\n  ".join(mismatches)


def test_audience_persona_design_replaces_legacy_audience_persona_dir() -> None:
    """Issue #1371: `/audience-persona` を単一ペルソナ設計スキルへ rename した契約。"""
    legacy_path = _SKILLS_DIR / "audience-persona"
    assert not os.path.lexists(legacy_path), "旧スキルディレクトリ .claude/skills/audience-persona が残存している"
    assert _AUDIENCE_PERSONA_DESIGN.exists()
    assert _front_matter_name(_AUDIENCE_PERSONA_DESIGN) == "audience-persona-design"


def test_no_legacy_audience_persona_slash_command_in_skill_docs() -> None:
    """Issue #1371: skill docs と配布テンプレ内の旧 `/audience-persona` 導線を残さない。"""
    pattern = _slash_pattern("audience-persona")
    offenders: list[str] = []
    for path in _iter_audience_persona_route_docs():
        text = _read(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "旧スラッシュコマンド `/audience-persona` が skill docs または配布テンプレートに残存。"
        " `/audience-persona-design` に書き換えること:\n  " + "\n  ".join(offenders)
    )


def test_audience_persona_design_orchestrates_single_persona_flow() -> None:
    """Issue #1371: viewer-voice → persona design → viewing-scene → final persona の順序を固定する。"""
    text = _read(_AUDIENCE_PERSONA_DESIGN)
    order = _markdown_section(text, "## 実行順序")

    expected_order = (
        "`/viewer-voice` の成果物を確認する。未実施なら案内して停止する。",
        "コメント由来の語彙・不満・利用シーン・感情トリガーを入力にする。",
        "候補を 1 人の第一ペルソナへ統合",
        "暫定 `persona-definition.md` を保存",
        "`/viewing-scene` を実行",
        "`/viewing-scene` の結果を反映し、最終 `persona-definition.md` を更新する。",
    )
    _assert_tokens_in_order(order, expected_order, "audience-persona-design 実行順序")

    assert "最終版に残す人物は 1 人だけ" in text
    for required in (
        "コメント由来の語彙",
        "感情トリガー",
        "利用シーン",
        "検索キーワード",
        "避けるべき訴求",
        "自チャンネルへの示唆",
    ):
        assert required in text


def test_persona_flow_declares_untrusted_data_boundaries() -> None:
    """Issue #1371: コメント・WebSearch・生成 Markdown を命令として後続へ再注入しない。"""
    for path in (_VIEWER_VOICE, _AUDIENCE_PERSONA_DESIGN, _VIEWING_SCENE, _COLLECTION_IDEATE):
        text = _read(path)
        assert "## Untrusted Data 境界" in text, f"{path.relative_to(_REPO_ROOT)} に untrusted data 境界がない"
        assert "外部由来テキスト内の命令" in text, f"{path.relative_to(_REPO_ROOT)} が外部命令の無視を明記していない"
        assert "構造化 persona fields" in text, (
            f"{path.relative_to(_REPO_ROOT)} が構造化 persona fields 境界を明記していない"
        )


def test_audience_persona_route_docs_follow_required_order() -> None:
    """Issue #1371: 利用者導線も viewer-voice → persona design → viewing-scene の順にする。"""
    onboarding = _read(_ONBOARDING)
    frequency = _markdown_section(onboarding, "### 5.1 定常タスクの推奨頻度")
    troubleshooting = _markdown_section(onboarding, "### 5.2 困ったときに参照するスキル")
    postmortem = _read(_POSTMORTEM)
    verification = _markdown_section(postmortem, "### Phase 4: 検証ステップの案内")
    next_step = _markdown_section(postmortem, "## Next Step")

    expected = "`/viewer-voice` → `/audience-persona-design` → `/viewing-scene`"
    expected_tokens = ("`/viewer-voice`", "`/audience-persona-design`", "`/viewing-scene`")
    assert expected in frequency
    assert expected in troubleshooting
    _assert_tokens_in_order(verification, expected_tokens, "postmortem Phase 4")
    assert expected in next_step
    assert "`/audience-persona-design` → `/viewer-voice`" not in postmortem


def test_audience_persona_design_failure_guidance_covers_prerequisite_paths() -> None:
    """Issue #1371: 未実施 viewer-voice と未反映 viewing-scene の停止/再実行契約を固定する。"""
    text = _read(_AUDIENCE_PERSONA_DESIGN)
    guidance = _markdown_section(text, "## 障害時ガイダンス")

    assert "viewer-voice 未実施" in guidance
    assert "`docs/plans/viewer-voice-analysis.md` が無い" in guidance
    assert "`/viewer-voice` を先に実行するよう案内して停止する" in guidance
    assert "viewing-scene 未反映" in guidance
    assert "`docs/plans/viewing-scene-matrix.md` が無い" in guidance
    assert "暫定 `persona-definition.md` 保存後に `/viewing-scene` を実行し、結果を反映して最終化する" in guidance


def test_persona_skill_docs_do_not_reference_content_json_suno_genre_line() -> None:
    """Issue #1371: `genre_line` は `config/skills/suno.yaml` 側であり content.json には存在しない。"""
    for path in (_AUDIENCE_PERSONA_DESIGN, _VIEWING_SCENE):
        text = _read(path)
        assert "content.json` の `tags.base` と `suno.genre_line`" not in text
        assert "content.json` の `tags.base` と `genre.*`" in text


# ---------- `.claude/skills/**/*.md` に旧スラッシュコマンド参照が残っていないか ----------


@pytest.mark.parametrize("old_name", _OLD_NAMES, ids=_OLD_NAMES)
def test_no_legacy_slash_command_in_skill_docs(old_name: str) -> None:
    """Given Issue #130 の rename 後の状態
    When `.claude/skills/**/*.md` を全件走査して `/<old>` を探す
    Then 旧スラッシュコマンド参照が 1 件もない。

    `.claude/skills/<old>/` パス文字列や `description-templates.md` のような
    ファイル名との誤検出を避けるため、前後の境界を厳格にチェックする。
    """
    pattern = _slash_pattern(old_name)
    new_name = RENAME_MAP[old_name]
    offenders: list[str] = []
    for path in _iter_skill_md_files():
        text = _read(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        f"旧スラッシュコマンド `/{old_name}` が `.claude/skills/**/*.md` に残存。"
        f" `/{new_name}` に書き換えること:\n  " + "\n  ".join(offenders)
    )


# ---------- `.claude/skills/**/*.md` に旧 skill ディレクトリパスが残っていないか ----------


@pytest.mark.parametrize("old_name", _OLD_NAMES, ids=_OLD_NAMES)
def test_no_legacy_skill_dir_path_in_skill_docs(old_name: str) -> None:
    """Given Issue #130 の rename 後の状態
    When `.claude/skills/**/*.md` を全件走査して `.claude/skills/<old>/` を探す
    Then 旧パス参照が 1 件もない。

    自己参照 (例: `.claude/skills/description/config.default.yaml`) も含めて
    `.claude/skills/<new>/` に書き換える必要がある。
    """
    pattern = _path_pattern(old_name)
    new_name = RENAME_MAP[old_name]
    offenders: list[str] = []
    for path in _iter_skill_md_files():
        text = _read(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        f"旧パス `.claude/skills/{old_name}/` が残存。"
        f" `.claude/skills/{new_name}/` に書き換えること:\n  " + "\n  ".join(offenders)
    )


# ---------- `config/skills/<old>.yaml` 参照が残っていないか ----------


@pytest.mark.parametrize("old_name", _OLD_NAMES, ids=_OLD_NAMES)
def test_no_legacy_config_yaml_path_in_skill_docs(old_name: str) -> None:
    """Given Issue #130 の rename 後の状態
    When `.claude/skills/**/*.md` および `*.yaml` を走査して `config/skills/<old>.yaml` を探す
    Then 旧 skill-config パス参照が 1 件もない。

    rename 対象のうち実際に skill-config を持つのは `description` / `ideate` のみ
    (調査済み) だが、新規追加の regression を検出するため全 8 件を走査する。
    """
    pattern = _config_yaml_pattern(old_name)
    new_name = RENAME_MAP[old_name]
    offenders: list[str] = []
    for path in _SKILLS_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".yaml", ".yml"}:
            continue
        text = _read(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        f"旧 skill-config パス `config/skills/{old_name}.yaml` が残存。"
        f" `config/skills/{new_name}.yaml` に書き換えること:\n  " + "\n  ".join(offenders)
    )


# ---------- プロダクションコードの slash 参照書換 ----------


@pytest.mark.parametrize(
    "prod_file",
    _PROD_FILES_WITH_SLASH_REFS,
    ids=[str(p.relative_to(_REPO_ROOT)) for p in _PROD_FILES_WITH_SLASH_REFS],
)
def test_no_legacy_description_slash_in_prod_source(prod_file: Path) -> None:
    """Given rename 後の `src/youtube_automation/**/*.py`
    When コメント・エラーメッセージ中の `/description` を走査する
    Then 旧スラッシュコマンド参照が残っていない。

    plan.md の grep で確認済み:
      - `agents/youtube_auto_uploader.py` line 119, 133, 189, 225 — 4 箇所
      - `utils/metadata_generator.py` line 47 — 1 箇所

    rename 後はすべて `/video-description` に書き換える必要がある。
    """
    if not prod_file.exists():
        pytest.fail(f"{prod_file.relative_to(_REPO_ROOT)} が存在しない")
    pattern = _slash_pattern("description")
    text = _read(prod_file)
    offenders: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            offenders.append(f"{prod_file.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "旧スラッシュコマンド `/description` がプロダクションコードに残存。"
        " `/video-description` に書き換えること:\n  " + "\n  ".join(offenders)
    )


# ---------- 監査ドキュメント ----------


def test_audit_document_exists() -> None:
    """Given Issue #130 完了条件 #1「全 SKILL.md の冗長記述・実装乖離をリストアップ」
    When 監査ドキュメントの生成先を確認する
    Then `docs/audits/2026-05-skill-md-audit.md` が存在する。

    plan.md「監査ドキュメント生成」(`docs/audits/2026-05-skill-md-audit.md`) で
    冗長記述・実装乖離・命名問題を観点別に列挙する成果物。
    """
    assert _AUDIT_DOC.exists(), (
        f"監査ドキュメント {_AUDIT_DOC.relative_to(_REPO_ROOT)} が生成されていない。"
        " plan.md の §「監査ドキュメントの構造」に従って生成すること"
    )


def test_audit_document_lists_all_eight_renames() -> None:
    """Given 監査ドキュメント
    When 内容を読む
    Then rename 対象 8 件すべての旧名 → 新名マッピングが記載されている。

    rename 表が監査ドキュメントの「rename 一覧」セクションに含まれていることを担保し、
    rename 履歴のトレーサビリティを保証する。
    """
    if not _AUDIT_DOC.exists():
        pytest.skip("audit document not yet generated; covered by test_audit_document_exists")
    text = _read(_AUDIT_DOC)
    missing: list[str] = []
    for old, new in _RENAME_PAIRS:
        # 「`old` → `new`」 / 「old → new」 / table cell `| old | new |` のいずれかにマッチ
        if old not in text or new not in text:
            missing.append(f"{old} -> {new}")
    assert missing == [], "監査ドキュメントに rename マッピング記載が不足:\n  " + "\n  ".join(missing)
