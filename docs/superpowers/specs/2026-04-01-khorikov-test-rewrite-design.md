# テスト書き直し設計: Khorikov「単体テストの考え方/使い方」準拠

## 概要

現在の 12 モジュール・270+ テストを Vladimir Khorikov の原則に基づいて書き直す。
パイロット 2 モジュールでパターンを確立し、残りに展開する。

## 適用する原則

### テスト分類の優先順位

| 優先順位 | スタイル | 適用先 |
|---------|---------|-------|
| 1st | 出力ベース | 純粋関数（入力→出力の検証） |
| 2nd | 状態ベース | 状態を持つオブジェクト（操作後の状態検証） |
| 3rd | コミュニケーションベース | 外部システム境界のみ（管理下にない依存） |

### 核心ルール

1. **mock は管理下にない依存（YouTube API, ffmpeg 等の外部プロセス）にのみ使う** — 自プロジェクト内クラス間は mock しない
2. **観察可能な振る舞いを検証する** — メソッド呼び出し順序・回数・引数の詳細は検証しない
3. **1 テスト = 1 振る舞い** — AAA（Arrange-Act-Assert）厳守、Assert は 1 つの論理的概念
4. **テスト名は振る舞いを記述する** — `test_<振る舞いの説明>` 形式
5. **プライベートメソッドを直接テストしない** — 公開 API 経由で間接的に検証
6. **Humble Object パターン** — ビジネスロジックをインフラから分離し、ロジックを出力ベースでテスト

### ユニットテスト vs 統合テスト

- **ユニットテスト**: 高速、プロセス外依存なし、単一の振る舞いを検証
- **統合テスト**: プロセス外依存との統合を検証、ハッピーパス + 重要異常系のみ

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
    """format_duration_mss: 秒数を "M:SS" 形式に変換する"""

    @pytest.mark.parametrize("seconds, expected", [
        (0, "0:00"),
        (59, "0:59"),
        (90, "1:30"),
        (3600, "60:00"),
    ])
    def test_converts_seconds_to_m_ss_format(self, seconds, expected):
        assert format_duration_mss(seconds) == expected

    def test_rounds_float_seconds_down(self):
        assert format_duration_mss(90.9) == "1:30"
```

## パイロット 2: test_upload_core.py（Humble Object パターン）

### 配置

- `tests/unit/test_upload_logic.py` — 抽出したロジック関数のテスト
- `tests/integration/test_upload_core.py` — YouTubeUploadCore の統合テスト

### プロダクションコード変更

`utils/upload_core.py` から以下の純粋関数を抽出（同ファイル内のモジュールレベル関数）:

```python
def should_compress_thumbnail(file_size: int, max_bytes: int = 2_097_152) -> bool:
    """ファイルサイズが上限を超えているか判定"""
    return file_size > max_bytes

def get_compression_qualities() -> list[int]:
    """圧縮品質の試行順序を返す"""
    return [2, 5]

def is_retryable_http_status(status_code: int) -> bool:
    """HTTP ステータスがリトライ可能か判定"""
    return status_code in (500, 502, 503, 504)

def calculate_retry_delay(retry_count: int) -> float:
    """リトライ回数に応じた待機秒数を返す（指数バックオフ）"""
    return float(2 ** retry_count)

MAX_RETRY_ATTEMPTS = 5
```

### ユニットテスト（出力ベース、mock なし）

```python
# tests/unit/test_upload_logic.py

class TestShouldCompressThumbnail:
    def test_returns_false_when_under_limit(self):
        assert should_compress_thumbnail(1000) is False

    def test_returns_true_when_over_limit(self):
        assert should_compress_thumbnail(3_000_000) is True

    def test_returns_false_at_exact_limit(self):
        assert should_compress_thumbnail(2_097_152) is False

class TestIsRetryableHttpStatus:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_errors_are_retryable(self, status):
        assert is_retryable_http_status(status) is True

    @pytest.mark.parametrize("status", [400, 403, 404, 429])
    def test_client_errors_are_not_retryable(self, status):
        assert is_retryable_http_status(status) is False

class TestCalculateRetryDelay:
    @pytest.mark.parametrize("retry, expected", [
        (0, 1.0),
        (1, 2.0),
        (3, 8.0),
    ])
    def test_exponential_backoff(self, retry, expected):
        assert calculate_retry_delay(retry) == expected
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
- `assert_called_once()` 等の呼び出し検証は使わない — 戻り値・例外・状態で検証
- ハッピーパス + 重要異常系（ファイル不在、API エラー）に絞る

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

## スコープ外

- プロダクションコードの大規模リファクタリング（Humble Object のためのロジック抽出は最小限に行う）
- テストカバレッジの拡大（既存テストの質の改善が目的）
- CI/CD パイプラインの変更
