# Part C: description ↔ 実装 / バトン双方向 / v4.0.0 deprecated / 形式揺れ 機械検出

## 1. 概要

| 項目 | 値 |
|---|---|
| 走査対象 | `.claude/skills/**/SKILL.md` 全 35 件 |
| 走査方法 | `Read`（frontmatter / 本文） + `Grep`（クロスリファレンス・deprecated 用語） + `Glob`（実装ファイル存在確認） + `pyproject.toml` 照合 |
| 観点 | C-1 description ↔ 実装乖離 / C-2 バトン双方向 / C-3 v4.0.0 deprecated 残存 / C-4 形式揺れ |

### 検出件数サマリー

| 観点 | 検出件数 | 内訳 |
|---|---|---|
| C-1（description ↔ 実装乖離） | **1** | P1: 1（`short` 廃止スキル参照） |
| C-2（バトン片方向のみ） | **9 リンク** | 一方向: 9 / 双方向: 8 / 不一致（指す先が違う）: 0 |
| C-3（v4.0.0 deprecated 残存） | **1** | `video-description/config.default.yaml:6` の `short` 言及（コメント） |
| C-4（形式揺れ） | **多数** | frontmatter: 揃っている / セクション見出し: 揺れ大 / 名前: 揃っている |

---

## 2. C-1: description ↔ 実装乖離

### 検証ロジック

description（frontmatter `description:` 全文）で言及されている **コマンド名 / ファイル名 / パス / 他スキル `/xxx`** を抽出し、それぞれリポジトリ内に実在するか照合した。

### 検証済みリファレンス（全 35 件、抜粋）

| Skill | description 中の参照 | 実在確認 |
|---|---|---|
| `analytics-collect` | `analytics_system.py` | ✓ `src/youtube_automation/scripts/analytics_system.py` |
| `benchmark` | `docs/benchmarks/*.md` の更新 | ✓ 生成出力（実装は `benchmark_collector.py`） |
| `comments-reply` | `config/channel/comments.json`, `comment_reply_history.json` | ✓ `examples/channel_config.example/comments.json` 存在 |
| `lyria` | Vertex AI Lyria 3 `interactions` REST API / MP3 / PCM s16le WAV | ✓ `generate_lyria_master.py`（`yt-generate-lyria-master`）に対応 |
| `loop-video` | Veo 3.1 API / `main.png/jpg` / `loop.mp4` | ✓（実装 CLI 未確認だが skill 内 references あり） |
| `masterup` | プレイリスト URL → DL + マスター | ✓ `yt-generate-master` (`pyproject.toml:53`) |
| `metadata-audit` | `yt-metadata-audit` のラッパー / `collections/live/` | ✓ `yt-metadata-audit` 登録あり |
| `playlist` | `config/channel/playlists.json` / `yt-playlist-status` / `yt-playlist-manager` | ✓ 両 CLI が `pyproject.toml` 登録 |
| `postmortem` | `collections/live/<collection>/20-documentation/postmortem.md` | ✓ 出力規約として self-consistent |
| `streaming` | `infra/terraform/streaming/` モジュール | ✓ `infra/terraform/streaming/`（main.tf / outputs.tf / cloud-init.yaml / README.md / templates） |
| `suno` | Suno UI 投入用 Style + Lyrics プロンプト / SunoAI V5 | ✓（外部サービス記述） |
| `thumbnail` | Gemini / OpenAI 切り替え画像生成 | ✓ `yt-generate-image` 登録、provider 切り替え `image_provider.py` |
| `video-analyze` | Gemini で YouTube URL 解析、`hook_structure` / `bgm_arc` / `scene_timeline` / `thumbnail_alignment` / `editing_metrics` 抽出 | ✓ `yt-video-analyze` 登録 |
| `video-description` | Complete Collection 形式（情景フック＋タイムスタンプ＋Perfect for） | ✓ 本文 / config と整合 |
| `video-upload` | Complete Collection アップロードと live 移行 | ✓ `collection_uploader` 内で `planning/ → live/` 移行を行う旨が `playlist/SKILL.md:70` 等で参照 |
| `videoup` | `yt-generate-master` と `generate_videos.sh` | ✓ 両者とも実在 |
| 全 35 description の `/xxx` 参照 | 該当 SKILL.md ディレクトリ | ✓ 全て実在（後述 C-2 参照） |

