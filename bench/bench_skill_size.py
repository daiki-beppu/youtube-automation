"""`.claude/skills/*/SKILL.md` の行数集計（context / triggering 影響の参考値）.

#130 と関連する副次的指標として、SKILL.md の肥大具合を可視化する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"


def run() -> Sequence[Stats]:
    if not SKILLS.exists():
        print(f"  [SKIP] {SKILLS} が見つかりません")
        return []

    sizes: list[tuple[str, int]] = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        n = sum(1 for _ in path.open(encoding="utf-8"))
        sizes.append((path.parent.name, n))

    if not sizes:
        print("  [SKIP] SKILL.md が見つかりません")
        return []

    sizes.sort(key=lambda x: x[1], reverse=True)

    total = sum(n for _, n in sizes)
    print(f"  total_files={len(sizes)} total_lines={total}")
    print("  Top 10:")
    for name, n in sizes[:10]:
        print(f"    {name:<30} {n:>5}")

    samples_ms = [float(n) for _, n in sizes]
    s = stats_from_samples("skill_md_lines", samples_ms)
    save_result(
        s,
        extra={
            "total_lines": total,
            "total_files": len(sizes),
            "top10": [{"name": n, "lines": ln} for n, ln in sizes[:10]],
        },
    )
    return [s]


if __name__ == "__main__":
    run()
