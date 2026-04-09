# テスト書き直し設計: Khorikov「単体テストの考え方/使い方」準拠

## 概要

現在の 12 モジュール・270+ テストを Vladimir Khorikov の原則に基づいて書き直す。
パイロット 2 モジュールでパターンを確立し、残りに展開する。

## 移行手順（安全ネット）

既存テストは安全ネットとして機能している。原則への準拠を目的化せず、
「このテストは何を守っているのか」を 1 つ 1 つ確認してから書き直す。

1. **新テストを `tests/unit/` or `tests/integration/` に追加**（既存テストは触らない）
2. **新旧両方を実行し、同等のカバレッジを確認** — `pytest tests/` で全テスト通過
3. **新テストが同等の回帰保護を提供することを確認してから旧テストを削除**
4. 旧テスト削除は新テスト追加とは別のコミットで行う（revert 容易性）

## 適用する原則

### テスト分類の優先順位

| 優先順位 | スタイル | 適用先 |
|---------|---------|-------|
| 1st | 出力ベース | 純粋関数（入力→出力の検証） |
| 2nd | 状態ベース | 状態を持つオブジェクト（操作後の状態検証） |
| 3rd | コミュニケーションベース | 外部システム境界のみ（管理下にない依存） |

### 核心ルール

1. **mock は管理下にない依存（YouTube API, ffmpeg 等の外部プロセス）にのみ使う** — 自プロジェクト内クラス間は mock しない
2. **観察可能な振る舞いを検証する** — 戻り値・例外・状態変化で検証。コミュニケーションベース（`assert_called` 等）は管理下にない依存への副作用検証にのみ使う（例: YouTube API への動画アップロードが実行されたことの確認）
3. **1 テスト = 1 振る舞い** — AAA（Arrange-Act-Assert）厳守、Assert は 1 つの論理的概念
4. **テスト名はビジネス上の振る舞いを記述する** — 実装寄りの名前（`test_converts_seconds_to_m_ss_format`）ではなく、利用者視点の名前（`test_formats_duration_for_display`）にする。テストがドキュメントとしての価値を持つように
5. **プライベートメソッドを直接テストしない** — 公開 API 経由で間接的に検証
6. **Humble Object パターン** — ビジネスロジックをインフラから分離し、ロジックを出力ベースでテスト

### ユニットテスト vs 統合テスト

- **ユニットテスト**: 高速、プロセス外依存なし、単一の振る舞いを検証
- **統合テスト**: プロセス外依存との統合を検証、ハッピーパス + 重要異常系のみ

### 統合テストの「重要異常系」判断基準

以下に該当するものを重要異常系として統合テストでカバーする:

1. **ユーザーのデータ・資産を守る異常系** — アップロード失敗時にファイルが破損しない、部分アップロードがリトライ可能
2. **外部 API 固有の振る舞い** — YouTube API の HTTP 5xx リトライ、レートリミット（429）、認証トークン期限切れ
3. **課金・クォータに影響する異常系** — API クォータ超過時の適切な停止
4. **サイレント失敗を防ぐ異常系** — レスポンスに video_id が含まれない場合の検出

該当しないもの（ユニットテストで十分）: 入力バリデーション、フォーマット変換、純粋なロジック分岐

## ディレクトリ構成

```
tests/
├── unit/              # 出力ベース・状態ベーステスト（mock なしまたは最小限）
├── integration/       # YouTube API 等の外部依存との統合テスト
├── conftest.py        # 共有フィクスチャ（CHANNEL_DIR 設定等）
└── fixtures/          # テストデータ（現状維持）
    └── sample_channel/
```

## パイロット 1: test_time_utils.py（出力ベーステストの模範）

### 配置

`tests/unit/test_time_utils.py`

### 方針

- クラスは「関数 x 振る舞いカテゴリ」でグループ化（読みやすさのため維持）
- テスト名は `test_<振る舞いの説明>` 形式
- `@pytest.mark.parametrize` で同一振る舞いの複数ケースをまとめる
- 境界値（0, 負数, 大きな値）を明示的にカバー
- assert は各テストで 1 つの論理的概念

### 例