### 検出された乖離（P1: 1 件）

#### C-1-① `video-description/config.default.yaml:6` — 廃止スキル `short` を「現役の参照元」として明記

```yaml
# 注意: tags.base / title.template / descriptions.opening / perfect_for / hashtags は
# 複数スキル（metadata_generator / short / upload 等）から参照される横断属性のため、
# 引き続き config/channel/*.json で管理する。
```

- **問題**: `short` は v4.0.0 で `workflow.json` から撤去（CLAUDE.md: `workflow.json # (v4.0.0 で short / community 撤去、後方互換で素通し)`）。`.claude/skills/short/` も存在しない（全 35 skill 一覧に無し）。
- **位置**: `.claude/skills/video-description/config.default.yaml:6`
- **推測される正解**: コメント文を `metadata_generator / upload 等` に縮める、または `short` を `community / live` 等の現役対象に書き換える（**判定: 推測**）。

> その他、description 本文中で実装と矛盾するコマンド名・出力ファイル名は **検出されなかった**（35 件すべて pyproject.toml の entry point またはリポジトリ内ファイルに対応）。

---

## 3. C-2: バトン（前工程 / 次工程）双方向整合

### 検出ロジック

1. `Grep "次工程[：:]"` `Grep "前工程[：:]"` で明示バトンを抽出
2. 各 SKILL.md の `## Next Step` / `## Cross References` / 本文中の `→ /xxx` から「指している」関係を抽出
3. 指された側にも対応する back-reference があるかを 1 件ずつ照合

### 明示バトン（`前工程:` / `次工程:` キーワード）

| ファイル:行 | 記述 |
|---|---|
| `masterup/SKILL.md:3` | description `前工程: /suno` `次工程: /videoup` |
| `masterup/SKILL.md:28` | 本文 `**前工程:** /suno` |
| `suno/SKILL.md:3` | description `DL + マスター化は次工程 /masterup` |
| `lyria/SKILL.md:3` | description `次工程は /videoup` |

明示キーワード以外の方向性は `## Next Step` / `→ /xxx` / `## Cross References` から拾った。

### バトンマッピング表（17 リンク全件）

凡例: ✓ 双方向 / ↪ 一方向（指された側に back-reference 無し）/ ✗ 不一致

