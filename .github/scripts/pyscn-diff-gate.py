#!/usr/bin/env python3
"""pyscn の finding を base commit と突き合わせる new-only 差分ゲート（#4616）。

#4615 の `pyscn check`（実測値を固定した絶対上限）とは独立に、base commit に
無い finding が増えたときだけ非 0 で終了する。比較元はリポジトリへコミットした
baseline ファイルではなく base commit そのもの（一時 worktree へ展開して base /
HEAD の 2 回 `pyscn analyze --json` を実行する）。baseline を持たないため、
削除済みパスを指す亡霊エントリが蓄積しない。

- 対象 finding: complexity の high risk 関数と dead code（`pyscn check` が即時
  fail させる循環 import は差分を取る必要がなく、clone はペア単位のため
  「ファイル + 種別 + シンボル」の鍵モデルに合わない。どちらも対象外）
- 突き合わせ鍵: ファイルパス + finding 種別 + シンボル名。行番号を含めないため、
  無関係な行ずれで finding の同一性が壊れない
- 基準点の解決順: `PYSCN_DIFF_BASE` → `origin/main` → `main`（merge-base）。
  any-usage-gate.sh と同じ規則で、remote を持たない隔離クローン（takt）でも
  ローカル `main` へフォールバックする

CI（ci.yml の lint ジョブ）はイベント種別から解決した base SHA を
`PYSCN_DIFF_BASE` で渡す。ローカルでは `nix develop --command uv run python
.github/scripts/pyscn-diff-gate.py` で単体実行できる。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ANALYSIS_TARGET = "src/youtube_automation"
# check が扱う category のうち差分に意味があるものだけを解析する（docstring 参照）。
_ANALYZE_SELECT = "complexity,deadcode"
_BASE_REF_CANDIDATES = ("origin/main", "main")

Finding = tuple[str, str, str]


def extract_findings(report: dict) -> set[Finding]:
    """analyze レポートから (ファイルパス, 種別, シンボル名) の finding 集合を抽出する。

    finding が 0 件のコレクションを pyscn は空リストではなく null で出力するため、
    リスト値の None は「finding なし」として扱う。section 自体の欠落は解析の失敗
    （--select との不整合）であり、ゲートの素通りを防ぐため KeyError のまま落とす。
    """
    findings: set[Finding] = set()
    for function in report["complexity"]["Functions"] or []:
        if function["RiskLevel"] == "high":
            findings.add((function["FilePath"], "complexity/high_risk", function["Name"]))
    for file_entry in report["dead_code"]["files"] or []:
        for function_entry in file_entry["functions"] or []:
            for finding in function_entry["findings"] or []:
                findings.add(
                    (
                        finding["location"]["file_path"],
                        f"dead_code/{finding['reason']}",
                        finding["function_name"],
                    )
                )
    return findings


def resolve_new_findings(base_report: dict, head_report: dict) -> list[Finding]:
    """base に無い finding だけを決定的な順序で返す。"""
    return sorted(extract_findings(head_report) - extract_findings(base_report))


def _run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _resolve_base_sha(repository: Path) -> str | None:
    """diff の基準点 SHA を解決する。どの ref も無ければ None（呼び出し元で skip）。"""
    explicit_base = os.environ.get("PYSCN_DIFF_BASE")
    if explicit_base:
        return _run_git(repository, "rev-parse", "--verify", f"{explicit_base}^{{commit}}")
    for candidate in _BASE_REF_CANDIDATES:
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            return _run_git(repository, "merge-base", candidate, "HEAD")
    return None


def _run_analysis(pyscn_executable: str, checkout_root: Path) -> dict:
    """checkout_root を cwd に pyscn analyze を実行し、生成された JSON レポートを返す。

    `--json` は stdout ではなく `.pyscn/reports/analyze_<timestamp>.json` へ書く
    ため、実行前後のファイル集合の差分で新規レポートを特定する（stdout の文言に
    依存しない）。
    """
    reports_dir = checkout_root / ".pyscn" / "reports"
    existing_reports = set(reports_dir.glob("*.json")) if reports_dir.is_dir() else set()
    subprocess.run(
        [pyscn_executable, "analyze", "--json", "--select", _ANALYZE_SELECT, ANALYSIS_TARGET],
        cwd=checkout_root,
        capture_output=True,
        text=True,
        check=True,
    )
    new_reports = set(reports_dir.glob("*.json")) - existing_reports
    if len(new_reports) != 1:
        raise SystemExit(
            f"pyscn-diff-gate: ERROR: {checkout_root} の解析レポートを特定できません"
            f"（新規ファイル {len(new_reports)} 件）。"
        )
    return json.loads(new_reports.pop().read_text(encoding="utf-8"))


def _analyze_base_commit(pyscn_executable: str, repository: Path, base_sha: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="pyscn-diff-base-") as temporary_directory:
        base_checkout = Path(temporary_directory) / "base"
        _run_git(repository, "worktree", "add", "--detach", str(base_checkout), base_sha)
        try:
            return _run_analysis(pyscn_executable, base_checkout)
        finally:
            # 解析が .pyscn/ を書き込み worktree が dirty になるため --force が必要。
            _run_git(repository, "worktree", "remove", "--force", str(base_checkout))


def _format_finding(finding: Finding) -> str:
    file_path, kind, symbol = finding
    return f"  {file_path}  {kind}  {symbol}"


def main() -> int:
    repository = Path(_run_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    pyscn_executable = shutil.which("pyscn")
    if pyscn_executable is None:
        raise SystemExit(
            "pyscn-diff-gate: ERROR: pyscn が見つかりません。"
            "`nix develop --command uv run python .github/scripts/pyscn-diff-gate.py` で実行してください。"
        )

    base_sha = _resolve_base_sha(repository)
    if base_sha is None:
        # exit 0 はゲートを素通りさせるため、試した ref を必ず示す（any-usage-gate と同じ扱い）。
        print(
            "pyscn-diff-gate: 基準点の ref が無いためスキップします"
            f"（試した ref: {' '.join(_BASE_REF_CANDIDATES)}）。CI / review で確認してください。",
            file=sys.stderr,
        )
        return 0

    head_report = _run_analysis(pyscn_executable, repository)
    base_report = _analyze_base_commit(pyscn_executable, repository, base_sha)

    new_findings = resolve_new_findings(base_report, head_report)
    if not new_findings:
        print(f"pyscn-diff-gate: OK: base {base_sha[:12]} に対する新規 finding はありません。")
        return 0

    print(
        f"pyscn-diff-gate: ERROR: base {base_sha[:12]} に無い finding が {len(new_findings)} 件増えています。",
        file=sys.stderr,
    )
    for finding in new_findings:
        print(_format_finding(finding), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
