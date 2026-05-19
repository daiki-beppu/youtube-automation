# C-3: 後方互換 shim の現状 — 監査データ

調査日: 2026-05-18
担当: dig.part-c-deps-deprecation
対象リビジョン: HEAD

---

## 6.11 ルート shim 棚卸し

### 6.11.1 CLAUDE.md の宣言 vs 実態

`CLAUDE.md:38`（プロジェクト固有）の記述:

> - `utils/`, `agents/`, `auth/`, `scripts/` — submodule 利用者向け **後方互換 shim**（新規開発は `src/youtube_automation/` 側で行う）

実態（`find -maxdepth 1 -type d` + `ls`）:

| ディレクトリ | 存在 | 中身 | 性質 |
|---|---|---|---|
| `utils/` | **存在しない** | — | CLAUDE.md の記述が古い（残骸） |
| `agents/` | **存在しない** | — | CLAUDE.md の記述が古い（残骸） |
| `auth/` | 存在 | `SETUP.md`, `client_secrets_template.json` の 2 ファイルのみ | **shim ではなく、template + setup ドキュメント** |
| `scripts/` | 存在 | `gcp-bootstrap.sh`, `gcp-terraform-apply.sh` の 2 シェルスクリプトのみ | **Python shim ではなく、共通シェルスクリプトのみ** |

`CLAUDE.md:100`（同じファイル内）には:

> - ルート直下の `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

→ `CLAUDE.md` 内部で**矛盾**している。L.38 が古い記述、L.100 が現状。`utils/`, `agents/`, `auth/`, `scripts/` のうち実際の Python shim として残っているのは **0 個**。

### 6.11.2 ルート shim の実態詳細

#### `auth/`

```
auth/
├── SETUP.md                       # GCP / YouTube API セットアップガイド
└── client_secrets_template.json   # OAuth client_secrets.json のテンプレ
```

`SETUP.md:88` で「`<channel_dir>/automation/auth/client_secrets.json`（submodule 互換フォールバック）」と書かれているが、これは下流チャンネル側の path 検索の話で、本リポジトリの `auth/` ディレクトリ自体は shim ではなく、純粋にドキュメント + テンプレ配布用。

`src/youtube_automation/auth/oauth_handler.py:99-102` も：

```python
candidates = [
    channel_dir / "auth" / "client_secrets.json",
    channel_dir / "automation" / "auth" / "client_secrets.json",
]
```

→ 「submodule 互換」は **下流チャンネル側** の検索 path 互換であり、本リポジトリ側に shim ファイルは存在しない。

#### `scripts/`

```
scripts/
├── gcp-bootstrap.sh
└── gcp-terraform-apply.sh
```

`CLAUDE.md:105` で「複数の文脈から共有される **共通スクリプトのみ** を置く」と方針宣言。`auth/SETUP.md:23` で `automation/scripts/gcp-bootstrap.sh` として参照されている。下流チャンネルから submodule 経由で呼ばれる前提。shim ではなく、本物の共通スクリプト。

#### `utils/` / `agents/`

`find` で確認したが**ディレクトリ自体が存在しない**。`CLAUDE.md:38` の記述は obsolete。Python shim 廃止済みとした `CLAUDE.md:100` 方が正しい。

### 6.11.3 結論

「ルート直下の Python shim」は実態 **ゼロ件**。CLAUDE.md L.38 の記述だけが残骸として残っている。
**P2: ドキュメント修正案件**（コードへの影響なし）。

---

## 6.12 v1 → v2 設定移行残骸（`cli.config_migrate`）

### 6.12.1 配置と役割

`src/youtube_automation/cli/config_migrate.py:1-13`（モジュール docstring 抜粋）:

> "yt-config-migrate — 旧 config/channel_config.json を新 config/channel/*.json 構造に分割する。
> ...
> automation v2.0.0 に pin-bump した直後、旧 channel_config.json のままでも実行可能である必要があるため。"

`pyproject.toml:48`:

```toml
yt-config-migrate = "youtube_automation.cli.config_migrate:main"
```

→ entry point として登録継続。

`src/youtube_automation/utils/config/loader.py:100-106`:

```python
legacy_path = channel_dir_path / "config" / "channel_config.json"

if legacy_path.exists():
    raise ConfigError(
        f"旧 channel_config.json が残っています: {legacy_path}\n"
        "yt-config-migrate で新構造 (config/channel/*.json) へ変換してください"
    )
