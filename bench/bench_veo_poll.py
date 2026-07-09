"""Veo 3.1 fast の生成完了までの実時間を測り、poll 間隔短縮の理論効果を算出する.

固定間隔 (POLL_INTERVAL_SEC=20) で polling した場合の待ち取りこぼし（次 poll まで
何秒余分に待ったか）を推定する。実 API 1 リクエスト分のコストが発生する。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples


def _ensure_sample_image(path: Path) -> None:
    """Veo は入力画像を要求する。1x1 の PNG を ffmpeg なしで生成。"""
    from PIL import Image

    Image.new("RGB", (1024, 576), color=(40, 30, 60)).save(path)


def run() -> Sequence[Stats]:
    if not (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")):
        print("  [SKIP] GOOGLE_CLOUD_PROJECT 未設定")
        return []

    try:
        from google import genai

        from youtube_automation.utils import veo_generator
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        image = tmp / "in.png"
        output = tmp / "out.mp4"
        _ensure_sample_image(image)

        client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )

        t0 = time.perf_counter()
        ok = veo_generator.generate_loop_video(
            client=client,
            image_path=image,
            output_path=output,
            model=veo_generator.DEFAULT_MODEL,
            prompt=veo_generator.DEFAULT_PROMPT,
            aspect_ratio="16:9",
            duration_seconds=8,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if not ok:
            print("  [FAIL] generate_loop_video が失敗")
            return []

    # 待ち取りこぼし試算: 平均 = interval / 2
    interval = veo_generator.POLL_INTERVAL_SEC
    estimated_wait_overhead = interval / 2.0
    s = stats_from_samples("veo_total_elapsed", [elapsed_ms])
    save_result(
        s,
        extra={
            "poll_interval_sec": interval,
            "estimated_avg_overhead_sec": estimated_wait_overhead,
            "model": veo_generator.DEFAULT_MODEL,
        },
    )
    print(f"  veo total: {elapsed_ms / 1000:.1f}s (poll={interval}s, avg overhead ~{estimated_wait_overhead:.1f}s)")
    return [s]


if __name__ == "__main__":
    run()