```python
class TestFormatDurationMss:
    """タイムスタンプ表示用の M:SS フォーマット"""

    @pytest.mark.parametrize("seconds, expected", [
        (0, "0:00"),
        (59, "0:59"),
        (90, "1:30"),
        (3600, "60:00"),
    ])
    def test_formats_duration_for_timestamp_display(self, seconds, expected):
        assert format_duration_mss(seconds) == expected

    def test_truncates_fractional_seconds(self):
        assert format_duration_mss(90.9) == "1:30"
```

## パイロット 2: test_upload_core.py（Humble Object パターン）

### 配置

- `tests/unit/test_upload_logic.py` — 抽出したロジック関数のテスト
- `tests/integration/test_upload_core.py` — YouTubeUploadCore の統合テスト

### プロダクションコード変更

`utils/upload_core.py` からワークフローロジックをドメインモデルとして抽出する。
単純な述語関数だけでなく、判断の連鎖をカプセル化する。

```python
# utils/upload_policy.py — アップロードに関するドメインロジック

from dataclasses import dataclass

MAX_THUMBNAIL_BYTES = 2_097_152
COMPRESSION_QUALITIES = (2, 5)
MAX_RETRY_ATTEMPTS = 5
RETRYABLE_HTTP_STATUSES = frozenset({500, 502, 503, 504})


@dataclass(frozen=True)
class ThumbnailCompression:
    """サムネイル圧縮ワークフローの判断結果"""
    needs_compression: bool
    qualities_to_try: tuple[int, ...] = ()

    @classmethod
    def for_file(cls, file_size: int, max_bytes: int = MAX_THUMBNAIL_BYTES) -> "ThumbnailCompression":
        if file_size <= max_bytes:
            return cls(needs_compression=False)
        return cls(needs_compression=True, qualities_to_try=COMPRESSION_QUALITIES)

    def next_quality(self, failed_qualities: set[int]) -> int | None:
        """次に試すべき品質を返す。全て試行済みなら None"""
        for q in self.qualities_to_try:
            if q not in failed_qualities:
                return q
        return None


@dataclass(frozen=True)
class RetryDecision:
    """リトライ判断の結果"""
    should_retry: bool
    delay_seconds: float = 0.0

    @classmethod
    def for_http_error(cls, status_code: int, current_attempt: int) -> "RetryDecision":
        if status_code not in RETRYABLE_HTTP_STATUSES:
            return cls(should_retry=False)
        if current_attempt >= MAX_RETRY_ATTEMPTS:
            return cls(should_retry=False)
        return cls(should_retry=True, delay_seconds=float(2 ** current_attempt))
```

`YouTubeUploadCore` はこれらのドメインオブジェクトに判断を委譲し、自身は API 呼び出しと
ファイル I/O のみを行う薄いシェルになる。

### ユニットテスト（出力ベース、mock なし）

```python
# tests/unit/test_upload_policy.py

class TestThumbnailCompression:
    def test_skips_compression_for_small_file(self):
        result = ThumbnailCompression.for_file(1000)
        assert result.needs_compression is False

    def test_requires_compression_for_oversized_file(self):
        result = ThumbnailCompression.for_file(3_000_000)
        assert result.needs_compression is True
        assert result.qualities_to_try == (2, 5)

    def test_boundary_at_exact_limit_skips_compression(self):
        result = ThumbnailCompression.for_file(MAX_THUMBNAIL_BYTES)
        assert result.needs_compression is False

    def test_suggests_next_quality_in_order(self):
        comp = ThumbnailCompression.for_file(3_000_000)
        assert comp.next_quality(failed_qualities=set()) == 2
        assert comp.next_quality(failed_qualities={2}) == 5
        assert comp.next_quality(failed_qualities={2, 5}) is None


class TestRetryDecision:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_server_error(self, status):
        decision = RetryDecision.for_http_error(status, current_attempt=0)
        assert decision.should_retry is True
        assert decision.delay_seconds > 0

    @pytest.mark.parametrize("status", [400, 403, 404, 429])
    def test_gives_up_on_client_error(self, status):
        decision = RetryDecision.for_http_error(status, current_attempt=0)
        assert decision.should_retry is False

    def test_gives_up_after_max_attempts(self):
        decision = RetryDecision.for_http_error(503, current_attempt=MAX_RETRY_ATTEMPTS)
        assert decision.should_retry is False

    def test_exponential_backoff_delay(self):
        d1 = RetryDecision.for_http_error(503, current_attempt=0)
        d3 = RetryDecision.for_http_error(503, current_attempt=3)
        assert d1.delay_seconds == 1.0
        assert d3.delay_seconds == 8.0
```