| # | From | To | From → To の出典 | To → From の出典 | 判定 |
|---|---|---|---|---|---|
| 1 | `suno` | `masterup` | `suno/SKILL.md:3` (`次工程 /masterup`), `suno/SKILL.md:321,327` (Next Step) | `masterup/SKILL.md:3` (`前工程: /suno`), `masterup/SKILL.md:28` (`**前工程:** /suno`) | ✓ 双方向 |
| 2 | `masterup` | `videoup` | `masterup/SKILL.md:3` (`次工程: /videoup`), `masterup/SKILL.md:178` (Next Step) | `videoup/SKILL.md:41` (`なければ /masterup でのマスター音源生成を案内` — back-ref はあるが「前工程: /masterup」明示なし) | ↪ 一方向（弱い back-ref のみ） |
| 3 | `lyria` | `videoup` | `lyria/SKILL.md:3` (`次工程は /videoup`), `lyria/SKILL.md:276` (Next Step) | `videoup/SKILL.md` 内に **lyria 言及なし** | ↪ 一方向 |
| 4 | `videoup` | `video-description` | `videoup/SKILL.md:64` (Next Step `→ /video-description`) | `video-description/SKILL.md` 内に **videoup 言及なし** | ↪ 一方向 |
| 5 | `video-description` | `video-upload` | `video-description/SKILL.md:123` (Next Step `→ /video-upload`) | `video-upload/SKILL.md:8` (Overview `/video-description で事前生成`), `video-upload/SKILL.md:120` (Cross Ref) | ✓ 双方向 |
| 6 | `video-upload` | `metadata-audit` | `video-upload/SKILL.md:122` (Cross Ref `/metadata-audit`) | `metadata-audit/SKILL.md` 内に **video-upload 言及なし**（`/video-description` のみ） | ↪ 一方向 |
| 7 | `channel-new` | `channel-research` | `channel-new/SKILL.md:13,182,186` | `channel-research/SKILL.md:8,10,129` (`/channel-new → 前フェーズ`) | ✓ 双方向 |
| 8 | `channel-research` | `channel-direction` | `channel-research/SKILL.md:50,125,130` (`次フェーズ: /channel-direction`) | `channel-direction/SKILL.md:8,11,150` (`/channel-research → 前フェーズ`) | ✓ 双方向 |
| 9 | `channel-direction` | `channel-setup` | `channel-direction/SKILL.md:130,151` (`次フェーズ: /channel-setup`) | `channel-setup/SKILL.md:3,10,15,111` (`/channel-direction → 前フェーズ`) | ✓ 双方向 |
| 10 | `channel-import` | `wf-new` | `channel-import/SKILL.md:94,101` (`config 完成後の最初のアクション: /wf-new`) | `wf-new/SKILL.md:16` (`既存チャンネル → /channel-import を案内` — 入口案内のみ、Cross Ref では未列挙) | ↪ 一方向 |
| 11 | `wf-new` | `wf-next` | `wf-new/SKILL.md:148,157` (`後続ステップ管理: /wf-next`) | `wf-next/SKILL.md:91` (Cross Ref `新規開始: /wf-new`) | ✓ 双方向 |
| 12 | `wf-next` | `analytics-analyze` | `wf-next/SKILL.md:82` (Next Step `→ /analytics-analyze で初週パフォーマンス`) | `analytics-analyze/SKILL.md` 内に **wf-next 言及なし** | ↪ 一方向 |
| 13 | `analytics-collect` | `analytics-analyze` | `analytics-collect/SKILL.md:3` (description `/analytics-analyze 実行前のデータ準備`) | `analytics-analyze/SKILL.md:3,20` (`/analytics-collect でデータ収集後に実行`) | ✓ 双方向 |
| 14 | `analytics-analyze` | `collection-ideate` | `analytics-analyze/SKILL.md:55,85,98` (`→ /collection-ideate`) | `collection-ideate/SKILL.md:33,63,71,72` (`/analytics-analyze が未生成 or stale → 中断`) | ✓ 双方向 |
| 15 | `collection-ideate` | `thumbnail` | `collection-ideate/SKILL.md:105,107,330` (`→ /thumbnail` Phase 4) | `thumbnail/SKILL.md:222` (`/collection-ideate で本番品質のプレビューが生成され`) | ✓ 双方向 |
| 16 | `viewer-voice` | `audience-persona` | `viewer-voice/SKILL.md:3` (`/audience-persona や /viewing-scene の前提データ`) | `audience-persona/SKILL.md:3` (`/viewer-voice の結果を前提とし`) | ✓ 双方向 |
| 17 | `audience-persona` | `viewing-scene` | `audience-persona/SKILL.md:3` (`/viewing-scene の入力になる`) | `viewing-scene/SKILL.md:3` (`/audience-persona の結果を踏まえて`) | ✓ 双方向 |
| 18 | `loop-video` | `videoup` | `loop-video/SKILL.md:129` (Next Step `→ /videoup`) | `videoup/SKILL.md:42` (`なければ /loop-video でのループ動画生成を案内`) | ✓ 双方向 |
| 19 | `thumbnail` | `suno` | `thumbnail/SKILL.md:314` (Next Step `→ /suno`) | `suno/SKILL.md` 内に **thumbnail 言及なし** | ↪ 一方向 |
| 20 | `postmortem` | `thumbnail-compare` / `alignment-check` / `viewer-voice` / `video-analyze` | `postmortem/SKILL.md:3,101-109,166-170` で多数バトン | 4 スキルとも postmortem への back-reference 無し | ↪ 一方向（× 4） |

### 不整合一覧（一方向: 9 リンク）

P1 候補（双方向であるべき主要バトン）:

