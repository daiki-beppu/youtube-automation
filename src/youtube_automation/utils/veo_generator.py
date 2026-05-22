"""Veo 3.1 動画生成の共有コア。

generate_loop_video.py / generate_veo_video.py から共通利用される
API 呼び出し・音声除去・クロスフェード補正の関数群。
"""

import re
import subprocess
import time
from pathlib import Path

from youtube_automation.utils import cost_tracker
from youtube_automation.utils import veo_operation_store as op_store
from youtube_automation.utils.profile import section

# --- 定数 ---
DEFAULT_MODEL = "veo-3.1-fast-generate-001"
DEFAULT_PROMPT = (
    "Static scene with only natural subtle movements: gentle flickering of candle flames, "
    "slight sway of character breathing, soft light shifts on surfaces. "
    "No smoke, no magical effects, no particles, no falling objects. "
    "Keep the scene calm and grounded, like a living painting."
)
POLL_INTERVAL_SEC = 5
MAX_POLL_SEC = 600  # 10分タイムアウト


def _is_unrecoverable_operation_error(exc: Exception) -> bool:
    """operation.get の例外が再開不能（not found / 404 等）かどうかを判定する。

    一時的な API 障害（接続エラー等）は False を返し、state を保持するべき。
    404 / not_found 等の確定的な失効エラーは True を返し、state を削除するべき。
    """
    msg = str(exc).lower()
    return "not found" in msg or "404" in msg


def _handle_operations_get_error(exc: Exception, output_path: Path) -> None:
    """operations.get の例外に応じて state を管理し、エラーメッセージを出力する。

    失効 operation (not found / 404) は state を削除する。
    一時的な API 障害は state を保持し、次回実行で再開できるようにする。
    """
    if _is_unrecoverable_operation_error(exc):
        print(f"\n  [ERROR]  operation.get 失敗（失効 operation、state を削除）: {exc}")
        op_store.clear(output_path)
    else:
        print(f"\n  [ERROR]  operation.get 失敗（一時障害、state を保持）: {exc}")


def _resume_operation(client, gen_types, output_path: Path, requested_model: str, state: dict):
    """保存済み operation を復元し、resume 用の operation と実効モデルを返す。"""
    saved_model = state["model"]
    operation_name = state["operation_name"]
    if saved_model != requested_model:
        print(
            f"  [Warn]   保存済みモデル ({saved_model}) と引数モデル ({requested_model}) が異なります。"
            f"保存済みモデルで続行します"
        )
    print(f"  [Resume] 前回の operation を引き継ぎます: {operation_name}")
    operation = gen_types.GenerateVideosOperation(name=operation_name)
    try:
        operation = client.operations.get(operation)
    except KeyboardInterrupt:
        _print_interrupt_messages(output_path)
        return None, saved_model
    except Exception as exc:
        _handle_operations_get_error(exc, output_path)
        return None, saved_model
    return operation, saved_model


def _join_natural(items: list[str]) -> str:
    """list[str] を英文として自然に結合する (Oxford comma 付き)。"""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def build_structured_prompt(
    motion_targets: list[str],
    static_targets: list[str],
    template: str,
    base_rules: str,
) -> str:
    """motion / static のリストからテンプレ展開で Veo 3.1 用英文プロンプトを生成する。

    motion_targets が strip + filter 後に空なら ValueError を送出する。

    テンプレ内のプレースホルダ:
      - {motion_clause}: motion_targets を自然結合した英文
      - {static_clause}: static_targets を自然結合した英文 (空なら "the rest of the scene")
      - {base_rules}: 共通追加ルール
    """
    motion = [t.strip() for t in motion_targets if t and t.strip()]
    if not motion:
        raise ValueError("motion_targets is empty after strip/filter")

    static = [t.strip() for t in static_targets if t and t.strip()]
    static_clause = _join_natural(static) if static else "the rest of the scene"
    motion_clause = _join_natural(motion)

    prompt = template
    prompt = prompt.replace("{motion_clause}", motion_clause)
    prompt = prompt.replace("{static_clause}", static_clause)
    prompt = prompt.replace("{base_rules}", base_rules or "")
    # base_rules が空のときにテンプレ内で連続スペースが残るので 1 個に正規化
    prompt = re.sub(r" {2,}", " ", prompt)
    return prompt.strip()


