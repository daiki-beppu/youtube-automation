#!/usr/bin/env python3
"""
動画ファイル検証ユーティリティ
アップロード前の動画ファイル品質・整合性チェック
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Dict, List, Optional

from youtube_automation.domains.media.audio_formats import AUDIO_EXTS

logger = logging.getLogger(__name__)


# --- YouTube アップロード制限 ---
MAX_FILE_SIZE_BYTES = 128 * 1024 * 1024 * 1024  # 128 GB
MAX_DURATION_SEC = 12 * 3600  # 12 時間
MIN_RESOLUTION_PX = 144

# --- ビットレート推奨範囲 (bps) ---
BITRATE_4K = (35_000_000, 68_000_000)
BITRATE_1080P = (8_000_000, 12_000_000)
BITRATE_720P = (5_000_000, 7_500_000)

SUPPORTED_CODECS = ["h264", "h265", "hevc", "vp9", "av1"]


class VideoValidator:
    """動画ファイル検証クラス"""

    def __init__(self, metadata_reader: Callable[[Path], Optional[Dict]]):
        """検証対象の metadata reader を受け取って初期化する。"""
        self._metadata_reader = metadata_reader
        self.validation_results = []

    def validate_collection(self, collection_path: str) -> Dict:
        """
        コレクション全体の動画ファイル検証

        Args:
            collection_path (str): コレクションディレクトリパス

        Returns:
            Dict: 検証結果
        """
        collection_dir = Path(collection_path)

        if not collection_dir.exists():
            return {"error": f"コレクションディレクトリが存在しません: {collection_path}"}

        results = {
            "collection_path": str(collection_dir),
            "collection_name": collection_dir.name,
            "master_video": None,
            "individual_videos": [],
            "errors": [],
            "warnings": [],
            "summary": {"total": 0, "valid": 0, "invalid": 0},
        }

        # マスター動画検証
        master_result = self._validate_master_video(collection_dir)
        results["master_video"] = master_result

        if master_result:
            results["summary"]["total"] += 1
            if master_result.get("valid", False):
                results["summary"]["valid"] += 1
            else:
                results["summary"]["invalid"] += 1

        # 個別動画検証
        individual_results = self._validate_individual_videos(collection_dir)
        results["individual_videos"] = individual_results

        for video_result in individual_results:
            results["summary"]["total"] += 1
            if video_result.get("valid", False):
                results["summary"]["valid"] += 1
            else:
                results["summary"]["invalid"] += 1

        # 全体的な問題チェック
        overall_issues = self._check_overall_consistency(collection_dir, results)
        results["errors"].extend(overall_issues.get("errors", []))
        results["warnings"].extend(overall_issues.get("warnings", []))

        return results

    def _validate_master_video(self, collection_dir: Path) -> Optional[Dict]:
        """マスター動画の検証"""
        # マスター動画ファイル検索
        master_candidates = []

        # 03-Individual-movie/ 内のマスター動画
        video_dir = collection_dir / "03-Individual-movie"
        if video_dir.exists():
            master_candidates.extend(video_dir.glob("*master*.mp4"))

        # 01-master/ 内の動画
        master_dir = collection_dir / "01-master"
        if master_dir.exists():
            master_candidates.extend(master_dir.glob("*.mp4"))

        if not master_candidates:
            return {"error": "マスター動画ファイルが見つかりません", "valid": False}

        if len(master_candidates) > 1:
            return {
                "error": f"複数のマスター動画ファイルが見つかりました: {[f.name for f in master_candidates]}",
                "valid": False,
            }

        master_video = master_candidates[0]
        return self._validate_single_video(master_video, "master")

    def _validate_individual_videos(self, collection_dir: Path) -> List[Dict]:
        """個別動画の検証"""
        video_dir = collection_dir / "03-Individual-movie"

        if not video_dir.exists():
            return [{"error": "03-Individual-movie ディレクトリが存在しません", "valid": False}]

        video_files = [f for f in video_dir.glob("*.mp4") if "master" not in f.name.lower()]

        if not video_files:
            return [{"error": "個別動画ファイルが見つかりません", "valid": False}]

        results = []
        for video_file in sorted(video_files):
            result = self._validate_single_video(video_file, "individual")
            results.append(result)

        return results

    def _validate_single_video(self, video_path: Path, video_type: str) -> Dict:
        """単一動画ファイルの検証"""
        result = {
            "file_path": str(video_path),
            "file_name": video_path.name,
            "file_size": 0,
            "video_type": video_type,
            "duration": 0,
            "resolution": None,
            "codec": None,
            "bitrate": None,
            "valid": False,
            "errors": [],
            "warnings": [],
        }

        try:
            # ファイル存在確認
            if not video_path.exists():
                result["errors"].append(f"ファイルが存在しません: {video_path}")
                return result

            # ファイルサイズ取得
            result["file_size"] = video_path.stat().st_size

            # adapter が取得したメタデータを domain policy で検証する
            metadata = self._metadata_reader(video_path)

            if metadata:
                result.update(metadata)

                # 基本検証
                validation_errors = self._validate_video_properties(result, video_type)
                result["errors"].extend(validation_errors)

                # 警告チェック
                warnings = self._check_video_warnings(result, video_type)
                result["warnings"].extend(warnings)

                # 有効性判定
                result["valid"] = len(result["errors"]) == 0
            else:
                result["errors"].append("動画メタデータの取得に失敗しました")

        except (OSError, ValueError, TypeError) as e:
            result["errors"].append(f"検証エラー: {e}")

        return result

    def _validate_video_properties(self, video_info: Dict, video_type: str) -> List[str]:
        """動画プロパティの検証"""
        errors = []

        # ファイルサイズチェック
        if video_info["file_size"] == 0:
            errors.append("ファイルサイズが0です")
        elif video_info["file_size"] > MAX_FILE_SIZE_BYTES:
            errors.append("ファイルサイズがYouTube上限（128GB）を超えています")

        # 動画長チェック
        duration = video_info["duration"]
        if duration == 0:
            errors.append("動画の長さが取得できません")
        elif duration < 1:  # 1秒未満
            errors.append("動画が短すぎます（1秒未満）")
        elif duration > MAX_DURATION_SEC:
            errors.append("動画がYouTube上限（12時間）を超えています")

        # 解像度チェック
        resolution = video_info.get("resolution", "0x0")
        if resolution == "0x0":
            errors.append("解像度が取得できません")
        else:
            try:
                width, height = map(int, resolution.split("x"))
                if width < MIN_RESOLUTION_PX or height < MIN_RESOLUTION_PX:
                    errors.append("解像度が低すぎます（最小144p）")
            except (TypeError, ValueError):
                errors.append("解像度の形式が不正です")

        # コーデックチェック
        codec = video_info.get("codec", "")
        if codec.lower() not in SUPPORTED_CODECS:
            errors.append(f"サポートされていないコーデックです: {codec}")

        return errors

    def _check_video_warnings(self, video_info: Dict, video_type: str) -> List[str]:
        """動画の警告チェック"""
        warnings = []

        # ビットレート警告
        bitrate = video_info.get("bitrate")
        if bitrate:
            # 4K: 35-68 Mbps, 1080p: 8-12 Mbps, 720p: 5-7.5 Mbps
            resolution = video_info.get("resolution", "0x0")
            try:
                _width, height = map(int, resolution.split("x"))

                if height >= 2160:  # 4K
                    lo, hi = BITRATE_4K
                    if bitrate < lo or bitrate > hi:
                        warnings.append("4K動画のビットレートが推奨範囲外です（35-68 Mbps）")
                elif height >= 1080:  # 1080p
                    lo, hi = BITRATE_1080P
                    if bitrate < lo or bitrate > hi:
                        warnings.append("1080p動画のビットレートが推奨範囲外です（8-12 Mbps）")
                elif height >= 720:  # 720p
                    lo, hi = BITRATE_720P
                    if bitrate < lo or bitrate > hi:
                        warnings.append("720p動画のビットレートが推奨範囲外です（5-7.5 Mbps）")
            except (ValueError, TypeError, AttributeError):
                # resolution が "WxH" 形式でない / 数値変換できない場合は
                # ビットレート警告をスキップする（判定はベストエフォート）
                pass

        # フレームレート警告
        fps = video_info.get("fps", 0)
        if fps > 0:
            if fps < 24:
                warnings.append("フレームレートが低い可能性があります（24fps未満）")
            elif fps > 60:
                warnings.append("フレームレートが高く、ファイルサイズが大きい可能性があります（60fps超）")

        # 動画タイプ別チェック
        if video_type == "individual":
            duration = video_info["duration"]
            if duration < 30:
                warnings.append("個別楽曲としては短い可能性があります（30秒未満）")
            elif duration > 600:  # 10分
                warnings.append("個別楽曲としては長い可能性があります（10分超）")

        return warnings

    def _check_overall_consistency(self, collection_dir: Path, results: Dict) -> Dict:
        """コレクション全体の整合性チェック"""
        issues = {"errors": [], "warnings": []}

        # 音声ファイルと動画ファイルの数の整合性
        audio_dir = collection_dir / "02-Individual-music"
        if audio_dir.exists():
            audio_files = [f for f in audio_dir.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
            video_count = len(results["individual_videos"])

            if len(audio_files) != video_count:
                issues["warnings"].append(
                    f"音声ファイル数（{len(audio_files)}）と動画ファイル数（{video_count}）が一致しません"
                )

        # サムネイル画像の存在確認
        assets_dir = collection_dir / "10-assets"
        if assets_dir.exists():
            thumbnail_files = list(assets_dir.glob("*.png"))
            if not thumbnail_files:
                issues["warnings"].append("サムネイル画像（PNG）が見つかりません")
        else:
            issues["warnings"].append("10-assets ディレクトリが存在しません")

        return issues

    def generate_validation_report(self, validation_results: Dict) -> str:
        """検証結果レポート生成"""
        lines = []

        lines.append("📹 動画ファイル検証レポート")
        lines.append("=" * 50)
        lines.append(f"🎵 コレクション: {validation_results['collection_name']}")
        lines.append(f"📁 パス: {validation_results['collection_path']}")
        lines.append("")

        # サマリー
        summary = validation_results["summary"]
        lines.append(f"📊 検証結果: {summary['valid']}/{summary['total']} ファイル有効")

        if summary["invalid"] > 0:
            lines.append(f"❌ 無効ファイル: {summary['invalid']}個")

        lines.append("")

        # マスター動画
        master = validation_results["master_video"]
        if master:
            status = "✅" if master.get("valid", False) else "❌"
            lines.append(f"{status} マスター動画: {master.get('file_name', 'N/A')}")

            if master.get("duration"):
                minutes = int(master["duration"] // 60)
                seconds = int(master["duration"] % 60)
                lines.append(f"   ⏱️ 長さ: {minutes}:{seconds:02d}")

            if master.get("resolution"):
                lines.append(f"   🖼️ 解像度: {master['resolution']}")

            for error in master.get("errors", []):
                lines.append(f"   ❌ {error}")

            for warning in master.get("warnings", []):
                lines.append(f"   ⚠️ {warning}")

        lines.append("")

        # 個別動画
        individual_videos = validation_results["individual_videos"]
        if individual_videos:
            lines.append(f"🎶 個別動画: {len(individual_videos)}本")

            valid_count = sum(1 for v in individual_videos if v.get("valid", False))
            lines.append(f"   ✅ 有効: {valid_count}本")

            invalid_count = len(individual_videos) - valid_count
            if invalid_count > 0:
                lines.append(f"   ❌ 無効: {invalid_count}本")

            # エラーがある動画のみ詳細表示
            for video in individual_videos:
                if video.get("errors") or video.get("warnings"):
                    status = "✅" if video.get("valid", False) else "❌"
                    lines.append(f"   {status} {video.get('file_name', 'N/A')}")

                    for error in video.get("errors", []):
                        lines.append(f"      ❌ {error}")

                    for warning in video.get("warnings", []):
                        lines.append(f"      ⚠️ {warning}")

        # 全体的な問題
        if validation_results["errors"] or validation_results["warnings"]:
            lines.append("")
            lines.append("🔍 全体的な問題:")

            for error in validation_results["errors"]:
                lines.append(f"❌ {error}")

            for warning in validation_results["warnings"]:
                lines.append(f"⚠️ {warning}")

        lines.append("")
        lines.append("=" * 50)

        return "\n".join(lines)