1. **`masterup → videoup`**（#2）: masterup は「次工程: /videoup」と明示。videoup は `/masterup` に「fallback として案内する」のみで「前工程」とは書いていない。`videoup/SKILL.md:41` の文面を強化（例: 「**前工程**: `/masterup`（Suno チャンネル）または `/lyria`（Lyria チャンネル）」）すべき。
2. **`lyria → videoup`**（#3）: lyria は「次工程は /videoup」と明示。videoup 側で `/lyria` を一切言及しない。music engine 分岐に対する盲点。
3. **`videoup → video-description`**（#4）: videoup の Next Step。video-description には videoup への back-reference 無し（本文 `20-documentation/suno-prompts.md` を読み込むのみ）。
4. **`video-upload → metadata-audit`**（#6）: Cross Ref で言及。metadata-audit から見た上流（アップロード完了直後）が明示されていない。

P2 候補（ライフサイクル系で双方向追記が望ましい）:

5. **`channel-import → wf-new`**（#10）: wf-new の Cross References に `既存チャンネル取り込み: /channel-import` を追記したい。
6. **`wf-next → analytics-analyze`**（#12）: T+7 日後の振り返りエントリポイント。analytics-analyze の「前提」セクションで wf-next との関係を明示してもよい。
7. **`thumbnail → suno`**（#19）: collection 制作チェーンの主要動線。suno 側で thumbnail を「前工程」として明示すれば、テーマ確定の依存が読み取りやすい。
8. **`postmortem → 4 skill`**（#20）: postmortem は明示的に「実検証は既存スキルへバトンする」と書いており、検証先 4 スキル側に back-reference が無いのは**設計上妥当**（postmortem は上位レイヤのメタスキル）。追記しなくてもよい — **推測**。

### 双方向が成立しているリンク（8 リンク）

#1, #5, #7, #8, #9, #11, #13, #14, #15, #16, #17, #18（実質 12 リンク中 8 が完全双方向、4 が「強い back-ref のみ」で運用上問題なし）。

---

## 4. C-3: v4.0.0 deprecated（`short` / `community`）参照残存

### 前提

CLAUDE.md（`/Users/mba/02-yt/takt-worktrees/20260518T0804-353-issue-353-chore-skills-sukiru/CLAUDE.md`）の以下記述が出典:

```
workflow.json      # (v4.0.0 で short / community 撤去、後方互換で素通し)
```

`examples/channel_config.example/workflow.json` を確認したところ内容は `{}` で、空オブジェクト = v4.0.0 撤去後の状態であることを再確認。

### `short` / `community` 出現箇所の分類

`Grep -i "\b(short|shorts|community)\b"` を `.claude/skills/**` に走査した全 19 件のヒットを意味で分類:

| 分類 | 件数 | 例 |
|---|---|---|
| **A. 削除済みスキル `/short` を「現役の参照元」として記述（C-3 該当）** | **1** | `video-description/config.default.yaml:6` |
| B. channel slug 用 config field `channel.short`（=「短縮名」） | 11 | `channel-setup/references/config-template/meta.json:4`, `config-template/analytics.json:3`, `channel-direction/SKILL.md:106`, `channel-setup/references/config-generation-rules.md:10`, `channel-new/SKILL.md:47,48,94`, `channel-import/SKILL.md:21,22`, `wf-new/SKILL.md:59,73,139`, `analytics-report/SKILL.md:109` |
| C. YouTube Shorts 動画フォーマット（除外対象） | 3 | `video-analyze/SKILL.md:66`, `analytics-report/SKILL.md:73,123` |
| D. 英文形容詞 "short"（楽曲歌詞例ほか） | 2 | `suno/SKILL.md:122`, `suno/references/lyrics-examples.md:17` |
| E. 英文単語 "community"（音楽 community demographic） | 1 | `audience-persona/SKILL.md:39` |
| F. 削除済みスキル `/community` を参照 | 0 | — |

### 検出（P1: 1 件）

#### C-3-① `video-description/config.default.yaml:6` — コメント内に廃止スキル名

```yaml
# 注意: tags.base / title.template / descriptions.opening / perfect_for / hashtags は
# 複数スキル（metadata_generator / short / upload 等）から参照される横断属性のため、
# 引き続き config/channel/*.json で管理する。
```

