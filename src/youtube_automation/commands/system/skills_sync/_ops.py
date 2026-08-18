"""FS プリミティブ — `cmd_sync` と `cmd_diff` で共用される低レイヤ操作。

`pathlib` / `shutil` / `filecmp` のラッパー責務に閉じる。
- `_ensure_target_parent`: 親ディレクトリの作成
- `_copy_entry` / `_symlink_entry`: 単一 entry の配置
- `_ensure_agents_skills_symlink`: Codex 探索パス `.agents/skills` の symlink を張る
- `_prune_orphans`: 既知の upstream orphan の列挙・削除
- `_report_orphan_skill_configs`: 対応する同梱 skill がない channel override の報告
- `_has_diff`: `filecmp.dircmp` の再帰的差分検出
"""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

# Codex CLI が探索する `.agents/skills` から `.claude/skills` への相対リンク先。
# upstream リポの `.agents/skills -> ../.claude/skills` と同じ相対表現を用いる
# ことで、リポジトリをどこに clone しても壊れないリンクにする。
_AGENTS_SKILLS_LINK_TARGET = Path("..") / ".claude" / "skills"

# 未知の target entry は symlink や file でもローカル自作 skill の可能性があるため、
# upstream が管理していた既知名だけを prune 対象にする。
_KNOWN_REMOVED_SKILL_NAMES = frozenset(
    {
        "analyze",
        "collect",
        "report",
        "status",
        "description",
        "upload",
        "ideate",
        "persona",
        "onboard",
        "distrokid-prep",
        "channel-import",
        "channel-setup",
        "channel-direction",
        "automation-release",
        "shadcn",
        "feedback",
        "analytics-collect",
        "analytics-analyze",
        "analytics-report",
        "analytics-run",
        "alignment-check",
        "audience-persona-design",
        "automation-schedule",
        "automation-update",
        "benchmark",
        "channel-new",
        "channel-status",
        "collection-ideate",
        "comments-reply",
        "community-draft",
        "community-post",
        "creative-constraints",
        "discover-competitors",
        "ext-install",
        "flop-analysis",
        "live-chat-reply",
        "live-clean",
        "loop-video",
        "lyria",
        "market-research",
        "masterup",
        "metadata-audit",
        "pinned-comment",
        "playlist",
        "post-publish",
        "short-release",
        "short-thumbnail",
        "suno",
        "suno-helper",
        "suno-lyric",
        "thumbnail-compare",
        "thumbnail-iterate",
        "thumbnail-research",
        "thumbnail-test",
        "value-loop-audit",
        "video-analyze",
        "video-description",
        "video-upload",
        "videoup",
        "viewer-voice",
        "viewing-scene",
        "wf-auto",
        "wf-new-batch",
    }
)

_SKILL_CONFIG_SUFFIXES = frozenset({".json", ".yaml"})
_COMPATIBLE_SKILL_CONFIG_NAMES = frozenset({"postmortem"})


def _prunable_orphan_names(entry_names: set[str], bundled: set[str]) -> set[str]:
    return (entry_names - bundled) & _KNOWN_REMOVED_SKILL_NAMES


def _orphan_skill_config_names(config_dir: Path, configurable: set[str]) -> list[str]:
    """対応する同梱 default config がない channel override 名を返す。"""
    if not config_dir.is_dir():
        return []
    configured = {
        entry.stem for entry in config_dir.iterdir() if entry.is_file() and entry.suffix in _SKILL_CONFIG_SUFFIXES
    }
    return sorted(configured - configurable - _COMPATIBLE_SKILL_CONFIG_NAMES)


def _report_orphan_skill_configs(target_dir: Path, source_dir: Path) -> None:
    """標準 skills 配置に対応する channel override の孤児を報告する。"""
    if not (target_dir.name == "skills" and target_dir.parent.name == ".claude"):
        return
    configurable = {
        skill_dir.name
        for skill_dir in source_dir.iterdir()
        if skill_dir.is_dir() and (skill_dir / "config.default.yaml").is_file()
    }
    from youtube_automation.commands.system.skills_sync import _migrate_config

    migratable = set(_migrate_config.SKILL_CONFIG_MIGRATIONS)
    workspace = target_dir.parent.parent
    config_dirs = [workspace / "config" / "skills"]
    channels_dir = workspace / "channels"
    if channels_dir.is_dir():
        config_dirs.extend(channel / "config" / "skills" for channel in channels_dir.iterdir() if channel.is_dir())
    for config_dir in config_dirs:
        location = config_dir.relative_to(workspace).as_posix()
        configured = (
            {entry.stem for entry in config_dir.iterdir() if entry.is_file() and entry.suffix in _SKILL_CONFIG_SUFFIXES}
            if config_dir.is_dir()
            else set()
        )
        for name in sorted(configured & migratable):
            print(
                f"  [warn] 未移行の skill-config です: {name} ({location}) — "
                f"yt-skills migrate-config --channel-dir {config_dir.parent.parent} --dry-run"
            )
        for name in _orphan_skill_config_names(config_dir, configurable | migratable):
            print(f"  [warn] 対応する skill が同梱されていません: {name} ({location})")