```

→ **新 loader は legacy 形式を読まずに ConfigError で fail-fast**。`yt-config-migrate` で移行する前提。

### 6.12.2 現在の役割（v5.5.0 時点）

`docs/migration/v2-config-split.md` が存在（`docs/migration/` の中身を `Bash ls` で確認済み）。v2 移行ガイドが残っている。

`config_migrate` 本体は読み取りロジックを independent に持つ（loader を使わない設計、`config_migrate.py:8-12` docstring 明記）。これは過去の判断としては適切。

`tests/test_config_migrate.py` などのテストカバレッジは未確認だが、`yt-config-migrate verify` が新 loader でロード検証可能。

### 6.12.3 廃止判定

- v2.0.0 への pin-bump 後の移行用 → 既に **v5.5.0**（pyproject.toml:8）に到達。3 メジャーバージョン経過
- 下流チャンネルが v1 → v2 移行を未完了で残しているケースは個別調査要だが、loader 側が hard fail するので「移行せずに使い続ける」運用は不可能

→ `yt-config-migrate` を撤去するタイミングを検討する余地あり（**P3: 中長期判断**）。撤去判断には CHANGELOG / 配布実績の追跡が必要だが、新規ユーザーには不要 CLI。

---

## 6.13 廃止された設定キー — workflow.json の `short` / `community`

### 6.13.1 v4.0.0 で撤去された経緯

`src/youtube_automation/utils/config/workflow.py:8-15`:

```python
@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    v4.0.0 で short 関連フィールド（`post_upload` / `short`）を撤去した。
    将来フィールドが増えたら本 dataclass に追加し、`_REQUIRED_KEYS_BY_SECTION` に
    必須キーを登録すること。
    """
```

→ **空の dataclass**。フィールド 0 個。

`src/youtube_automation/utils/config/loader.py:266-271`:

```python
def _build_workflow(merged: dict) -> Workflow:
    # v4.0.0 で short / community_post 関連セクションを撤去。
    # `workflow` / `post_upload` / `short` / `community` が downstream に残っていても
    # `_validate_required` は workflow.json に必須キーを登録していないため
    # 素通しする（後方互換）。
    return Workflow()
```

→ **無条件で空 dataclass を返す**。downstream の `workflow.json` 内の `workflow` / `post_upload` / `short` / `community` キーは読まれもせず捨てられる。

### 6.13.2 CHANGELOG での撤去記録

`CHANGELOG.md:482-491` 抜粋（v4.0.0 系のリリースノート）:

```
- **設定スキーマ**: `Workflow.post_upload` / `Workflow.short` フィールド、および `PostUpload` / `ShortSettings` dataclass
- **Python モジュール**: `youtube_automation.scripts.community_draft` / `youtube_automation.scripts.post_upload_actions`
- **スキル参照**: `.claude/skills/wf-next/references/community_draft.py` / `post_upload_actions.py`（symlink）
- **スキル記述**: `wf-next/SKILL.md` の community-draft ステップ、`wf-new/references/schema.md` の `community` フィールド定義、`ideate/SKILL.md` と `ideate/references/object-design-examples.md` の「コミュニティ投稿での展開 / 活用」セクション、`channel-setup/references/config-generation-rules.md` の `post_upload` オプション行
```

`CHANGELOG.md:500`:

> 3. `config/channel/workflow.json` の `post_upload` / `short` / `community` キーは**削除しなくても loader は素通しする**ため任意。整理したい場合は手動削除

→ 明示的に「素通し（silent ignore）」と運用上宣言。

### 6.13.3 影響範囲

- **`Workflow` dataclass は空**だが `ChannelConfig.workflow` フィールドは残っている（`src/youtube_automation/utils/config/config.py:27`）→ 構造保持のための placeholder
- 下流が `workflow.json` を持っていれば中身は無視されるが、loader はファイルそのものは glob で読む（`_load_and_merge` で重複キー検出はする）
- `tests/test_config_loader.py:134-139` で「v4.0.0 で post_upload / short セクションは撤去されたが、downstream の」（テストケースが残置確認のために存在）

### 6.13.4 廃止判定

「空 dataclass + 素通し loader」は典型的な **dead backward-compat shim**。

- `Workflow` 自体が空なら `ChannelConfig.workflow` フィールド／`_build_workflow` の関数を撤去できる（代わりに `ChannelConfig` から workflow フィールド削除）
- ただし下流が `from youtube_automation.utils.config import ChannelConfig` で型 hint 経由で参照している可能性があるので、撤去はメジャーバージョン bump で

**P2: dead shim**。動作影響なし、メジャーバージョン更新時に整理候補。

---

## 6.14 skill 同梱バージョンと配布側の固定リスク

### 6.14.1 配布メカニズム

`pyproject.toml:82-88`:

```toml
[tool.hatch.build.targets.wheel.force-include]
".claude/skills" = "youtube_automation/_skills"
".claude/CLAUDE.template.md" = "youtube_automation/_claude_md/CLAUDE.template.md"
```

→ wheel ビルド時に **`youtube-channels-automation` のバージョンと skills のバージョンが完全固定**になる。`5.5.0` の wheel をインストールすれば必ず `5.5.0` 時点の skills が配布される。

`src/youtube_automation/cli/skills_sync.py:73-78` で `importlib.resources` 経由で wheel 内の `_skills/` を参照し、`yt-skills sync` 実行時に下流の `.claude/skills/` に展開。

### 6.14.2 skills 自体のバージョン管理

各 skill ディレクトリには独立した version 表記が **無い**:

```
.claude/skills/<name>/
├── SKILL.md         # frontmatter に version: なし
├── config.default.yaml
└── references/
```

`grep "^version:" .claude/skills/**/SKILL.md` で 0 件。

→ skill 単体のバージョンは追跡不可。`pyproject.toml::version` のみがソース。

### 6.14.3 下流での固定リスク

**問題シナリオ**:

1. 下流チャンネル A が `uv add 'git+...youtube-automation@v5.3.0'` で pin
2. 当時の `5.3.0` 時点の `.claude/skills/` が配布される
3. `5.4.0` で `analyze` → `analytics-analyze` のような skill rename があった（`CHANGELOG.md:154` で確認可能: 「スキル名 rename 8 件（`analyze` → `analytics-analyze` など、破壊的）」）
4. チャンネル A 側で `claude code` / SKILL invocation を使う際に、古い skill 名が残ったまま動く
5. 一方で `pyproject.toml` の依存（`google-genai` 等）は version 上限なしで最新を引くため、**skill ファイルだけ 5.3.0、ランタイムは最新** という乖離が発生

→ **P1: skill とランタイムの version lock が一致しない可能性**。`yt-skills sync --force` で更新する運用責任は下流チャンネル側にあり、自動アップデートしない。

### 6.14.4 wheel 同梱の不安定要素

`yt-skills sync` がデフォルトで `force=False`（`skills_sync.py:114-115`）。既存 skill が target にあれば「skipped」になり、新版が適用されない。`--force` フラグを明示しないと古い skill が残る。

下流の運用ドキュメント（`README.md` / `ONBOARDING.md`）に「`yt-skills sync --force` を upgrade 時に実行」と明記されているかは未検証だが、CLI 出力にメッセージ:

```
(skipped を上書きするには --force を指定してください)
```

`skills_sync.py:194,228` に表示される。気づける設計にはなっている。

### 6.14.5 結論

- skill version 単独追跡なし
- パッケージ version と完全同期
- 下流アップデート手順が `--force` 必須

**P2: 下流アップデート時の手順が明示化されていないと skill だけ古いまま乖離する**。

---

## まとめ（後方互換 shim severity）

| ID | 内容 | severity |
|---|---|---|
| 6.11 | `CLAUDE.md:38` が古く、`utils/`/`agents/` shim は実在しない（同ファイル L.100 と矛盾） | P2（docs） |
| 6.11 | `auth/`, `scripts/` ルートディレクトリは shim ではなく template + 共通スクリプト | — |
| 6.12 | `yt-config-migrate` v1→v2 移行 CLI は v5.5.0 でも残存。撤去判断が必要 | P3 |
| 6.13 | `Workflow` dataclass 空、`_build_workflow` も placeholder。dead backward-compat shim | P2 |
| 6.14 | skill バージョン追跡なし、wheel 同期は `--force` 明示要 | **P1**（下流ずれリスク） |

調査不可項目: 下流チャンネルでの実利用バージョン（git remote 接続不可、grep 範囲外）。