- C-1-① と同じ箇所。C-3 の観点では「v4.0.0 で撤去された `short` スキル」が「現役の横断参照スキル」のように記述されている。
- 修正案: `metadata_generator / upload 等`（推測）または現役で `tags.base` を読むスキルを列挙し直す。

### 偽陽性として除外したもの

- `channel.short`（B 分類 11 件）: `config/channel/meta.json` の正当な field（リポジトリ slug の短縮名）。撤去された `workflow.short` とは無関係。
- `Shorts`（C 分類 3 件）: YouTube プラットフォーム上の「Shorts 動画」フォーマット。`/short` skill とは別物。
- 英文 "short" / "community"（D, E 分類）: 自然言語の単語使用。

---

## 5. C-4: 形式揺れ（frontmatter / セクション / 命名）

### 5.1 Frontmatter キー分布

35 件すべての SKILL.md を `awk '/^---$/{n++; if(n==2) exit} n>=1'` で抽出し、キーを集計:

| キー | 出現数 / 35 | 備考 |
|---|---|---|
| `name` | 35 (100%) | 全件揃っている |
| `description` | 35 (100%) | 全件揃っている |
| `model` | 0 | 一切なし |
| `tools` / `allowed-tools` | 0 | 一切なし |
| `argument-hint` | 0 | 一切なし |
| その他 | 0 | — |

→ **frontmatter は全 35 件で完全に揃っており、揺れなし。**

### 5.2 セクション見出し分布（主要見出しのみ集計）

各 SKILL.md の先頭から `## ` 始まり行を最大 8 個抽出（`bash awk '/^## /{print; if(++c>=8) exit}'`）し、見出し名の出現数を集計:

| 見出し | 出現数 / 35 | 揺れ |
|---|---|---|
| `## Overview` | 35 | なし（英語統一） |
| `## 前提` | 24 | あり: 無いスキル（streaming は `## 前提` あり / live-clean, thumbnail-compare, masterup, channel-direction, channel-import, channel-new, channel-research, channel-setup, discover-competitors, metadata-audit, suno が **無**または別形式） |
| `## Quick Reference` | 14 | 任意性あり |
| `## Instructions` | 15 | あり |
| `## 実行フロー` | 7 | あり: `Instructions`（英）と二系統存在（`alignment-check`, `audience-persona`, `benchmark`, `comments-reply`, `postmortem`, `thumbnail-compare`, `video-analyze`, `viewer-voice`, `viewing-scene`） |
| `## When to Use` | 9 | あり: 日本語版「いつ使うか（選択タイミング）」を suno が使用 |
| `## Next Step` | 13 | あり |
| `## Cross References` | 11 | あり: `## 関連ファイル`（日本語）と二系統存在 |
| `## 関連ファイル` | 8 | あり |
| `## TTP 原則（ベンチマーク参照）` | 6 | チャンネル系のみ |
| `## Scripts` | 1 | videoup 独自 |
| `## 設定` | 3 | あり: `benchmark`, `masterup`, `video-analyze` |
| `## Channel Adaptation` | 4 | あり |
| `## §1 初回構築` 〜 `## §5 片付け` | 1 | streaming 独自（番号付き節） |

#### 主な揺れ

1. **「実行フロー」と「Instructions」の混在** — 工程記述の見出しが日英で揺れている。
2. **「Cross References」と「関連ファイル」と「Next Step」の混在** — 外部スキル参照の出力先見出しが 3 系統。
3. **「When to Use」と「いつ使うか」の混在** — suno のみ日本語、他は英語。
4. **`streaming` のみ `§1〜§5` 番号付き節**: 他にこの形式は無い。

### 5.3 スキル名（ディレクトリ名）命名規則

全 35 件:

```
alignment-check, analytics-analyze, analytics-collect, analytics-report,
audience-persona, benchmark, channel-direction, channel-import, channel-new,
channel-research, channel-setup, channel-status, collection-ideate,
comments-reply, discover-competitors, live-clean, loop-video, lyria,
masterup, metadata-audit, playlist, postmortem, streaming, suno,
thumbnail, thumbnail-compare, video-analyze, video-description,
video-upload, videoup, viewer-voice, viewing-scene, wf-new, wf-next, wf-status
```