### 統合テスト（YouTube API 境界のみ mock）

```python
# tests/integration/test_upload_core.py

class TestSetThumbnail:
    def test_sets_thumbnail_for_small_image(self, tmp_path, youtube_mock):
        """2MB 以下の画像はそのままアップロードされる"""
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)
        core = make_upload_core(youtube_mock)

        result = core.set_thumbnail("video123", str(thumb))

        assert result is True

    def test_returns_false_when_file_inaccessible(self, youtube_mock):
        """ファイルアクセスエラー時は False を返す"""
        core = make_upload_core(youtube_mock)

        result = core.set_thumbnail("video123", "/nonexistent/thumb.jpg")

        assert result is False
```

**統合テストのルール:**
- mock は YouTube API サービスオブジェクトのみ（管理下にない依存）
- コミュニケーションベース検証（`assert_called` 等）は管理下にない依存への副作用検証にのみ使う（例: YouTube API に動画が送信されたことの確認）。戻り値・例外・状態で検証できる場合はそちらを優先
- 上記「重要異常系の判断基準」に該当するケースのみカバー

## 残りモジュールの展開計画

### 出力ベース書き直し（time_utils パターン）

| モジュール | 配置先 |
|-----------|-------|
| `test_benchmark_analyzer.py` | `tests/unit/` |
| `test_metadata_generator.py` | `tests/unit/` |
| `test_collection_paths.py` | `tests/unit/` |

### Humble Object 適用（upload_core パターン）

| モジュール | 配置先 |
|-----------|-------|
| `test_video_uploader.py` | ロジック → `tests/unit/`、統合 → `tests/integration/` |
| `test_playlist_manager.py` | ロジック → `tests/unit/`、統合 → `tests/integration/` |
| `test_analytics_system.py` | ロジック → `tests/unit/`、統合 → `tests/integration/` |

### 状態ベース整理

| モジュール | 配置先 |
|-----------|-------|
| `test_channel_config.py` | `tests/unit/` |
| `test_youtube_service.py` | `tests/unit/` |

### 非同期テスト

| モジュール | 配置先 |
|-----------|-------|
| `test_generate_music_dj.py` | ロジック → `tests/unit/`、統合 → `tests/integration/` |

## マイルストーンと完了基準

### マイルストーン 1: パイロット（本設計のスコープ）

| ステップ | 完了基準 |
|---------|---------|
| time_utils 新テスト追加 | `tests/unit/test_time_utils.py` が全パス、旧テストと同等の回帰保護 |
| upload_policy 抽出 + テスト | `utils/upload_policy.py` + `tests/unit/test_upload_policy.py` が全パス |
| upload_core 統合テスト | `tests/integration/test_upload_core.py` が全パス |
| 旧テスト削除 | 旧 `tests/test_time_utils.py`, `tests/test_upload_core.py` を削除、全テスト通過 |
| パターンレビュー | パイロットで確立したパターンが残りモジュールに適用可能か評価 |

### マイルストーン 2: 展開（パイロット後に計画）

パイロットのフィードバックを反映してから計画する。展開順は ROI で優先付け:
1. mock 過多で壊れやすいテスト（video_uploader, playlist_manager, analytics_system）
2. 純粋関数テストの整理（benchmark_analyzer, metadata_generator, collection_paths）
3. 状態ベース整理（channel_config, youtube_service）
4. 非同期テスト（generate_music_dj）

## プロダクションコード変更の範囲

Humble Object パターン適用のためプロダクションコードの構造変更は不可避。
ただし変更は以下に限定する:

- **許可**: ロジックを新モジュール（`upload_policy.py` 等）に抽出。既存モジュールは抽出先に委譲するよう変更
- **許可**: 既存の公開 API（メソッドシグネチャ、戻り値）は維持。呼び出し元に影響しない内部リファクタリング
- **禁止**: 公開 API の変更、モジュール間の依存関係の再構成、新しい外部依存の追加

## スコープ外

- テストカバレッジの拡大（既存テストの質の改善が目的）
- CI/CD パイプラインの変更
- マイルストーン 2 の詳細計画（パイロット完了後に策定）
