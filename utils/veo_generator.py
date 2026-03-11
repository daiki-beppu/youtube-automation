"""Veo 3.1 動画生成の共有コア。

generate_loop_video.py / generate_veo_video.py から共通利用される
API 呼び出し・音声除去・クロスフェード補正の関数群。
"""

import subprocess
import time
from pathlib import Path

# --- 定数 ---
DEFAULT_MODEL = "veo-3.1-generate-preview"
DEFAULT_PROMPT = (
    "Static scene with only natural subtle movements: gentle flickering of candle flames, "
    "slight sway of character breathing, soft light shifts on surfaces. "
    "No smoke, no magical effects, no particles, no falling objects. "
    "Keep the scene calm and grounded, like a living painting."
)
POLL_INTERVAL_SEC = 20
MAX_POLL_SEC = 600  # 10分タイムアウト


def generate_loop_video(client, image_path: Path, output_path: Path, model: str, prompt: str) -> bool:
    """Veo 3.1 API でループ動画を生成する。"""
    from google.genai import types

    image = types.Image.from_file(location=str(image_path))

    print(f"  [Submit] モデル={model}")
    print(f"  [Image]  {image_path.name}")
    print(f"  [Prompt] {prompt[:100]}...")
    print("  [Config] 16:9 / 1080p / 8秒 / ループ（開始=終了フレーム）")
    print()

    try:
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            image=image,
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9",
                resolution="1080p",
                number_of_videos=1,
                duration_seconds=8,
                person_generation="allow_adult",
                last_frame=image,
            ),
        )
    except Exception as e:
        print(f"  [ERROR]  API 呼び出し失敗: {e}")
        return False

    # ポーリングで完了待ち
    print("  [Wait]   動画生成中...", end="", flush=True)
    start = time.monotonic()
    while not operation.done:
        elapsed = time.monotonic() - start
        if elapsed > MAX_POLL_SEC:
            print(f"\n  [ERROR]  タイムアウト ({MAX_POLL_SEC}秒)")
            return False
        print(".", end="", flush=True)
        time.sleep(POLL_INTERVAL_SEC)
        operation = client.operations.get(operation)
    elapsed = time.monotonic() - start
    print(f" 完了 ({elapsed:.0f}秒)")

    # 結果取得・保存
    if not operation.response or not operation.response.generated_videos:
        print("  [ERROR]  動画が生成されませんでした")
        return False

    video_obj = operation.response.generated_videos[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        client.files.download(file=video_obj.video)
        video_obj.video.save(str(output_path))
    except Exception as e:
        print(f"  [ERROR]  動画保存失敗: {e}")
        return False

    # Veo 3.1 はデフォルトで音声を生成するため、音声トラックを除去
    strip_audio(output_path)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  [Done]   保存完了 → {output_path} ({size_mb:.1f} MB)")
    return True


def strip_audio(video_path: Path) -> None:
    """FFmpeg で音声トラックを除去する。"""
    tmp = video_path.with_stem(video_path.stem + "_tmp")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-c:v", "copy", "-an", str(tmp)],
            check=True, capture_output=True, text=True,
        )
        tmp.rename(video_path)
        print("  [Strip]  音声トラック除去済み")
    except subprocess.CalledProcessError:
        if tmp.exists():
            tmp.unlink()


def smooth_loop(video_path: Path, crossfade_sec: float = 0.5) -> bool:
    """FFmpeg クロスフェードでループの継ぎ目を滑らかにする。"""
    output = video_path.with_stem(video_path.stem + "_smooth")
    duration_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
    ]
    try:
        duration = float(subprocess.check_output(duration_cmd, text=True).strip())
    except Exception as e:
        print(f"  [ERROR]  動画長取得失敗: {e}")
        return False

    trim_end = duration - crossfade_sec
    # 末尾と先頭をクロスフェードで結合
    filter_complex = (
        f"[0]split[main][tail];"
        f"[main]trim=0:{trim_end},setpts=PTS-STARTPTS[a];"
        f"[tail]trim={trim_end}:{duration},setpts=PTS-STARTPTS[b];"
        f"[b][a]xfade=transition=fade:duration={crossfade_sec}:offset=0[out]"
    )

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-an",
        str(output),
    ]

    print(f"  [FFmpeg] クロスフェード補正 ({crossfade_sec}秒)...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR]  FFmpeg 失敗: {e.stderr[:200]}")
        return False

    # 元ファイルをバックアップして置き換え
    backup = video_path.with_stem(video_path.stem + "_raw")
    video_path.rename(backup)
    output.rename(video_path)
    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"  [Done]   補正完了 → {video_path} ({size_mb:.1f} MB)")
    print(f"  [Backup] 元ファイル → {backup}")
    return True