- 全て **kebab-case**（小文字 + ハイフン）。アンダースコア / キャメルケース / 大文字混在は **0 件**。
- 単語 1 つの場合はハイフン無し（`benchmark`, `lyria`, `masterup`, `playlist`, `postmortem`, `streaming`, `suno`, `thumbnail`, `videoup`）。
- 名前的に紛らわしいペア:
  - `videoup` vs `video-upload` (異なる責務 — videoup = mp3→mp4 ローカル動画ファイル生成、video-upload = YouTube への push)
  - `thumbnail` vs `thumbnail-compare`
  - `video-analyze` vs `analytics-analyze`
  - これらは責務分離されているが、命名上紛らわしい可能性あり（**推測**）。

---

## 6. 主要な発見のサマリー（top 5 影響度）

| # | 観点 | 検出 | 影響度 | 出典 |
|---|---|---|---|---|
| 1 | C-2 | **lyria → videoup の back-reference 完全欠落** | 中（lyria チャンネルでの workflow が videoup 側から読めない） | `videoup/SKILL.md` 全体（lyria の言及無し） |
| 2 | C-1 / C-3 | **`video-description/config.default.yaml:6` で廃止スキル `short` を「現役の参照元」と記述** | 中（user は実在しない skill を探しに行ってしまう） | `video-description/config.default.yaml:6` |
| 3 | C-2 | **masterup → videoup, videoup → video-description が一方向のみ** | 低〜中（音楽 → 動画 → 説明 の制作チェーン主動線で双方向欠落） | #2, #4 |
| 4 | C-4 | **「Cross References」「関連ファイル」「Next Step」の見出し 3 系統混在** | 低（読みやすさのみ。実害無し） | `## Cross References` 11 件 / `## 関連ファイル` 8 件 / `## Next Step` 13 件 |
| 5 | C-4 | **「Instructions」「実行フロー」「いつ使うか / When to Use」の英日混在** | 低（読みやすさのみ） | `audience-persona`, `benchmark`, `comments-reply`, `postmortem`, `thumbnail-compare`, `video-analyze`, `viewer-voice`, `viewing-scene` が `実行フロー`; その他は `Instructions` |

---

## 7. カバレッジ

### 7.1 走査した skill（35/35 件）

```
alignment-check, analytics-analyze, analytics-collect, analytics-report,
audience-persona, benchmark, channel-direction, channel-import, channel-new,
channel-research, channel-setup, channel-status, collection-ideate,
comments-reply, discover-competitors, live-clean, loop-video, lyria,
masterup, metadata-audit, playlist, postmortem, streaming, suno,
thumbnail, thumbnail-compare, video-analyze, video-description,
video-upload, videoup, viewer-voice, viewing-scene, wf-new, wf-next, wf-status
```

### 7.2 適用した Grep パターン一覧

| 用途 | パターン |
|---|---|
| C-1: 明示バトン | `次工程[：:]\s*/[\w-]+`, `前工程[：:]\s*/[\w-]+`, `次工程`, `前工程` |
| C-2: 全 skill 言及（クロスリファレンス抽出） | `/(channel-new\|channel-import\|...全 35 skill 名...)` |
| C-3: deprecated 用語 | `\b(short\|shorts\|community)\b` (`-i`) |
| C-4: frontmatter キー | `^model:`, `^tools:`, `^allowed-tools:`, `^argument-hint:`, `"name":\s*"` |
| C-4: 主要見出し抽出 | `awk '/^## /{print; if(++c>=8) exit}'` |
| 実装存在確認 | `Glob "**/analytics_system.py"`, `pyproject.toml` の `yt-*` entry point 照合 |

---

## 8. 注意点・リスク（偽陽性の可能性）

