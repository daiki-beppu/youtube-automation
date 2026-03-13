#!/usr/bin/env python3
"""コレクション用ループ動画背景を Veo 3.1 API で生成する。

main.png を開始・終了フレーム両方に指定し、微細なアニメーション付きの
シームレスなループ動画を生成する。

Usage:
    # コレクションパス指定
    python3 generate_loop_video.py <collection-path>
    python3 generate_loop_video.py <collection-path> --prompt "gentle wind..."

    # CWD がコレクションディレクトリの場合
    python3 generate_loop_video.py

    # FFmpeg クロスフェード補正
    python3 generate_loop_video.py <collection-path> --smooth
"""

import argparse
import os
import sys
import time
from pathlib import Path

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

import utils._path_setup  # noqa: F401, E402
from utils.veo_generator import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    generate_loop_video,
    smooth_loop,
)


def load_config() -> dict:
    """ChannelConfig から veo 設定を読み込む。"""
    try:
        from utils.channel_config import ChannelConfig  # noqa: E402
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
    # 既存 loop.mp4 がある場合は連番で退避
    output_path = collection_path / "10-assets" / "loop.mp4"
    if output_path.exists():
        n = 1
        while True:
            backup = collection_path / "10-assets" / f"loop-v{n}.mp4"
            if not backup.exists():
                break
            n += 1
        output_path.rename(backup)
        print(f"  [Backup] 既存ファイルを {backup.name} にリネーム")
    return image_path, output_path


def main():
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Veo 3.1 コレクションループ動画生成")
    parser.add_argument("collection", nargs="?", help="コレクションパス")
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
    if args.collection:
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
        smooth_loop(output_path, args.crossfade, trim_tail_sec=0.0)

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
