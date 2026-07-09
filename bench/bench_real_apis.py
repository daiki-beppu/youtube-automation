"""実 API ベンチをまとめて起動するオーケストレータ.

`--dry-run` で各 bench の前提チェックだけ行い API は叩かない。
通常は `bench/main.py` が呼び出すが、課金 API だけ独立して回したい場合の入口。

推定コスト（最小ケース）:
- YouTube Data API: クォータのみ（無料枠 10,000/日）
- YouTube Analytics API: 無料
- OpenAI gpt-image-1 1024×1024 ×2: ≈ $0.20
- Veo 3.1 fast 8s ×1: ≈ $0.40
- 合計: ≈ $0.60
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _check_env() -> dict[str, bool]:
    return {
        "YouTube Data / Analytics (CHANNEL_DIR + token.json)": bool(os.environ.get("CHANNEL_DIR")),
        "OpenAI (OPENAI_API_KEY)": bool(os.environ.get("OPENAI_API_KEY")),
        "Vertex AI (GOOGLE_CLOUD_PROJECT)": bool(
            os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API を叩かず、前提条件のチェックだけ行う",
    )
    args = parser.parse_args()

    print("=== 前提条件チェック ===")
    for label, ok in _check_env().items():
        mark = "✓" if ok else "✗"
        print(f"  {mark} {label}")

    if args.dry_run:
        return 0

    from bench import (
        bench_benchmark_collector,
        bench_generate_image,
        bench_veo_poll,
        bench_video_daily,
    )

    for mod in (
        bench_video_daily,
        bench_benchmark_collector,
        bench_generate_image,
        bench_veo_poll,
    ):
        name = mod.__name__.removeprefix("bench.")
        print(f"\n=== {name} ===")
        try:
            mod.run()
        except Exception as e:
            print(f"  [FAIL] {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