def _ensure_target_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _copy_entry(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    """単一 entry (ディレクトリ or ファイル) をコピーする。

    戻り値: 'created' | 'skipped'.
    """
    if dst.exists() and not force:
        return "skipped"
    if dry_run:
        return "created"
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return "created"


def _symlink_entry(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    if dst.exists() or dst.is_symlink():
        if not force:
            return "skipped"
        if not dry_run:
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
    if dry_run:
        return "linked"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src.resolve())
    return "linked"


def _ensure_agents_skills_symlink(target_dir: Path, *, force: bool, dry_run: bool) -> str | None:
    """skills を同期した downstream リポに `.agents/skills -> ../.claude/skills` を張る。

    Codex CLI は `$REPO_ROOT/.agents/skills` をスキル探索パスとする規約のため、
    `.claude/skills` を配布しただけでは Codex が同期済みスキルを発見できない。
    標準レイアウト (`<repo>/.claude/skills`) で sync したときに限り、Codex 用の
    `.agents/skills` symlink を併設する。

    戻り値:
        'linked'             : symlink を作成した (dry-run 時は作成予定)
        'skipped'            : 既存があり --force なしのため触らなかった
        'unsupported'        : symlink 非対応環境で作成できなかった (警告のみ、sync は継続)
        'permission-denied'  : 権限エラーで symlink を作成できなかった (sync は失敗扱い)
        None                 : 標準レイアウトでない target のため対象外 (`.agents` 規約が成立しない)

    `PermissionError` は `OSError` のサブクラスだが、ユーザーが手動で復旧可能な
    failure mode (チャンネルリポの所有者・umask・親ディレクトリ permission) のため
    silent 化せず明示的なエラーとして表面化する。symlink 機能自体が無効な環境 (例:
    Windows 非特権ユーザー / FS が symlink 非対応) とは扱いを分け、後者のみ
    'unsupported' で警告に留める。
    """
    # `.agents` 規約は `<repo>/.claude/skills` レイアウト前提。--target で別パスを
    # 指定した場合は repo root を推定できないため、副作用を出さず対象外として返す。
    if not (target_dir.name == "skills" and target_dir.parent.name == ".claude"):
        return None

    link = target_dir.parent.parent / ".agents" / "skills"

    if link.exists() or link.is_symlink():
        # 既存 (正しい symlink 含む) は冪等にスキップ。張り直しは --force のみ。
        if not force:
            return "skipped"
        if not dry_run:
            try:
                if link.is_symlink() or link.is_file():
                    link.unlink()
                else:
                    shutil.rmtree(link)
            except PermissionError:
                return "permission-denied"

    if dry_run:
        return "linked"

    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return "permission-denied"

    try:
        link.symlink_to(_AGENTS_SKILLS_LINK_TARGET)
    except PermissionError:
        # 権限エラーは「symlink 機能がない」ではなく「書ける権限がない」という
        # ユーザーの環境問題なので、握りつぶさず明示的なエラーとして返す。
        return "permission-denied"
    except OSError:
        # Windows の非特権ユーザー等、symlink を張れない環境では sync 全体を
        # 失敗させず警告に留める (呼び出し側が stderr に出す)。
        return "unsupported"
    return "linked"


def _prune_orphans(
    target_dir: Path,
    bundled: set[str],
    *,
    do_delete: bool,
) -> dict[str, int]:
    """既知の upstream orphan だけを列挙し、do_delete=True なら削除する。

    戻り値: {"pruned": N} (実削除時) または {"would-prune": N} (列挙のみ)。
    entry の種別にかかわらず、未知名はローカル entry として保護する。
    """
    label = "pruned" if do_delete else "would-prune"
    count = 0
    entries_by_name = {entry.name: entry for entry in target_dir.iterdir()}
    prunable_names = _prunable_orphan_names(set(entries_by_name), bundled)
    for name in sorted(prunable_names):
        entry = entries_by_name[name]
        count += 1
        print(f"  {label:>8}: {name}")
        if do_delete:
            if entry.is_symlink():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    return {label: count} if count else {}


def _has_diff(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    return any(_has_diff(sub) for sub in cmp.subdirs.values())
