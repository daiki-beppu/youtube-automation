#!/usr/bin/env python
"""PROTOTYPE (#4896) — 使い捨て。リポジトリの engine 実装には組み込まない。

fal.ai 経由の MiniMax H3 Max / H3 Max Turbo（image-to-video）を、承認済み Veo Fast 1080p の
loop.mp4 と比較するための実測スクリプト。`requests` 直叩き、FAL_KEY は `op read`。

サブコマンド:
  run      アップロード → 5 本を直列 submit → ダウンロード → ffmpeg 後処理 → results.json / comparison.md / compare.html
  recheck  保存済み response_url / status_url / CDN URL を GET し、保持状況を retention.jsonl に追記
  pricing  GET api.fal.ai/v1/models/pricing の応答形を記録

実行例:
  <repo>/.venv/bin/python fal_h3_compare.py run --out out
  <repo>/.venv/bin/python fal_h3_compare.py recheck --out out
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

CHANNEL = Path(
    "~/ghq/github.com/daiki-beppu/youtube-channels-workspace/channels/001ch-afro-deep-noir"
).expanduser()
COLLECTION = CHANNEL / "collections/live/20260714-adn-deep-melodic-collection"
MAIN_PNG = COLLECTION / "10-assets/main.png"
VEO_LOOP = COLLECTION / "10-assets/loop.mp4"  # 承認済みベースライン（6.5 s, smooth 済み）
VEO_RAW = COLLECTION / "10-assets/loop_raw.mp4"  # Veo 生出力（8 s, 音声付き）
THUMBNAIL_YAML = CHANNEL / "config/skills/thumbnail.yaml"

QUEUE = "https://queue.fal.run"
REST = "https://rest.fal.ai"
PRICING = "https://api.fal.ai/v1/models/pricing"
ENDPOINTS = {
    "turbo": "minimax/h3-max-turbo/image-to-video",
    "max": "minimax/h3-max/image-to-video",
}
# 通常単価（USD/s, 768P）。9/7 まで 75% off（Max 0.02 / Turbo 0.01）
UNIT_PRICE_USD_PER_SEC = {"turbo": 0.04, "max": 0.08}
PROMO_FACTOR = 0.25

DURATION = 8
RESOLUTION = "768P"
SEED = 4896
CANVAS_16_9 = (1344, 768)
UPSCALE_16_9 = (1920, 1080)
# smooth_loop 既定（veo_generator.smooth_loop）と揃える
TRIM_TAIL_SEC = 1.0
CROSSFADE_SEC = 0.5
CRF = 18
PRESET = "slow"
POLL_SEC = 2.0
MAX_POLL_SEC = 600

# 比較条件（直列に実行）。lifecycle は submit 時の X-Fal-Object-Lifecycle-Preference 検証用
RUNS = [
    {"name": "turbo-balanced", "engine": "turbo", "mode": "balanced", "image": "original"},
    {"name": "turbo-quality", "engine": "turbo", "mode": "quality", "image": "original"},
    {"name": "max-balanced", "engine": "max", "mode": "balanced", "image": "original"},
    {"name": "max-quality", "engine": "max", "mode": "quality", "image": "original", "lifecycle_sec": 86400},
    {"name": "turbo-balanced-resized", "engine": "turbo", "mode": "balanced", "image": "resized"},
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def fal_key() -> str:
    out = subprocess.run(
        ["op", "read", "op://Personal/fal_API_Key/credential"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def auth_headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Key {key}"}


def load_prompt() -> str:
    cfg = yaml.safe_load(THUMBNAIL_YAML.read_text(encoding="utf-8"))
    return str(cfg["loop"]["veo"]["default_prompt"]).strip()


def prevalidate(payload: dict) -> None:
    """422 でも課金され得るので submit 前にクライアント側で検証する。"""
    assert 5 <= payload["duration"] <= 15, "duration は 5〜15"
    assert payload["resolution"] in {"480P", "768P"}, "resolution は 480P / 768P"
    assert payload["prompt_expansion_mode"] in {"balanced", "quality"}, "expansion mode"
    assert 0 < len(payload["prompt"]) < 2000, "prompt 長"
    for k in ("image_url", "end_image_url"):
        assert payload[k].startswith("https://"), k


def ffprobe(path: Path) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,bit_rate,sample_rate,channels"
            ":format=duration,size,bit_rate",
            "-of", "json", "--", str(path),
        ],
        text=True,
    )
    data = json.loads(out)
    fmt = data.get("format", {})
    summary = {
        "duration_sec": float(fmt.get("duration", 0)),
        "size_bytes": int(fmt.get("size", 0)),
        "bit_rate": int(fmt.get("bit_rate", 0)),
        "streams": [],
    }
    for s in data.get("streams", []):
        item = {"type": s.get("codec_type"), "codec": s.get("codec_name")}
        if s.get("codec_type") == "video":
            item.update(width=s.get("width"), height=s.get("height"), fps=s.get("r_frame_rate"), bit_rate=s.get("bit_rate"))
        else:
            item.update(sample_rate=s.get("sample_rate"), channels=s.get("channels"), bit_rate=s.get("bit_rate"))
        summary["streams"].append(item)
    return summary


def ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def resize_to_canvas(src: Path, dst: Path, size: tuple[int, int]) -> None:
    w, h = size
    ffmpeg([
        "-i", str(src),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}",
        "-frames:v", "1", str(dst),
    ])


def strip_audio(src: Path, dst: Path) -> None:
    ffmpeg(["-i", str(src), "-c:v", "copy", "-an", str(dst)])


def upscale_and_smooth(src: Path, dst: Path, size: tuple[int, int]) -> None:
    """768P → 1080p（lanczos）+ smooth_loop 同型（末尾 trim + xfade）を 1 パスで掛ける。"""
    probe = ffprobe(src)
    duration = probe["duration_sec"]
    usable_end = duration - TRIM_TAIL_SEC
    trim_end = usable_end - CROSSFADE_SEC
    w, h = size
    fc = (
        f"[0:v]scale={w}:{h}:flags=lanczos,trim=0:{usable_end},setpts=PTS-STARTPTS[trimmed];"
        f"[trimmed]split[main][tail];"
        f"[main]trim=0:{trim_end},setpts=PTS-STARTPTS[a];"
        f"[tail]trim={trim_end}:{usable_end},setpts=PTS-STARTPTS[b];"
        f"[b][a]xfade=transition=fade:duration={CROSSFADE_SEC}:offset=0[out]"
    )
    ffmpeg([
        "-i", str(src), "-filter_complex", fc, "-map", "[out]",
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF), "-pix_fmt", "yuv420p", "-an", str(dst),
    ])


def double_loop(src: Path, dst: Path) -> None:
    """継ぎ目確認用に 2 周連結（stream copy）。"""
    ffmpeg(["-stream_loop", "1", "-i", str(src), "-c", "copy", str(dst)])


# ---------------------------------------------------------------- fal calls


def upload_image(key: str, path: Path, *, lifecycle_sec: int = 86400) -> dict:
    t0 = time.monotonic()
    r = requests.post(
        f"{REST}/storage/upload/initiate",
        params={"storage_type": "fal-cdn-v3"},
        headers={
            **auth_headers(key),
            "Content-Type": "application/json",
            "X-Fal-Object-Lifecycle-Preference": json.dumps({"expiration_duration_seconds": lifecycle_sec}),
        },
        json={"file_name": path.name, "content_type": "image/png"},
        timeout=60,
    )
    r.raise_for_status()
    init = r.json()
    put = requests.put(init["upload_url"], data=path.read_bytes(), headers={"Content-Type": "image/png"}, timeout=300)
    put.raise_for_status()
    return {
        "file_url": init["file_url"],
        "initiate_keys": sorted(init.keys()),
        "put_status": put.status_code,
        "upload_sec": round(time.monotonic() - t0, 2),
        "bytes": path.stat().st_size,
    }


def submit(key: str, endpoint: str, payload: dict, *, lifecycle_sec: int | None) -> tuple[dict, float, dict]:
    headers = {**auth_headers(key), "Content-Type": "application/json"}
    if lifecycle_sec is not None:
        headers["X-Fal-Object-Lifecycle-Preference"] = json.dumps({"expiration_duration_seconds": lifecycle_sec})
    t0 = time.monotonic()
    r = requests.post(f"{QUEUE}/{endpoint}", headers=headers, json=payload, timeout=60)
    elapsed = time.monotonic() - t0
    if r.status_code >= 400:
        raise RuntimeError(f"submit failed status={r.status_code} error_type={r.headers.get('X-Fal-Error-Type')} body={r.text[:500]}")
    interesting = {k: v for k, v in r.headers.items() if k.lower().startswith("x-fal")}
    return r.json(), elapsed, interesting


def poll(key: str, status_url: str) -> tuple[dict, list[dict]]:
    t0 = time.monotonic()
    history: list[dict] = []
    while True:
        r = requests.get(status_url, params={"logs": "1"}, headers=auth_headers(key), timeout=60)
        r.raise_for_status()
        body = r.json()
        history.append({"t": round(time.monotonic() - t0, 2), "status": body.get("status"), "queue_position": body.get("queue_position")})
        if body.get("status") == "COMPLETED":
            return body, history
        if time.monotonic() - t0 > MAX_POLL_SEC:
            raise TimeoutError(status_url)
        time.sleep(POLL_SEC)


def fetch_result(key: str, response_url: str) -> dict:
    r = requests.get(response_url, headers=auth_headers(key), timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"result failed status={r.status_code} error_type={r.headers.get('X-Fal-Error-Type')} body={r.text[:500]}")
    return r.json()


def download(url: str, dst: Path) -> float:
    t0 = time.monotonic()
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with dst.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return time.monotonic() - t0


# ---------------------------------------------------------------- commands


def cmd_pricing(args: argparse.Namespace) -> None:
    key = fal_key()
    out = {}
    for name, endpoint in ENDPOINTS.items():
        r = requests.get(PRICING, params={"endpoint_id": endpoint}, headers=auth_headers(key), timeout=60)
        try:
            body = r.json()
        except ValueError:
            body = r.text[:1000]
        out[name] = {"status": r.status_code, "body": body, "fetched_at": now()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "pricing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    key = fal_key()
    prompt = load_prompt()
    print(f"[prompt] {prompt}")

    # 入力画像 2 種をアップロード（original / 1344×768 リサイズ）
    resized_png = out / "main-1344x768.png"
    resize_to_canvas(MAIN_PNG, resized_png, CANVAS_16_9)
    uploads = {
        "original": upload_image(key, MAIN_PNG),
        "resized": upload_image(key, resized_png),
    }
    print(f"[upload] {json.dumps(uploads, ensure_ascii=False)}")

    # Veo ベースラインも同じ後処理（2 周連結）を掛けて並べる
    veo_dir = out / "veo-fast-1080p"
    veo_dir.mkdir(exist_ok=True)
    shutil.copy(VEO_LOOP, veo_dir / "final.mp4")
    double_loop(veo_dir / "final.mp4", veo_dir / "final-2x.mp4")
    baseline = {
        "name": "veo-fast-1080p",
        "engine": "veo-3.1-fast-generate-001",
        "note": "既存の承認済み loop.mp4（再生成なし）",
        "probe_raw": ffprobe(VEO_RAW),
        "probe_final": ffprobe(VEO_LOOP),
        "cost_usd_normal": 0.80,
    }

    results = []
    for spec in RUNS:
        name = spec["name"]
        run_dir = out / name
        run_dir.mkdir(exist_ok=True)
        endpoint = ENDPOINTS[spec["engine"]]
        image_url = uploads[spec["image"]]["file_url"]
        payload = {
            "prompt": prompt,
            "image_url": image_url,
            "end_image_url": image_url,
            "duration": DURATION,
            "resolution": RESOLUTION,
            "prompt_expansion_mode": spec["mode"],
            "seed": SEED,
        }
        prevalidate(payload)
        record: dict = {**spec, "endpoint": endpoint, "payload": payload, "submitted_at": now()}
        print(f"\n=== {name} ({endpoint}, {spec['mode']}, image={spec['image']}) ===")
        try:
            t_wall0 = time.monotonic()
            q, submit_sec, fal_headers = submit(key, endpoint, payload, lifecycle_sec=spec.get("lifecycle_sec"))
            record.update(
                request_id=q.get("request_id"),
                response_url=q.get("response_url"),
                status_url=q.get("status_url"),
                cancel_url=q.get("cancel_url"),
                queue_position=q.get("queue_position"),
                submit_sec=round(submit_sec, 2),
                submit_headers=fal_headers,
            )
            print(f"[submit] request_id={q.get('request_id')} queue_position={q.get('queue_position')} ({submit_sec:.2f}s)")
            status, history = poll(key, q["status_url"])
            record["poll_history"] = history
            record["metrics"] = status.get("metrics")
            record["logs"] = status.get("logs")
            record["completed_wall_sec"] = round(time.monotonic() - t_wall0, 2)
            result = fetch_result(key, q["response_url"])
            record["result_completed_at"] = now()
            record["result_keys"] = sorted(result.keys())
            record["expanded_prompt"] = result.get("expanded_prompt")
            record["timings"] = result.get("timings")
            video = result.get("video") or {}
            record["video"] = {k: video.get(k) for k in ("url", "content_type", "file_name", "file_size")}
            if result.get("error_type") or result.get("error"):
                record["error"] = {"error_type": result.get("error_type"), "detail": str(result.get("detail") or result.get("error"))[:300]}
                raise RuntimeError(record["error"])
            raw = run_dir / "raw.mp4"
            record["download_sec"] = round(download(video["url"], raw), 2)
            record["total_submit_to_file_sec"] = round(time.monotonic() - t_wall0, 2)
            print(f"[done] submit→file {record['total_submit_to_file_sec']}s, inference={record['timings']}")
            (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            (run_dir / "expanded_prompt.txt").write_text(str(record["expanded_prompt"]), encoding="utf-8")

            # 後処理: ffprobe(raw) → strip_audio → upscale+smooth → 2 周連結
            record["probe_raw"] = ffprobe(raw)
            noaudio = run_dir / "noaudio.mp4"
            strip_audio(raw, noaudio)
            final = run_dir / "final.mp4"
            upscale_and_smooth(noaudio, final, UPSCALE_16_9)
            double_loop(final, run_dir / "final-2x.mp4")
            record["probe_final"] = ffprobe(final)
            unit = UNIT_PRICE_USD_PER_SEC[spec["engine"]]
            record["cost_usd_normal"] = round(unit * DURATION, 2)
            record["cost_usd_promo"] = round(unit * DURATION * PROMO_FACTOR, 3)
            record["static_hint_kept"] = _static_hint_kept(record["expanded_prompt"])
        except Exception as exc:  # 使い捨て: 続行して次の候補へ
            record["failure"] = repr(exc)[:800]
            print(f"[FAIL] {name}: {record['failure']}")
        results.append(record)
        (out / "results.json").write_text(
            json.dumps({"generated_at": now(), "prompt": prompt, "seed": SEED, "uploads": uploads, "baseline": baseline, "runs": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    write_markdown(out, prompt, baseline, results)
    write_html(out, prompt, baseline, results)
    print(f"\n[ok] {out / 'comparison.md'} / {out / 'compare.html'}")


_STATIC_WORDS = ("locked", "static", "fixed camera", "no camera movement", "still", "preserve composition", "no new objects")


def _static_hint_kept(expanded: str | None) -> dict:
    text = (expanded or "").lower()
    return {w: (w in text) for w in _STATIC_WORDS}


def write_markdown(out: Path, prompt: str, baseline: dict, results: list[dict]) -> None:
    lines = [
        "# fal.ai H3 Max / Turbo vs Veo Fast 実測比較（#4896）",
        "",
        f"- 生成日時: {now()}",
        f"- プロンプト（Veo と同一）: `{prompt}`",
        f"- 条件: {DURATION} 秒 / {RESOLUTION} / seed={SEED} / first = last 同一画像 / 後処理は strip_audio → 1920×1080 lanczos → trim {TRIM_TAIL_SEC}s + xfade {CROSSFADE_SEC}s（CRF {CRF} {PRESET}）",
        "- 単価は通常価格（Turbo 0.04 / Max 0.08 USD/s）。9/7 まで 75% off のためプロモ値を併記",
        "",
        "| 候補 | mode | 入力 | submit→file (s) | inference (s) | 生出力 実寸/fps | 音声 | 生 size (MB) | 生 bitrate (Mbps) | final size (MB) | USD 通常 / プロモ | 状態 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    v = baseline["probe_raw"]["streams"][0]
    lines.append(
        f"| Veo Fast 1080p（承認済み） | — | original | —（typ. 60〜120） | — | {v['width']}×{v['height']} @ {v['fps']} | あり (aac) | "
        f"{baseline['probe_raw']['size_bytes']/1e6:.1f} | {baseline['probe_raw']['bit_rate']/1e6:.1f} | {baseline['probe_final']['size_bytes']/1e6:.1f} | 0.80 / — | baseline |"
    )
    for r in results:
        if "failure" in r:
            lines.append(f"| {r['name']} | {r['mode']} | {r['image']} | — | — | — | — | — | — | — | — | FAIL: {r['failure'][:80]} |")
            continue
        pv = next(s for s in r["probe_raw"]["streams"] if s["type"] == "video")
        pa = [s for s in r["probe_raw"]["streams"] if s["type"] == "audio"]
        audio = f"あり ({pa[0]['codec']} {pa[0]['sample_rate']}Hz {pa[0]['channels']}ch)" if pa else "なし"
        inf = (r.get("timings") or {}).get("inference")
        lines.append(
            f"| {r['name']} | {r['mode']} | {r['image']} | {r['total_submit_to_file_sec']} | {inf} | {pv['width']}×{pv['height']} @ {pv['fps']} | {audio} | "
            f"{r['probe_raw']['size_bytes']/1e6:.1f} | {r['probe_raw']['bit_rate']/1e6:.1f} | {r['probe_final']['size_bytes']/1e6:.1f} | {r['cost_usd_normal']} / {r['cost_usd_promo']} | ok |"
        )
    lines += ["", "## expanded_prompt と静止指示の残存", ""]
    for r in results:
        if "failure" in r:
            continue
        kept = ", ".join(k for k, v in r["static_hint_kept"].items() if v) or "（該当語なし）"
        lines += [f"### {r['name']}", "", f"- 残存語: {kept}", "", "```", str(r["expanded_prompt"]), "```", ""]
    lines += [
        "## 目視評価（ユーザー記入）",
        "",
        "`compare.html` を開き、継ぎ目・静止対象の逸脱・画質の 3 観点で Veo と「同等以上 / 劣る」を候補ごとに記録する。",
        "",
        "| 候補 | 継ぎ目 | 静止対象の逸脱 | 画質 | 総合 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['name']} |  |  |  |  |")
    lines += ["", "## request 保持・CDN 寿命", "", "`recheck` の結果は `retention.jsonl` を参照。", ""]
    (out / "comparison.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(out: Path, prompt: str, baseline: dict, results: list[dict]) -> None:
    cards = []
    entries = [("veo-fast-1080p", "Veo Fast 1080p（承認済みベースライン）", None)] + [
        (r["name"], f"{r['name']}（{r['endpoint'].split('/')[1]} / {r['mode']} / {r['image']}）", r) for r in results if "failure" not in r
    ]
    for name, label, r in entries:
        meta = ""
        if r:
            inf = (r.get("timings") or {}).get("inference")
            meta = f"submit→file {r['total_submit_to_file_sec']}s · inference {inf}s · USD {r['cost_usd_normal']}（promo {r['cost_usd_promo']}）"
        verdict = "" if r is None else f"""
        <div class="verdict" data-name="{name}">
          {''.join(f'<label>{crit}<select data-crit="{crit}"><option value="">—</option><option>同等以上</option><option>劣る</option></select></label>' for crit in ('継ぎ目', '静止対象の逸脱', '画質'))}
          <input type="text" placeholder="メモ" data-note>
        </div>"""
        cards.append(f"""
      <section class="card">
        <h2>{label}</h2>
        <video src="{name}/final-2x.mp4" controls loop muted playsinline preload="metadata"></video>
        <p class="meta">{meta}</p>{verdict}
      </section>""")
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>#4896 fal H3 vs Veo 比較</title>
<style>
body{{font-family:system-ui;margin:16px;background:#111;color:#eee}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:16px}}
.card{{background:#1c1c1c;border-radius:8px;padding:12px}} video{{width:100%;background:#000}}
h2{{font-size:14px;margin:0 0 8px}} .meta{{font-size:12px;color:#aaa}} label{{font-size:12px;margin-right:8px}}
select,input{{background:#222;color:#eee;border:1px solid #444;border-radius:4px;padding:2px 4px}}
textarea{{width:100%;height:160px;background:#000;color:#0f0;font-family:monospace}}
.bar{{position:sticky;top:0;background:#111;padding:8px 0;display:flex;gap:8px;align-items:center}}
button{{padding:6px 12px}}
</style></head><body>
<div class="bar"><button onclick="playAll()">全部再生</button><button onclick="pauseAll()">全部停止</button>
<button onclick="seekAll(6.0)">継ぎ目へ（6.0s）</button><button onclick="exportVerdict()">評価を JSON に書き出す</button>
<span class="meta">動画は各候補を 2 周連結したもの。継ぎ目は 6.5 秒付近。prompt: {prompt}</span></div>
<div class="grid">{''.join(cards)}</div>
<h2>評価 JSON（コピーして Claude に貼る）</h2><textarea id="out"></textarea>
<script>
const vids=[...document.querySelectorAll('video')];
function playAll(){{vids.forEach(v=>v.play())}} function pauseAll(){{vids.forEach(v=>v.pause())}}
function seekAll(t){{vids.forEach(v=>{{v.currentTime=t;v.play()}})}}
function exportVerdict(){{const o={{}};document.querySelectorAll('.verdict').forEach(d=>{{const r={{}};d.querySelectorAll('select').forEach(s=>r[s.dataset.crit]=s.value);r.note=d.querySelector('[data-note]').value;o[d.dataset.name]=r}});document.getElementById('out').value=JSON.stringify(o,null,2)}}
</script></body></html>"""
    (out / "compare.html").write_text(html, encoding="utf-8")