def _submit_operation(
    client,
    gen_types,
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    aspect_ratio: str,
    duration_seconds: int,
):
    """新規 generate_videos を実行し、state 保存後の operation を返す。"""
    image = gen_types.Image.from_file(location=str(image_path))
    print(f"  [Submit] モデル={model}")
    print(f"  [Image]  {image_path.name}")
    print(f"  [Prompt] {prompt[:100]}...")
    print(f"  [Config] {aspect_ratio} / 1080p / {duration_seconds}秒 / ループ（開始=終了フレーム）")
    print()
    try:
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            image=image,
            config=gen_types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                resolution="1080p",
                number_of_videos=1,
                duration_seconds=duration_seconds,
                person_generation="allow_adult",
                last_frame=image,
            ),
        )
    except KeyboardInterrupt:
        print("\n  [Interrupt] Ctrl+C 検出（submit 中断）、resume 不可")
        return None
    except Exception as exc:
        print(f"  [ERROR]  API 呼び出し失敗: {exc}")
        return None

    if operation.name:
        op_store.save(output_path, operation.name, model)
    else:
        print("  [Warn]   operation.name が空のため state を保存できません")
    return operation


def _wait_for_operation(client, operation, output_path: Path):
    """operation 完了まで polling し、完了 operation を返す。"""
    print("  [Wait]   動画生成中...", end="", flush=True)
    start = time.monotonic()
    with section("veo.poll_total", interval_sec=POLL_INTERVAL_SEC):
        try:
            while not operation.done:
                elapsed = time.monotonic() - start
                if elapsed > MAX_POLL_SEC:
                    print(f"\n  [ERROR]  タイムアウト ({MAX_POLL_SEC}秒)")
                    return None
                print(".", end="", flush=True)
                time.sleep(POLL_INTERVAL_SEC)
                try:
                    with section("veo.operations_get"):
                        operation = client.operations.get(operation)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    _handle_operations_get_error(exc, output_path)
                    return None
        except KeyboardInterrupt:
            _print_interrupt_messages(output_path)
            return None
    elapsed = time.monotonic() - start
    print(f" 完了 ({elapsed:.0f}秒)")
    return operation


def _persist_generated_video(operation, output_path: Path) -> bool:
    """生成済み動画を output_path へ保存する。"""
    if not operation.response or not operation.response.generated_videos:
        print("  [ERROR]  動画が生成されませんでした")
        op_store.clear(output_path)
        return False

    video_obj = operation.response.generated_videos[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_bytes = getattr(video_obj.video, "video_bytes", None)
    if not video_bytes:
        print("  [ERROR]  動画バイト列が取得できませんでした")
        op_store.clear(output_path)
        return False
    output_path.write_bytes(video_bytes)
    return True


def _finalize_generated_video(
    output_path: Path,
    effective_model: str,
    duration_seconds: int,
    aspect_ratio: str,
    compression: dict | None = None,
) -> None:
    """保存済み動画の後処理と課金ログ出力を行う。

    compression が有効なら libx264 再エンコードで音声除去も同時に行うため
    `strip_audio` の stream copy パスを skip し、ffmpeg 起動を 1 回に集約する。
    """
    if compression and compression.get("enabled", True):
        compress_loop(
            output_path,
            crf=int(compression.get("crf", 22)),
            preset=str(compression.get("preset", "slow")),
        )
    else:
        strip_audio(output_path)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  [Done]   保存完了 → {output_path} ({size_mb:.1f} MB)")

    entry = cost_tracker.log_generation(
        "video",
        model=effective_model,
        quantity=duration_seconds,
        unit="second",
        metadata={
            "duration_sec": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "resolution": "1080p",
            "output_file": cost_tracker.relative_to_channel_dir(output_path),
        },
    )
    cost_tracker.print_last_report(entry)
    op_store.clear(output_path)


def generate_loop_video(
    client,
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 8,
    compression: dict | None = None,
) -> bool:
    """Veo 3.1 API でループ動画を生成する。

    前回 Ctrl+C で中断した state が残っている場合は generate_videos を呼ばずに
    保存済み operation_name から polling を再開する（二重課金防止）。
    """
    from google.genai import types as gen_types

    state = op_store.load(output_path)

    if state is not None:
        operation, effective_model = _resume_operation(client, gen_types, output_path, model, state)
        if operation is None:
            return False
    else:
        effective_model = model
        operation = _submit_operation(
            client,
            gen_types,
            image_path,
            output_path,
            model,
            prompt,
            aspect_ratio,
            duration_seconds,
        )
        if operation is None:
            return False

    operation = _wait_for_operation(client, operation, output_path)
    if operation is None:
        return False

    if not _persist_generated_video(operation, output_path):
        return False
    _finalize_generated_video(output_path, effective_model, duration_seconds, aspect_ratio, compression=compression)
    return True


def _print_interrupt_messages(output_path: Path) -> None:
    """KeyboardInterrupt 受信時にユーザー向けメッセージを出力する。"""
    state_file = op_store.state_path(output_path)
    print("\n  [Interrupt] Ctrl+C 検出、API 側継続")
    print("  [Resume] 再実行で operation を引き継ぎます")
    print(f"  [State] {state_file}")


def strip_audio(video_path: Path) -> None:
    """FFmpeg で音声トラックを除去する。"""
    tmp = video_path.with_stem(video_path.stem + "_tmp")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-c:v", "copy", "-an", str(tmp)],
            check=True,
            capture_output=True,
            text=True,
        )
        tmp.rename(video_path)
        print("  [Strip]  音声トラック除去済み")
    except subprocess.CalledProcessError:
        if tmp.exists():
            tmp.unlink()


