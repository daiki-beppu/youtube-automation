#!/usr/bin/env python3
"""Veo 3.1 API 経由でループ動画背景を生成する。

main.png を開始・終了フレーム両方に指定し、微細なアニメーション付きの
シームレスなループ動画を生成する。

Usage:
    # コレクションモード（10-assets/main.png → 10-assets/loop.mp4）
    python3 generate_loop_video.py <collection-path>
    python3 generate_loop_video.py <collection-path> --prompt "gentle wind..."

    # ダイレクトモード
    python3 generate_loop_video.py --image /path/to/image.png --output /path/to/loop.mp4

    # FFmpeg クロスフェード補正
    python3 generate_loop_video.py <collection-path> --smooth
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

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


def load_config() -> dict:
    """ChannelConfig から veo 設定を読み込む。"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from utils.channel_config import ChannelConfig
        config = ChannelConfig.load()
        return config.raw.get("veo", {})
    except Exception:
        return {}


def resolve_collection_paths(collection_path: Path) -> tuple[Path, Path]:
    """コレクションパスから入力画像と出力動画のパスを解決する。"""
    image_path = collection_path / "10-assets" / "main.png"
    if not image_path.exists():
        # JPEG フォールバック
        image_path = collection_path / "10-assets" / "main.jpg"
    output_path = collection_path / "10-assets" / "loop.mp4"
    return image_path, output_path


def generate_loop_video(client, image_path: Path, output_path: Path, model: str, prompt: str) -> bool:
    """Veo 3.1 API でループ動画を生成する。"""
    from google.genai import types

    image = types.Image.from_file(location=str(image_path))

    print(f"  [Submit] モデル={model}")
    print(f"  [Image]  {image_path.name}")
    print(f"  [Prompt] {prompt[:100]}...")
    print(f"  [Config] 16:9 / 1080p / 8秒 / ループ（開始=終了フレーム）")
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
    duration_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
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


def main():
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Veo 3.1 ループ動画生成")
    parser.add_argument("collection", nargs="?", help="コレクションパス")
    parser.add_argument("--image", help="入力画像パス（ダイレクトモード）")
    parser.add_argument("--output", help="出力動画パス（ダイレクトモード）")
    parser.add_argument("--prompt", help="動画生成プロンプト")
    parser.add_argument("--model", help="Veo モデル名")
    parser.add_argument("--smooth", action="store_true", help="FFmpeg クロスフェードでループ補正")
    parser.add_argument("--crossfade", type=float, default=0.5, help="クロスフェード秒数 (デフォルト: 0.5)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    # 設定読み込み
    veo_config = load_config()
    model = args.model or veo_config.get("model", DEFAULT_MODEL)
    prompt = args.prompt or veo_config.get("default_prompt", DEFAULT_PROMPT)

    # パス解決
    if args.image and args.output:
        # ダイレクトモード
        image_path = Path(args.image).resolve()
        output_path = Path(args.output).resolve()
    elif args.collection:
        collection_path = Path(args.collection)
        if not collection_path.is_absolute():
            collection_path = Path.cwd() / collection_path
        image_path, output_path = resolve_collection_paths(collection_path)
    else:
        # CWD がコレクションディレクトリか確認
        cwd = Path.cwd()
        if (cwd / "10-assets").exists():
            image_path, output_path = resolve_collection_paths(cwd)
        else:
            parser.error("コレクションパスを指定するか、コレクションディレクトリ内で実行してください")
            return

    # バリデーション
    if not image_path.exists():
        print(f"[ERROR] 入力画像が見つかりません: {image_path}")
        sys.exit(1)

    # 確認
    print()
    print("===========================================")
    print("  Veo 3.1 ループ動画生成")
    print("===========================================")
    print(f"  入力:   {image_path}")
    print(f"  出力:   {output_path}")
    print(f"  モデル: {model}")
    print(f"  補正:   {'あり' if args.smooth else 'なし'}")
    print("===========================================")
    print()

    if not args.yes:
        answer = input("  生成しますか？ [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  キャンセルしました。")
            sys.exit(0)

    # API キー確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 環境変数が設定されていません。")
        print("  export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)

    # SDK インポート
    try:
        from google import genai
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  pip3 install google-genai --break-system-packages")
        sys.exit(1)

    # 生成実行
    client = genai.Client()
    start_time = time.monotonic()
    success = generate_loop_video(client, image_path, output_path, model, prompt)

    if success and args.smooth:
        smooth_loop(output_path, args.crossfade)

    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  ループ動画生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  ループ動画生成: 失敗")
        print("  --prompt でプロンプトを変えて再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