def cmd_recheck(args: argparse.Namespace) -> None:
    key = fal_key()
    data = json.loads((args.out / "results.json").read_text(encoding="utf-8"))
    log = args.out / "retention.jsonl"
    rows = []
    for r in data["runs"]:
        if "request_id" not in r:
            continue
        row = {"checked_at": now(), "name": r["name"], "request_id": r["request_id"], "result_completed_at": r.get("result_completed_at")}
        for label, url, auth in (
            ("status_url", r.get("status_url"), True),
            ("response_url", r.get("response_url"), True),
            ("cdn_video_url", (r.get("video") or {}).get("url"), False),
        ):
            if not url:
                continue
            try:
                resp = requests.get(url, headers=auth_headers(key) if auth else {}, timeout=60, stream=not auth)
                item = {"status": resp.status_code, "error_type": resp.headers.get("X-Fal-Error-Type")}
                if auth:
                    try:
                        body = resp.json()
                        item["has_video_url"] = bool((body.get("video") or {}).get("url")) if isinstance(body, dict) else None
                        item["status_field"] = body.get("status") if isinstance(body, dict) else None
                        item["detail"] = str(body.get("detail"))[:120] if isinstance(body, dict) and body.get("detail") else None
                    except ValueError:
                        item["body"] = resp.text[:120]
                else:
                    item["content_length"] = resp.headers.get("Content-Length")
                resp.close()
            except requests.RequestException as exc:
                item = {"exception": type(exc).__name__}
            row[label] = item
        rows.append(row)
    for u_name, u in data["uploads"].items():
        try:
            resp = requests.get(u["file_url"], timeout=60, stream=True)
            rows.append({"checked_at": now(), "name": f"upload:{u_name}", "cdn_input_url": {"status": resp.status_code, "content_length": resp.headers.get("Content-Length")}})
            resp.close()
        except requests.RequestException as exc:
            rows.append({"checked_at": now(), "name": f"upload:{u_name}", "cdn_input_url": {"exception": type(exc).__name__}})
    with log.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(rows, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("recheck", cmd_recheck), ("pricing", cmd_pricing)):
        sp = sub.add_parser(name)
        sp.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
        sp.set_defaults(fn=fn)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