def trim_tail(video_path: Path, trim_sec: float = 1.0) -> bool:
    """Veo 末尾のノイズ/歪みを除去する（映像コピー、再エンコードなし）。"""
    duration_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "--",
        str(video_path),
    ]
    try:
        duration = float(subprocess.check_output(duration_cmd, text=True).strip())
    except Exception as e:
        print(f"  [ERROR]  動画長取得失敗: {e}")
        return False

    usable = duration - trim_sec
    if usable <= 0:
        print(f"  [ERROR]  動画が短すぎます ({duration:.1f}秒)")
        return False

    tmp = video_path.with_stem(video_path.stem + "_trimmed")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-t", str(usable), "-c:v", "copy", "-an", str(tmp)],
            check=True,
            capture_output=True,
            text=True,
        )
        tmp.rename(video_path)
        print(f"  [Trim]   末尾 {trim_sec}秒カット（{duration:.1f}秒 → {usable:.1f}秒）")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR]  トリム失敗: {e.stderr[:200]}")
        if tmp.exists():
            tmp.unlink()
        return False


def compress_loop(video_path: Path, crf: int = 22, preset: str = "slow") -> bool:
    """libx264 で loop.mp4 を再エンコードして容量削減する（Issue #175）。

    Veo 3.1 由来の `loop.mp4` は 1080p で 5.6〜6.0 Mbps あり、`generate_videos.sh` が
    stream copy で本編動画を組むため最終マスター動画もそのビットレートを継承する。
    本編動画は YouTube 側で VP9/AV1 に再 transcoding されるため、CRF 22 程度の
    再圧縮では視聴品質に有意な影響は出ない（issue 本文の検証参照）。
    """
    tmp = video_path.with_stem(video_path.stem + "_compressed")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(tmp),
    ]
    try:
        with section("veo.compress_loop.ffmpeg", crf=crf, preset=preset):
            subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR]  圧縮失敗: {e.stderr[:200]}")
        if tmp.exists():
            tmp.unlink()
        return False
    tmp.rename(video_path)
    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"  [Compress] CRF {crf} / preset {preset} → {size_mb:.1f} MB")
    return True


def smooth_loop(
    video_path: Path,
    crossfade_sec: float = 0.5,
    trim_tail_sec: float = 1.0,
    crf: int = 18,
    preset: str = "slow",
) -> bool:
    """末尾トリム + FFmpeg クロスフェードでループの継ぎ目を滑らかにする。

    Veo 3.1 は末尾にノイズ/歪みを生成することがあるため、
    trim_tail_sec でカットしてからクロスフェードで結合する。
    再エンコード時の crf/preset は compress_loop と揃えると `--smooth` 実行後も
    `compress_loop` 由来の容量削減効果を維持できる（Issue #175）。
    """
    output = video_path.with_stem(video_path.stem + "_smooth")
    duration_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "--",
        str(video_path),
    ]
    try:
        duration = float(subprocess.check_output(duration_cmd, text=True).strip())
    except Exception as e:
        print(f"  [ERROR]  動画長取得失敗: {e}")
        return False

    # 末尾トリム（ノイズ除去）+ クロスフェード用の分割点
    usable_end = duration - trim_tail_sec
    trim_end = usable_end - crossfade_sec
    if trim_end <= 0:
        print(f"  [ERROR]  動画が短すぎます ({duration:.1f}秒)")
        return False

    print(f"  [Trim]   末尾 {trim_tail_sec}秒カット（{duration:.1f}秒 → {usable_end:.1f}秒）")

    # 末尾と先頭をクロスフェードで結合
    filter_complex = (
        f"[0]trim=0:{usable_end},setpts=PTS-STARTPTS[trimmed];"
        f"[trimmed]split[main][tail];"
        f"[main]trim=0:{trim_end},setpts=PTS-STARTPTS[a];"
        f"[tail]trim={trim_end}:{usable_end},setpts=PTS-STARTPTS[b];"
        f"[b][a]xfade=transition=fade:duration={crossfade_sec}:offset=0[out]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-an",
        str(output),
    ]

    print(f"  [FFmpeg] クロスフェード補正 ({crossfade_sec}秒, CRF {crf} / preset {preset})...")
    try:
        with section("veo.smooth_loop.ffmpeg", crossfade_sec=crossfade_sec):
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
