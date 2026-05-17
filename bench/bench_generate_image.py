"""OpenAI gpt-image-1 の単発 vs バッチ生成を実測.

`OPENAI_API_KEY` が必要。プロバイダ実装 (`utils/image_provider/openai.py`) が
`n=batch` を活用しているか実測ベースで確認する目的の bench。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples  # noqa: E402


def _provider(batch: int):
    from youtube_automation.utils.image_provider import get_provider

    cfg = {
        "provider": "openai",
        "openai": {
            "model": "gpt-image-1",
            "size": "1024x1024",
            "quality": "standard",
            "batch": batch,
        },
    }
    return get_provider(cfg)


def _bench_one(batch: int, n_iter: int = 2) -> Stats:
    from youtube_automation.utils.image_provider import ImageGenerationRequest

    samples: list[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        provider = _provider(batch)
        for i in range(n_iter):
            req = ImageGenerationRequest(
                prompt="A small grey pebble on a wooden table, soft light, photo realistic",
                output_path=Path(tmpdir) / f"out_b{batch}_{i}.png",
                aspect_ratio="1:1",
                image_size="1024x1024",
                references=[],
                cost_per_image_usd=0.04,
            )
            t0 = time.perf_counter()
            result = provider.generate(req)
            samples.append((time.perf_counter() - t0) * 1000.0)
            if not result.success:
                print(f"  [FAIL] batch={batch} iter={i} 生成失敗")
                break
    return stats_from_samples(f"openai_image_batch{batch}", samples)


def run() -> Sequence[Stats]:
    if not os.environ.get("OPENAI_API_KEY"):
        print("  [SKIP] OPENAI_API_KEY 未設定")
        return []

    results: list[Stats] = []
    for batch in (1, 4):
        try:
            s = _bench_one(batch)
            save_result(s, extra={"batch": batch})
            results.append(s)
            print(f"  batch={batch}: p50={s.p50_ms:.0f}ms p95={s.p95_ms:.0f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] batch={batch}: {e}")
    return results


if __name__ == "__main__":
    run()
