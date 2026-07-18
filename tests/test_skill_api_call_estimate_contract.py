"""課金 API 利用 skill の「想定 API call 数」契約を機械検証する (issue #2010)。

抽出は 2 段マッピングで機械化する:

1. pyproject `[project.scripts]` の全 CLI を BILLED_CLIS / NON_BILLED_CLIS に全数分類する
   （新規 CLI を追加すると、どちらかへ分類するまでこのテストが fail する）。
2. 各 skill ディレクトリのテキストから登録済み CLI 名の参照を抽出し、課金 CLI を
   1 つ以上参照する skill を対象候補とする。CLI 名を参照するが自身では実行しない
   skill は NON_TARGET_SKILLS に、CLI 参照を伴わず課金を誘発する skill は
   EXTRA_BILLED_SKILLS に、それぞれ理由付きで登録する（対象一覧・非対象理由が
   このファイル上でレビュー可能に残る）。

対象 skill の SKILL.md には以下の形式の記載を要求する:

    ## 想定 API call 数

    | API | call 数 / 実行 | 変動要因 |
    |---|---|---|
    | <API 名> | <固定数 or 算出式> | <変動要因> |

    - 上限 / 承認: <上限・dry-run・確認プロンプト等の安全弁>
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"

# --- 1 段目: CLI → 課金 API 分類（実装の execute() / クライアント呼び出しを根拠に判定） ---

# 実行すると課金 API（Vertex AI Gemini / Veo / Lyria、OpenAI Images）または
# YouTube Data / Analytics API の quota を消費する CLI。
BILLED_CLIS: dict[str, str] = {
    "yt-analytics": "YouTube Data + Analytics API",
    "yt-benchmark-collect": "YouTube Data API",
    "yt-benchmark-comments": "YouTube Data API (commentThreads.list)",
    "yt-bulk-update-desc": "YouTube Data API (videos.update)",
    "yt-bulk-update-synthetic-media": "YouTube Data API (videos.update)",
    "yt-captions-upload": "YouTube Data API (captions.list/insert/update)",
    "yt-channel-seed": "YouTube Data API",
    "yt-channel-settings": "YouTube Data API (channels.update)",
    "yt-channel-status": "YouTube Data + Analytics API",
    "yt-oauth": "YouTube Data API (channels.list による接続テストのみ)",
    "yt-comments-reply": "YouTube Data API (comments.insert)",
    "yt-discover-competitors": "YouTube Data API (search.list)",
    "yt-fetch-stream-key": "YouTube Data API (liveStreams.list)",
    "yt-generate-image": "Vertex AI Gemini / OpenAI Images",
    "yt-generate-loop-video": "Vertex AI Veo",
    "yt-generate-lyria-master": "Vertex AI Lyria",
    "yt-generate-shorts-loop": "Vertex AI Veo",
    "yt-metadata-audit": "YouTube Data API (videos.list)",
    "yt-pinned-comment": "YouTube Data API (commentThreads.insert)",
    "yt-playlist-manager": "YouTube Data API (playlists/playlistItems)",
    "yt-playlist-status": "YouTube Data API (playlistItems.list)",
    "yt-shorts-bulk-update-loc": "YouTube Data API (videos.update)",
    "yt-stream-archive-check": "YouTube Data API (search.list)",
    "yt-stream-bandwidth": "YouTube Data API (--report の search.list のみ)",
    "yt-thumbnail-check": "Vertex AI Gemini Vision",
    "yt-thumbnail-compare": "YouTube Data API (benchmark stale 時の再収集誘発)",
    "yt-upload-auto": "YouTube Data API (videos.insert)",
    "yt-upload-collection": "YouTube Data API (videos.insert)",
    "yt-upload-shorts": "YouTube Data API (videos.insert)",
    "yt-video-analyze": "Vertex AI Gemini",
    "yt-wf-batch": "YouTube Data API (videos.insert。内部で yt-upload-collection を実行)",
}

# 課金 API を呼ばない CLI（ローカル処理・無料 API のみ）。
NON_BILLED_CLIS: dict[str, str] = {
    "yt-apply-rain-layers": "ローカル ffmpeg 合成のみ",
    "yt-automation-update": "バージョン pin bump / git 操作のみ",
    "yt-channel-init": "ローカルの config 雛形生成のみ",
    "yt-channel-trend": "収集済み analytics_data_*.json のローカル分析のみ",
    "yt-collection-preflight": "ローカルの事前チェックのみ",
    "yt-collection-serve": "ローカル HTTP サーバーのみ",
    "yt-cost-report": "ローカル cost_tracker JSON の表示のみ",
    "yt-distrokid-migrate": "ローカルのファイル移行のみ",
    "yt-distrokid-prepare": "ローカルの配信準備（ffprobe / Pillow）のみ",
    "yt-doctor": "gcloud subprocess + YouTube Reporting API（無料枠）のみ",
    "yt-finalize-master": "ローカル ffmpeg 処理のみ",
    "yt-generate-master": "ローカル ffmpeg クロスフェード結合のみ",
    "yt-generate-suno": "ローカルの Suno プロンプト生成のみ",
    "yt-init-collection": "ローカルの collection 雛形生成のみ",
    "yt-kpi-dashboard": "収集済みデータのローカル KPI 集計のみ",
    "yt-launch-curve": "収集済み analytics_data_*.json のローカル分析のみ",
    "yt-populate-scene-phrases": "翻訳 JSON は外部エージェント生成を受け取るのみ",
    "yt-preflight": "ローカルの事前チェックのみ",
    "yt-raw-master-check": "workflow-state.json と 01-master/ 実ファイルのローカル突合のみ",
    "yt-setup-dirs": "ローカルのディレクトリ雛形生成のみ",
    "yt-skills": "ローカルの skill 同期のみ",
    "yt-stock-archive": "ローカルの stock アセット管理のみ",
    "yt-stock-list": "ローカルの stock アセット管理のみ",
    "yt-stock-preview": "ローカルの stock アセット管理のみ",
    "yt-stock-prune": "ローカルの stock アセット管理のみ",
    "yt-suno-audio-cleanup": "ローカル音声ファイル整理のみ",
    "yt-suno-select-tracks": "ローカルのトラック選定のみ",
    "yt-suno-verify": "ローカル成果物検証のみ",
    "yt-suno-verify-playlist": "ローカル成果物検証のみ",
    "yt-theme-compare": "収集済みデータのローカル分析のみ",
    "yt-thumbnail-auto-select": "ローカルのサムネイル採点・選定のみ",
    "yt-thumbnail-correlate": "CDN 画像 DL + ローカル相関計算のみ",
    "yt-thumbnail-text": "ローカル PIL テキスト描画のみ",
    "yt-title-duplicate-check": "ローカルのタイトル照合のみ",
    "yt-traffic-trend": "収集済み analytics_data_*.json のローカル分析のみ",
    "yt-vote-log": "ローカルの投票ログ記録のみ",
}

# --- 2 段目: skill → 対象 / 非対象 ---

# 課金 CLI 名を参照するが、skill 自身の手順としては実行しない skill（非対象理由）。
NON_TARGET_SKILLS: dict[str, str] = {
    "analytics-analyze": (
        "収集済み analytics_data_*.json のローカル分析のみ。yt-analytics への言及は"
        "search_terms 欠測時に再収集（/analytics-collect の責務）を案内する"
        " cross-reference で、手順として実行しない"
    ),
    "automation-release": (
        "本リポジトリのリリース作業のみ。yt-upload-collection への言及は"
        "リリースノート内の例示参照で、手順として実行しない"
    ),
    "short-release": (
        "9:16 クリップの ffmpeg ローカル生成のみ。yt-upload-shorts への言及は"
        "アップロード未実装（スコープ外）の案内で、手順として実行しない"
    ),
    "suno": (
        "Suno プロンプトのローカル生成のみ。yt-video-analyze への言及は"
        "/video-analyze 出力 JSON の読込参照で、手順として実行しない"
    ),
    "videoup": (
        "ffmpeg によるローカル動画生成のみ。yt-generate-loop-video への言及は"
        "generate_videos.sh のエラー時案内メッセージで、手順として実行しない"
    ),
}

# 課金 CLI の参照を伴わずに課金 API 呼び出しを誘発する skill（追加対象理由）。
EXTRA_BILLED_SKILLS: dict[str, str] = {
    "flop-analysis": (
        "Phase 4 の仮説検証で /video-analyze（Vertex AI Gemini 課金)を承認プロンプトなしで自律実行しうる"
    ),
}

# 機械抽出の期待結果（対象一覧）。candidates ∪ EXTRA − NON_TARGET と一致すること。
TARGET_SKILLS: frozenset[str] = frozenset(
    {
        "analytics-collect",
        "automation-update",
        "benchmark",
        "channel-new",
        "channel-status",
        "collection-ideate",
        "comments-reply",
        "discover-competitors",
        "distrokid-helper",
        "flop-analysis",
        "loop-video",
        "lyria",
        "metadata-audit",
        "pinned-comment",
        "playlist",
        "setup",
        "short",
        "short-thumbnail",
        "streaming",
        "thumbnail",
        "thumbnail-compare",
        "video-analyze",
        "video-upload",
        "viewer-voice",
        "wf-new",
        "wf-next",
    }
)

_CLI_NAME_RE = re.compile(r"yt-[a-z][a-z0-9-]*")
_SECTION_HEADING = "## 想定 API call 数"
_TABLE_HEADER = "| API | call 数 / 実行 | 変動要因 |"
_LIMIT_LINE_RE = re.compile(r"^- 上限 / 承認: \S", re.MULTILINE)


def _registered_clis() -> set[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    return set(pyproject["project"]["scripts"])


def _skill_dirs() -> list[Path]:
    return sorted(d for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file())


def _referenced_clis(skill_dir: Path, registered: set[str]) -> set[str]:
    """skill 配下の全テキストから登録済み CLI 名の参照を抽出する。

    登録済み CLI 名と交差させることで、例示用の架空 CLI 名やチャンネル名
    （yt-legacy-uploader 等）を機械的に除外する。
    """
    found: set[str] = set()
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.update(m.group(0) for m in _CLI_NAME_RE.finditer(text))
    return found & registered


def _billed_candidates() -> dict[str, set[str]]:
    registered = _registered_clis()
    billed = set(BILLED_CLIS)
    candidates: dict[str, set[str]] = {}
    for skill_dir in _skill_dirs():
        hits = _referenced_clis(skill_dir, registered) & billed
        if hits:
            candidates[skill_dir.name] = hits
    return candidates


def test_cli_classification_partitions_entry_points() -> None:
    """全 CLI が課金 / 非課金のどちらか一方に分類されている（新規 CLI の分類漏れ検出）。"""
    registered = _registered_clis()
    billed = set(BILLED_CLIS)
    non_billed = set(NON_BILLED_CLIS)

    assert not billed & non_billed, f"二重分類: {sorted(billed & non_billed)}"
    unclassified = registered - billed - non_billed
    assert not unclassified, (
        f"未分類の CLI があります: {sorted(unclassified)}。 BILLED_CLIS / NON_BILLED_CLIS のいずれかへ分類してください"
    )
    stale = (billed | non_billed) - registered
    assert not stale, f"pyproject に存在しない CLI の分類が残っています: {sorted(stale)}"


def test_non_target_and_extra_skill_reasons_are_not_stale() -> None:
    """非対象理由・追加対象理由が現状の参照実態と食い違っていない。"""
    candidates = _billed_candidates()
    skills = {d.name for d in _skill_dirs()}

    for skill, reason in NON_TARGET_SKILLS.items():
        assert skill in skills, f"NON_TARGET_SKILLS に存在しない skill: {skill}"
        assert skill in candidates, (
            f"{skill} は課金 CLI を参照しなくなりました。 NON_TARGET_SKILLS から削除してください（登録理由: {reason}）"
        )
    for skill, reason in EXTRA_BILLED_SKILLS.items():
        assert skill in skills, f"EXTRA_BILLED_SKILLS に存在しない skill: {skill}"
        assert skill not in candidates, (
            f"{skill} は課金 CLI を直接参照するようになりました。"
            f" EXTRA_BILLED_SKILLS の登録は冗長です（登録理由: {reason}）"
        )
    overlap = set(NON_TARGET_SKILLS) & set(EXTRA_BILLED_SKILLS)
    assert not overlap, f"対象と非対象に二重登録: {sorted(overlap)}"


def test_target_set_matches_mechanical_extraction() -> None:
    """対象一覧 = (課金 CLI 参照 skill ∪ 追加対象) − 非対象、が成立する。"""
    candidates = _billed_candidates()
    derived = (set(candidates) | set(EXTRA_BILLED_SKILLS)) - set(NON_TARGET_SKILLS)
    missing = derived - TARGET_SKILLS
    extra = TARGET_SKILLS - derived
    assert not missing, (
        "課金 CLI を参照する skill が対象一覧にありません: "
        + ", ".join(f"{s} (参照: {sorted(candidates.get(s, set()))})" for s in sorted(missing))
        + "。TARGET_SKILLS へ追加して SKILL.md に「想定 API call 数」を記載するか、"
        "実行しない参照であれば NON_TARGET_SKILLS に理由を登録してください"
    )
    assert not extra, f"課金 CLI 参照が消えた skill が対象一覧に残っています: {sorted(extra)}"


@pytest.mark.parametrize("skill", sorted(TARGET_SKILLS))
def test_target_skill_documents_estimated_api_calls(skill: str) -> None:
    """対象 skill の SKILL.md に「想定 API call 数」の見積もり契約が記載されている。"""
    skill_md = SKILLS_DIR / skill / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    assert _SECTION_HEADING in text, f"{skill}/SKILL.md に `{_SECTION_HEADING}` セクションがありません"
    section = text.split(_SECTION_HEADING, 1)[1]
    section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]

    assert _TABLE_HEADER in section, (
        f"{skill}/SKILL.md の想定 API call 数セクションに判定表 `{_TABLE_HEADER}` がありません"
    )
    table_body = section.split(_TABLE_HEADER, 1)[1].splitlines()
    data_rows = [
        line for line in table_body if line.startswith("|") and not line.startswith("|-") and line.strip("| -")
    ]
    assert data_rows, f"{skill}/SKILL.md の判定表にデータ行がありません"
    assert _LIMIT_LINE_RE.search(section), (
        f"{skill}/SKILL.md の想定 API call 数セクションに `- 上限 / 承認: <安全弁>` の行がありません"
    )
