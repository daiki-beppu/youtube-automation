# `.claude/CLAUDE.md` 配布化への移行ガイド

`youtube-channels-automation` v2 系 (#271) で `.claude/CLAUDE.md` が `yt-skills sync --asset claude-md` の配布対象になった。これに伴い、各チャンネルリポジトリ側で **共通骨格** と **個別メモ** を分離する必要がある。

本書は既存チャンネル（deepfocus365 / bobble / rjn / yt-studio / neta 等、現行 `.claude/CLAUDE.md` を手動コピーで運用してきたリポジトリ）向けの移行手順をチェックリスト形式でまとめる。

---

## 移行の全体像

```
[移行前]                              [移行後]
.claude/CLAUDE.md                     .claude/CLAUDE.md         ← upstream 配布の共通骨格 (sync 対象)
  (共通骨格 + 個別メモが      →      .claude/CLAUDE.local.md   ← 個別メモ (sync 対象外、手動管理)
   1 ファイルに混在)
```

**ゴール**: `yt-skills sync --asset claude-md --force` を安全に実行できる状態にする（共通骨格を最新版で上書きしても、各チャンネル固有のノウハウ・実験結果・運用メモが消えない）。

---

## 1. 分類観点（共通骨格 vs 個別メモ）

現行 `.claude/CLAUDE.md` を読み、各セクション・各箇条書きを以下の基準で **共通 / 個別** にラベル付けする。

### 共通骨格 (`.claude/CLAUDE.md`、配布対象) に残すもの

| 観点 | 例 |
|------|-----|
| **BGM チャンネル全般に当てはまる収益化原則** | CTR 最適化原則、誇張表現禁止、Complete Collection 原則 |
| **`yt-*` CLI / スキルの使い方早見表** | `/wf-status` `/analytics-analyze` `/comments-reply` の用途一覧 |
| **音楽エンジン切替ルール** | `lyria` / `suno` の選択基準と後工程フロー |
| **多言語ローカライゼーション原則** | `localizations.json` の運用 |
| **このリポジトリ全般の開発規約** | `load_config()` 経由の設定アクセス、ドメイン例外の使用 |
| **認証ファイルのコミット禁止** | `client_secrets.json` / `token.json` / `.env` |

### 個別メモ (`.claude/CLAUDE.local.md`、ローカル管理) へ切り出すもの

| 観点 | 例 |
|------|-----|
| **このチャンネル固有の target audience** | 「30-40 代男性 study 用途中心」など |
| **このチャンネルの訴求トーン・世界観** | 「夜の都市、雨」「北欧の朝」など |
| **特定シリーズの構成ノウハウ** | 「lofi-rain シリーズは A→B→A 展開で 60 分」 |
| **過去の実験結果・振り返り** | 「2025-Q3 にサムネ全面刷新で CTR +1.8%」 |
| **避けたい失敗パターン** | 「過去にやって滑った企画リスト」 |
| **外部サービス契約・API 鍵の場所メモ** | 「Suno アカウントは ○○、課金は ××」 |
| **このチャンネル固有の投稿スケジュール** | 「毎週木曜 21:00 JST」 |
| **このチャンネルの YouTube channel_id / handle** | `config/channel/meta.json` で管理しているがメモを残したい場合 |

### グレーゾーンの判断

| 例 | 判断 | 理由 |
|----|------|------|
| 「他社 BGM チャンネルで効いているサムネ構図」 | 共通骨格 | TTP 原則として汎用化できる |
| 「自チャンネルで効いているサムネ構図」 | 個別メモ | 結果はそのチャンネル固有 |
| 「ベンチマーク競合の追加リスト」 | **個別メモ** ではなく `config/channel/analytics.json::benchmark.channels` に書く | テンプレ／ローカルメモに散らさない |

---

## 2. 移行手順（チェックリスト）

### Step 1: 現行 `.claude/CLAUDE.md` のバックアップ

```bash
cp .claude/CLAUDE.md .claude/CLAUDE.md.pre-sync.bak
```

- [ ] バックアップ作成済み（あとで分類照合に使う）

### Step 2: 個別メモを `.claude/CLAUDE.local.md` に切り出し

現行 `.claude/CLAUDE.md` を読みながら、上記「個別メモ」基準に該当する箇条書き・節を抜粋して `.claude/CLAUDE.local.md` を新規作成する。

```markdown
# CLAUDE.local.md — {チャンネル名} 固有メモ

このファイルはこのチャンネルリポジトリ固有の戦術・運用メモ。`yt-skills sync` の対象外。
共通骨格は `.claude/CLAUDE.md` 側で upstream から配布される。

## このチャンネルの target audience
...

## 過去の実験結果
...
```

- [ ] target audience / 訴求トーンを移行
- [ ] シリーズ別ノウハウを移行
- [ ] 過去の実験結果・振り返りを移行
- [ ] 避けたい失敗パターンを移行
- [ ] 外部サービス契約メモを移行
- [ ] 投稿スケジュール等の運用ルールを移行

### Step 3: 共通骨格の最新版を取得

`yt-skills` を最新版に上げてから sync を実行:

```bash
uv add -U git+https://github.com/daiki-beppu/youtube-channels-automation.git
uv run yt-skills diff --asset claude-md     # 上書きされる差分を確認
uv run yt-skills sync --asset claude-md --force   # 既存を上書き
```

- [ ] `yt-skills` を最新版に更新済み
- [ ] `diff` で上書きされる内容を確認済み
- [ ] `sync --force` 実行で `.claude/CLAUDE.md` が共通骨格になった

### Step 4: 動作確認

- [ ] `.claude/CLAUDE.md` の内容が upstream `.claude/CLAUDE.template.md` と一致する（`yt-skills diff --asset claude-md` で「差分なし」表示）
- [ ] `.claude/CLAUDE.local.md` が **触られていない** こと（タイムスタンプ確認、内容確認）
- [ ] `.claude/CLAUDE.md.pre-sync.bak` と `.claude/CLAUDE.local.md` を突き合わせて、個別メモが抜け漏れなく移行されていること

### Step 5: コミット

`.claude/CLAUDE.local.md` は `.gitignore` に入れず、各チャンネルリポでバージョン管理する:

```bash
git add .claude/CLAUDE.md .claude/CLAUDE.local.md
rm .claude/CLAUDE.md.pre-sync.bak   # Step 1 で cp 作成した untracked なバックアップ
git commit -m "chore: split CLAUDE.md into upstream-distributed shell + local notes"
```

- [ ] `.claude/CLAUDE.md` と `.claude/CLAUDE.local.md` をコミット
- [ ] バックアップファイルを削除

---

## 3. 以後の運用

| シナリオ | 操作 |
|---|---|
| upstream の共通骨格が更新された | `uv run yt-skills sync --asset claude-md --force` で取り込み |
| 共通骨格の差分を見たい | `uv run yt-skills diff --asset claude-md` |
| BGM 系全般に効く新しい原則を追加したい | upstream `youtube-channels-automation/.claude/CLAUDE.template.md` に PR |
| このチャンネル固有のメモを追加したい | `.claude/CLAUDE.local.md` を直接編集（sync の影響を受けない） |

---

## 4. トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `yt-skills sync --asset claude-md` で `target が存在しません` | 初回展開時は `.claude/` ディレクトリのみあれば OK。`mkdir -p .claude` を実行してから sync |
| `--force` を付けても上書きされない | `--force` は `.claude/CLAUDE.md` のみを対象にする。`.claude/CLAUDE.local.md` は仕様上触らない（バグではない） |
| `--asset claude-md` が `choices` エラーになる | `yt-skills` のバージョンが古い。`uv add -U git+https://...` で更新 |
| sync 後に内容が壊れて見える | `yt-skills diff --asset claude-md` で同梱版との差分を確認。完全一致しない場合は upstream の README / リリースノートで仕様変更を確認 |

---

## 5. 既存 5 チャンネル向けチェックリスト（PR レビュー添付用）

PR description に貼って各チャンネル側でチェック:

```markdown
- [ ] deepfocus365: `.claude/CLAUDE.md` を分類 → `.claude/CLAUDE.local.md` 切り出し済み → sync --force 実行済み
- [ ] bobble:        同上
- [ ] rjn:           同上
- [ ] yt-studio:     同上
- [ ] neta:          同上
```

各チャンネルの実差分は本リポジトリからは見えないため、**チャンネル側リポで個別 issue 化** して進める（`#271` のスコープ外）。
