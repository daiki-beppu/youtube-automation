#!/usr/bin/env python
"""PROTOTYPE (#4896) — 目視の補助となる客観指標を ffmpeg だけで出す（使い捨て）。

- seam_yavg: final-2x.mp4 の隣接フレーム差（tblend difference → Y 平均）。継ぎ目フレーム（1 周目末尾 → 2 周目先頭）の値と、
  それ以外の中央値・最大値。継ぎ目が中央値に近ければ「継ぎ目が目立たない」
- drift_ssim: final.mp4 の各フレームと先頭フレームの SSIM。最小値が低いほど「静止対象の逸脱」が大きい
- first_vs_input_ssim: 先頭フレームと main.png（1920×1080 へ同じ lanczos で拡大）の SSIM。first = 入力 の忠実度
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"
MAIN_PNG = Path(
    "~/ghq/github.com/daiki-beppu/youtube-channels-workspace/channels/001ch-afro-deep-noir/collections/live/20260714-adn-deep-melodic-collection/10-assets/main.png"
).expanduser()
NAMES = ["veo-fast-1080p", "turbo-balanced", "turbo-quality", "max-balanced", "max-quality", "turbo-balanced-resized"]


def run(args: list[str]) -> str:
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True).stderr


def frame_count(path: Path) -> int:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        text=True,
    )
    return int(out.strip())


def seam_yavg(video_2x: Path, frames_per_loop: int) -> dict:
    err = run(["-i", str(video_2x), "-vf", "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"])
    vals = [float(m) for m in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", err)]
    # tblend の出力フレーム i は入力フレーム i と i-1 の差。継ぎ目は i = frames_per_loop
    seam = vals[frames_per_loop] if frames_per_loop < len(vals) else None
    others = [v for i, v in enumerate(vals) if i not in (0, frames_per_loop)]
    return {"seam": seam, "median": statistics.median(others), "p95": sorted(others)[int(len(others) * 0.95)], "max": max(others), "n": len(vals)}


def duration_sec(video: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)], text=True)
    return float(out.strip())


def ssim_series(video: Path, ref_png: Path) -> list[float]:
    # 参照画像は無限ループにせず、動画と同じ長さの 24 fps 映像として与える（-loop 1 だけだと終了しない）
    stats = video.parent / "ssim.log"
    run([
        "-i", str(video),
        "-framerate", "24", "-loop", "1", "-t", f"{duration_sec(video):.3f}", "-i", str(ref_png),
        "-filter_complex", f"[0:v][1:v]ssim=stats_file={stats}", "-f", "null", "-",
    ])
    vals = [float(m) for m in re.findall(r"All:([0-9.]+)", stats.read_text())]
    stats.unlink(missing_ok=True)
    return vals


def main() -> None:
    input_1080 = OUT / "frames" / "main-1920x1080.png"
    run(["-y", "-i", str(MAIN_PNG), "-vf", "scale=1920:1080:flags=lanczos", "-frames:v", "1", str(input_1080)])
    results = {}
    for name in NAMES:
        d = OUT / name
        final, final2x = d / "final.mp4", d / "final-2x.mp4"
        n = frame_count(final)
        frame0 = OUT / "frames" / f"{name}-frame0.png"
        run(["-y", "-i", str(final), "-frames:v", "1", str(frame0)])
        drift = ssim_series(final, frame0)
        first_vs_input = ssim_series(final, input_1080)[:1]
        results[name] = {
            "frames": n,
            "seam_yavg": seam_yavg(final2x, n),
            "drift_ssim": {"min": min(drift), "mean": statistics.fmean(drift), "argmin_sec": round(drift.index(min(drift)) / 24, 2)},
            "first_vs_input_ssim": first_vs_input[0] if first_vs_input else None,
        }
        print(name, json.dumps(results[name]))
    (OUT / "metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "",
        "## 客観指標（metrics.py）",
        "",
        "- seam: 2 周連結した動画の継ぎ目での隣接フレーム差（Y 平均）。median / p95 は継ぎ目以外の同指標。継ぎ目が p95 以下なら継ぎ目は動き幅の内側",
        "- drift SSIM min: 先頭フレームに対する各フレームの SSIM の最小値（低いほど静止対象が逸脱）。argmin はその時刻",
        "- first vs input: 先頭フレームと main.png（1080p 化）の SSIM。first = 入力 の忠実度",
        "",
        "| 候補 | seam | median | p95 | drift SSIM min (at s) | drift SSIM mean | first vs input SSIM |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in results.items():
        s = m["seam_yavg"]
        lines.append(
            f"| {name} | {s['seam']:.2f} | {s['median']:.2f} | {s['p95']:.2f} | {m['drift_ssim']['min']:.3f} ({m['drift_ssim']['argmin_sec']}) | {m['drift_ssim']['mean']:.3f} | {m['first_vs_input_ssim']:.3f} |"
        )
    with (OUT / "comparison.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
