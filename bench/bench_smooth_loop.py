"""veo_generator.smooth_loop の ffmpeg 再エンコードを preset 別に計測する.

8 秒のテスト動画を ffmpeg で合成し、libx264 (slow CRF18 / medium CRF20) と
ハードウェアエンコーダ (h264_videotoolbox) を比較する。

ffmpeg 不在環境では即座に [SKIP] して空 list を返す。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples

FFMPEG = shutil.which("ffmpeg")

PRESETS = [
    ("slow_crf18", ["-c:v", "libx264", "-preset", "slow", "-crf", "18"]),
    ("medium_crf20", ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]),
    ("videotoolbox", ["-c:v", "h264_videotoolbox", "-b:v", "8M"]),
]


def _make_sample(out: Path) -> None:
    cmd = [
        FFMPEG,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=8:size=1920x1080:rate=30",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _run_smooth(input_path: Path, output: Path, codec_args: list[str]) -> float:
    # smooth_loop と同じ filter_complex（クロスフェード 1 秒）
    crossfade_sec = 1.0
    duration = 8.0
    trim_end = duration - crossfade_sec
    filter_complex = (
        f"[0]trim=0:{duration},setpts=PTS-STARTPTS[trimmed];"
        f"[trimmed]split[main][tail];"
        f"[main]trim=0:{trim_end},setpts=PTS-STARTPTS[a];"
        f"[tail]trim={trim_end}:{duration},setpts=PTS-STARTPTS[b];"
        f"[b][a]xfade=transition=fade:duration={crossfade_sec}:offset=0[out]"
    )
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        *codec_args,
        "-an",
        str(output),
    ]
    start = time.perf_counter()
    subprocess.run(cmd, check=True, capture_output=True)
    return (time.perf_counter() - start) * 1000.0


def run() -> Sequence[Stats]:
    if FFMPEG is None:
        print("  [SKIP] ffmpeg が見つかりません")
        return []

    results: list[Stats] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sample = tmp / "sample.mp4"
        _make_sample(sample)

        for name, codec_args in PRESETS:
            samples = []
            n_iter = 3
            for i in range(n_iter):
                try:
                    elapsed = _run_smooth(sample, tmp / f"out_{name}_{i}.mp4", codec_args)
                except subprocess.CalledProcessError as e:
                    print(f"  [SKIP] {name}: {e.stderr[:120].decode(errors='replace')}")
                    samples = []
                    break
                samples.append(elapsed)
            if not samples:
                continue
            s = stats_from_samples(name, samples)
            save_result(s, extra={"codec_args": codec_args, "duration_sec": 8})
            results.append(s)
            print(f"  {name:<14}: p50={s.p50_ms:.1f}ms p95={s.p95_ms:.1f}ms (n={s.n})")
    return results


if __name__ == "__main__":
    run()
