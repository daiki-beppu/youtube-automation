"""perf #131 計測フェーズのオーケストレータ.

各 bench スクリプトを順次実行し、`bench/results/<session>/REPORT.md` を生成する。
実 API 不要の bench だけ走らせる場合は `--no-real-apis` を渡す。

Usage:
    uv run python bench/main.py                 # 全 bench（実 API 含む）
    uv run python bench/main.py --no-real-apis  # 課金 API をスキップ
    uv run python bench/main.py --only cost_tracker  # 単一 bench のみ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import format_table, session_dir

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

# import 順は依存ゼロのものから
LOCAL_BENCHES = [
    "bench_cost_tracker",
    "bench_strategic_analytics",
    "bench_smooth_loop",
    "bench_skill_size",
]

REAL_API_BENCHES = [
    "bench_video_daily",
    "bench_generate_image",
    "bench_veo_poll",
    "bench_benchmark_collector",
]


def _import_bench(name: str):
    mod = __import__(f"bench.{name}", fromlist=["run"])
    return mod.run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-real-apis", action="store_true", help="課金 API ベンチをスキップ")
    parser.add_argument("--only", help="単一 bench のみ実行（例: cost_tracker）")
    args = parser.parse_args()

    out_dir = session_dir()
    os.environ["BENCH_SESSION"] = out_dir.name  # 子 bench が同じ session に書くように

    benches = list(LOCAL_BENCHES)
    if not args.no_real_apis:
        benches.extend(REAL_API_BENCHES)
    if args.only:
        benches = [b for b in benches if args.only in b]
        if not benches:
            print(f"[ERROR] --only={args.only!r} に一致する bench がありません", file=sys.stderr)
            return 2

    rows: list[dict] = []
    for name in benches:
        print(f"\n=== {name} ===", flush=True)
        try:
            run = _import_bench(name)
        except ModuleNotFoundError as e:
            print(f"  [SKIP] {e}", file=sys.stderr)
            continue
        try:
            stats_list = run()
        except Exception as e:  # noqa: BLE001 — bench 単位で握りつぶす
            print(f"  [FAIL] {e}", file=sys.stderr)
            continue
        for stats in stats_list or []:
            rows.append(
                {
                    "bench": name.removeprefix("bench_"),
                    "case": stats.name,
                    "n": stats.n,
                    "p50_ms": stats.p50_ms,
                    "p95_ms": stats.p95_ms,
                    "max_ms": stats.max_ms,
                }
            )

    report = out_dir / "REPORT.md"
    body = (
        "# perf #131 計測結果\n\n"
        f"session: `{out_dir.name}`\n\n"
        + format_table(rows)
        + "\n\n## 個別 JSON\n\n"
        + "\n".join(f"- `{p.name}`" for p in sorted(out_dir.glob("*.json")))
        + "\n"
    )
    report.write_text(body, encoding="utf-8")

    print(f"\n→ {report}")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