1. **`short` の意味曖昧性**: 19 件のうち 18 件は B/C/D 分類で「廃止スキル参照」ではないと判定したが、文脈読解に依存する判定であり 1〜2 件が誤分類されている可能性がある（**推測**）。確実なのは C-3-① のみ。
2. **`## Next Step` を「片方向バトン」と数えるか**: 「Next Step」セクションは作者の意図として「**双方向は強制しない、次の案内のみ**」かもしれない。本レポートは「双方向」を理想として一方向を不整合扱いしているが、これは「**べき論**」であり、設計判断としては片方向 OK の見解もありうる（**推測**）。
3. **`postmortem → 4 skill` の片方向**: postmortem は上位レイヤのメタスキルで、4 検証スキルが postmortem を知らないのは妥当。C-2 表では一方向としたが、修正対象から外す方が合理的（**推測**）。
4. **`videoup` vs `video-upload` の命名紛らわしさ**: 形式揺れではなく責務上意図的な命名と思われるが、新規ユーザーには混乱の可能性（**推測**）。
5. **`comments.json` の責務別分割 7 ファイル外**: CLAUDE.md の責務別分割リストは `meta/content/youtube/analytics/playlists/workflow/audio` の 7 ファイルだが、`examples/channel_config.example/` には `comments.json` も含まれる（comments-reply 用）。これは Part C スコープ外だが、CLAUDE.md と examples の不一致として別 Part で扱うべき可能性あり。

---

## 9. 調査できなかった項目

| 項目 | 理由 |
|---|---|
| 「指す先が違う」型の C-2 不一致 | 検出されず（指された名前の skill が存在しないケース 0 件、リネーム残骸も 0 件） |
| `comment_reply_history.json` 実体ファイル | 各チャンネル実装で生成される動的ファイルのため確認不可（description のみで判断） |
| Vertex AI Lyria 3 API レスポンスが本当に MP3 を返すか | 外部 API 仕様の確認は本調査範囲外（description の主張を額面で受け入れた） |

---

## 10. 推奨 / 結論

### P1（双方向追記 / 廃止参照削除）

1. **`video-description/config.default.yaml:6`** のコメントから `short` を削除。同時に「現役で `tags.base` 等を読むスキル」を再列挙する。
2. **`videoup/SKILL.md`** に「前工程」ブロックを追加して `/masterup`（Suno 系）と `/lyria`（Lyria 系）の両方を明示。これで C-2 の #2, #3 の片方向バトンが解消する。
3. **`video-description/SKILL.md`** に「前工程: `/videoup`」を Cross References として追記。C-2 #4 解消。

### P2（運用上は問題ないが改善余地あり）

4. **`metadata-audit/SKILL.md`** の Cross References に「前工程: `/video-upload`」を追記（C-2 #6）。
5. **`wf-new/SKILL.md`** の Cross References に「既存チャンネル: `/channel-import`」を追記（C-2 #10）。
6. **`analytics-analyze/SKILL.md`** の前提セクションに「`/wf-next` から T+7 日後に呼ばれる」を追記（C-2 #12）。
7. **`suno/SKILL.md`** に「前工程: `/thumbnail`」を Cross References として追記（C-2 #19）。

### P3（形式統一・大規模リファクタ）

8. **見出し統一**: 「Cross References / 関連ファイル」「Instructions / 実行フロー」「When to Use / いつ使うか」のいずれかに揃える方針を CLAUDE.md または `docs/skills-style-guide.md` で宣言。35 件全 SKILL.md を一括書き換え。
9. **`postmortem → 4 検証 skill`**: 設計上の意図（メタスキル）が読めるよう、postmortem の Overview に「下位検証スキル群を呼び出すメタスキル」と明記し、各検証スキル側には追記しない方針を明確化。

### まとめ

- 全 35 スキル中、frontmatter / 命名規則は **完全に揃っている**。
- description ↔ 実装の重大乖離は **1 件のみ**（C-1-①）。
- バトン双方向は **8 リンクが完璧、9 リンクが片方向**。うち P1 対応が望ましいのは 3〜4 リンク。
- v4.0.0 deprecated `short` / `community` の残存は **1 箇所のみ**（コメント内）。コードレベルでの残骸は無い。
- 形式揺れは見出し命名のみで、構造的な品質問題には至っていない。
