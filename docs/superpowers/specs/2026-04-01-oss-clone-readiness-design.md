# OSS クローン & channel-new 対応

## Context

automation リポジトリを OSS として公開し、第三者がクローンして `channel-new` スキル経由で新チャンネルをセットアップできるようにする。現状の課題:
1. 1Password 依存のセットアップスクリプト
2. スキル内の認証手順が自分専用
3. yt チャンネルリポ（goa, rjn）にスキルが散在しており、automation submodule にまとまっていない

## 変更一覧

### Part A: セットアップの汎用化

#### A-1. setup_env.sh の汎用化

**ファイル**: `setup_env.sh`

現状: `op inject` (1Password CLI) に固定依存。

変更後:
- 1Password CLI (`op`) が利用可能なら `op inject` を使用
- なければ `.env.example` → `.env` にコピーしてユーザーに手動編集を案内
- `.env.tpl` は 1Password ユーザー用にそのまま残す

#### A-2. auth/SETUP.md のパス修正

**ファイル**: `auth/SETUP.md`

- Step 4 のパス: `youtube-automation/auth/` → `auth/` (相対パス)
- `.gitignore` 例: `youtube-automation/auth/` → `auth/` (相対パス)
- Step 5 のコマンドパス修正

### Part B: rjn ベースで全スキルを automation に移行

rjn リポの全スキルを automation の `.claude/skills/` に移行する。
ハードコードされたチャンネル固有値（CLM, RJN 等）を `channel_config.json` 参照に置換する。

#### 移行対象スキル（rjn → automation）

automation に既にある 4 スキル（channel-new, channel-research, channel-direction, channel-setup）は**スキップ**。

**value-only 差分（汎用化が容易）: 14 スキル**

| スキル | 概要 | 汎用化作業 |
|--------|------|-----------|
| alignment-check | ムード×サムネ×タイトル整合性監査 | "CLM" ラベル削除 |
| analyze | Analytics 詳細分析 | チャンネル名ハードコード削除 |
| benchmark | 競合ベンチマーク更新 | "CLM" → config 参照 |
| collect | Analytics データ収集 | ほぼそのまま |
| description | YouTube 概要欄生成 | config 参照に統一 |
| loop-video | ループ動画背景生成 | そのまま（既に汎用） |
| lyria | Lyria API 音楽生成 | 例示値を config 参照に |
| masterup | Suno 楽曲 DL + マスター生成 | そのまま（既に汎用） |
| persona | 視聴者ペルソナ定義 | "CLM の場合" 注釈削除 |
| short | ショート動画制作 | "CLM 等の" 注釈削除 |
| short-thumbnail | ショート用サムネイル | そのまま（既に汎用） |
| thumbnail | サムネイル生成 | config-driven（既に対応済み） |
| thumbnail-compare | サムネイル比較検証 | そのまま（既に汎用） |
| upload | YouTube アップロード | config 参照に統一 |
| viewer-voice | 視聴者コメント分析 | そのまま（既に汎用） |
| viewing-scene | 視聴シーン検証 | "CLM の場合" 注釈削除 |
| videoup | 動画生成 | そのまま（既に汎用） |

**構造的差分あり: 2 スキル**

| スキル | 概要 | 汎用化作業 |
|--------|------|-----------|
| ideate | 企画立案（ペルソナベース） | ペルソナ/企画フレームワークを config で制御 |
| wf-new | ワークフロー開始 | generation_mode 分岐を config で制御 |

**ワークフロー系: 3 スキル**

| スキル | 概要 | 汎用化作業 |
|--------|------|-----------|
| wf-next | ワークフロー次ステップ | そのまま（既に汎用） |
| wf-status | ワークフロー進捗確認 | そのまま（既に汎用） |
| wf-references | ワークフロースキーマ | → wf-new/references/schema.md に移動 |

**移行しないもの:**

| 対象 | 理由 |
|------|------|
| channel-references/ | automation の channel-setup/references/ に既に移行済み |
| report | template 版で十分、rjn 版と差異なし→要確認 |
| status | template 版で十分→要確認 |

#### 移行手順（スキルごと）

1. rjn から SKILL.md + コンパニオンファイルをコピー
2. ハードコードされたチャンネル固有値を汎用化:
   - `CLM` `RJN` `AEEJ` `GoA` → 削除または「`channel_config.json` の値を参照」に置換
   - 具体的なジャンル例（jazz, celtic 等）→ `{genre.primary}` `{genre.style}` プレースホルダーまたは「config の値を使用」
3. コンパニオンファイルは `references/` サブディレクトリに配置（前回の整理パターンに従う）:
   - `ideate/collection-lifecycle.md` → `ideate/references/collection-lifecycle.md`
   - `upload/posting-checklist.md` → `upload/references/posting-checklist.md`
   - `wf-references/schema.md` → `wf-new/references/schema.md`

#### channel-new スキルの認証手順更新

**ファイル**: `.claude/skills/channel-new/SKILL.md`

Step 3 を更新:
- 「client_secrets.json は submodule に含まれる」→ 削除
- 「`auth/SETUP.md` に従って OAuth 認証情報を作成し、`automation/auth/client_secrets.json` に配置」に変更
- 既存チャンネルからのトークンコピー手順はそのまま残す

## 対象外

- `client_secrets.json` は既に `.gitignore` で除外済み。変更不要
- `.env.tpl` はそのまま残す（1Password ユーザー向け）
- goa/rjn リポからのスキル削除（別タスク）
- template リポの更新（別タスク）

## 検証

1. `setup_env.sh` を 1Password なし環境で実行 → `.env` がコピーされること
2. 移行した全スキルにチャンネル固有のハードコード値が残っていないこと（grep で確認）
3. `channel-new` SKILL.md のパス参照が正しいこと
4. `auth/SETUP.md` のパスが正しいこと
5. コンパニオンファイルが `references/` に正しく配置されていること
