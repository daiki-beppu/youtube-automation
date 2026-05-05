# SKILL.md 監査レポート (2026-05)

Issue: [#130 chore: `.claude/skills/*/SKILL.md` の冗長記述を点検し最適化](https://github.com/d-bep/yt-channels/issues/130)

## 1. イントロ

`.claude/skills/` 配下の 31 SKILL.md を全件点検し、

- **description triggering 精度**
- **内部の重複・冗長**
- **実装との乖離**（v1 → v2 設定 namespace、廃止 CLI 等）
- **陳腐化したリンク・参照**（rename 済み skill への古い参照、削除済み skill 参照）

の 4 観点で検出結果をリストアップする。

本 PR (#130) では完了条件 #2 の「曖昧スキル名 rename」と本監査ドキュメントの生成のみを実施する。
個別の fix は follow-up issue として切り出し、粒度ごとに別 PR で順次対応する。

対象範囲:

- `.claude/skills/*/SKILL.md` 全 31 件
- 各 skill の `references/*.md`、`config.default.yaml` も補助参照
- 連鎖呼び出し（cross-skill `/...` references）の整合性

## 2. 本 PR で実施した rename

`<domain>-<action>` 形式に揃え、自然言語からの triggering の曖昧性を排除する。後方互換 alias は作らない（order.md「rename 一本で完結させる」方針）。

| 旧 | 新 | 改名理由 |
|---|---|---|
| `analyze` | `analytics-analyze` | 「何を analyze するか」が名前から不明 |
| `collect` | `analytics-collect` | 「何を collect するか」が名前から不明 |
| `report` | `analytics-report` | 「何の report か」が名前から不明 |
| `status` | `channel-status` | YouTube 統計か制作進捗 (`/wf-status`) か曖昧だった |
| `description` | `video-description` | 名詞 1 語、コンテキスト無し |
| `upload` | `video-upload` | 「何を upload するか」が名前から不明 |
| `ideate` | `collection-ideate` | 抽象動詞、何の ideation か不明 |
| `persona` | `audience-persona` | 「誰の persona か」が名前から不明 |

### 影響を受けたファイル

| 種別 | 件数 | 内容 |
|---|---|---|
| ディレクトリ rename | 8 | `git mv .claude/skills/<old> .claude/skills/<new>` |
| YAML front-matter `name:` 書換 | 8 | 各新ディレクトリの `SKILL.md` |
| `.claude/skills/**/*.md` のスラッシュコマンド・パス参照書換 | 24 | 連鎖呼び出し（`/<old>` → `/<new>`、`.claude/skills/<old>/` → `.claude/skills/<new>/`、`config/skills/<old>.yaml` → `config/skills/<new>.yaml`） |
| `.claude/skills/**/*.yaml` の自己参照書換 | 2 | `collection-ideate/config.default.yaml` / `video-description/config.default.yaml` |
| プロダクション源 (`src/youtube_automation/`) のコメント・エラーメッセージ書換 | 2 ファイル / 5 行 | `agents/youtube_auto_uploader.py` (4 箇所) / `utils/metadata_generator.py` (1 箇所) — すべて `/description` → `/video-description` |
| テストファイルの skill パス定数追従 | 1 | `tests/test_skill_cost_documentation.py::IDEATE_SKILL_MD` を `ideate` → `collection-ideate` |
| 新規テスト | 1 | `tests/test_skills_rename.py` で rename の不変条件 (旧ディレクトリ消滅 / 新 `name:` 値 / クロスリファレンス書換 / プロダクション源書換 / 監査ドキュメント存在) を 53 ケース parametrize で担保 |

`yt-skills sync` パイプライン (`src/youtube_automation/cli/skills_sync.py`) はディレクトリ名を `iterdir()` で動的取得するため、rename は配布側に影響しない（`tests/test_skills_sync.py` で end-to-end 不変条件を担保済み）。

### 下流チャンネルリポジトリへの migration 手順

下流チャンネルリポジトリで `config/skills/<old>.yaml` を上書き設定として置いている場合、以下のいずれかを手動で実施する必要がある（後方互換 alias は提供しない）:

| 旧パス | 新パス |
|---|---|
| `config/skills/ideate.yaml` | `config/skills/collection-ideate.yaml` |
| `config/skills/description.yaml` | `config/skills/video-description.yaml` |

その他 6 件は skill-config を持たないため移行不要。

## 3. 監査結果

### 3.1 description triggering 精度

| skill | 検出箇所 | 提案修正 |
|---|---|---|
| `alignment-check` | description 末尾「方向性見直し時に必ず使用すること」常套句 | 「など」連発と「必ず使用すること」を削り、トリガー語を厳選 |
| `analytics-analyze` | 「など、データに基づく判断が求められる場面で必ず使用すること」常套句 | トリガー語と前後関係 (`/analytics-collect` 後実行) の 2 文構成に整理 |
| `analytics-collect` | 「analytics_system.py の実行が必要な場面で必ず使用すること」（陳腐化）— `analytics_system.py` は `yt-analytics` に統合済み | CLI 名 `yt-analytics` に追従（実装乖離も併記） |
| `analytics-report` | 「など、既存レポートの参照・比較が必要な場面で必ず使用すること」常套句 | 「過去レポートの比較やパフォーマンスレビュー時」と既出冒頭文の重複を解消 |
| `audience-persona` | 「など。…必ず使用すること」常套句、トリガー語が 6 個並列で発動条件がぼやける | 主要 3 トリガー語に絞る |
| `benchmark` | description 156 chars。冒頭文と「など、競合情報の取得・更新に関わる場面で…」が同義反復 | トリガー語と CLI/output (`docs/benchmarks/*.md`) の 2 文構成に整理 |
| `channel-direction` | 「など、新チャンネルの戦略的方向性を対話で決定する場面で使用すること」常套句 | トリガー語列挙と前後関係を分離（既に `/channel-research` 後 / `/channel-setup` 前は明記済み） |
| `channel-import` | 「config 生成」「channel-import」自身がトリガー語に混入 | skill 名を直接トリガーにするのは triggering 学習を阻害するため除去 |
| `channel-new` | 「など、新規チャンネルのセットアップに関わる場面で必ず使用すること」常套句 + 「競合発掘→分析→方向性決定→セットアップの全工程のエントリポイント」が文脈情報として混入 | description は単発判定のためのみに使い、ワークフロー説明は本文に移動 |
| `channel-research` | 「など、新チャンネル開設時の競合チャンネル分析に関わる場面で使用すること」常套句 | 「など」削除 |
| `channel-setup` | 「セットアップ」「設定ファイル生成」「config 作成」「チャンネル構築」が同義反復 | 1 トリガー語に集約 |
| `channel-status` | 「ローカルのコレクション制作進捗は /wf-status」と紛らわしい仲間スキルへの誘導が混入 | 誘導は When to Use 本文へ |
| `collection-ideate` | 「など、新規コンテンツの方向性を決める場面で必ず使用すること」常套句 | 「など」削除 |
| `comments-reply` | 225 chars (最長クラス)。「config/channel/comments.json のルール…」のような実装詳細が description に混入 | description は triggering 専用に縮め、設定ファイルは Overview / Quick Reference に移動 |
| `discover-competitors` | 202 chars。「discover-competitors」自身がトリガー語に混入 | skill 名トリガーは除去、用途を 1 文に整理 |
| `live-clean` | トリガー語 8 個並列、「など、公開済みコレクションの不要ファイル削除に関わる場面で必ず使用すること」常套句 | 主要 3 語に絞る |
| `loop-video` | 「など、静止画を動画化する場面で必ず使用すること」常套句、Veo モデル名 (`Veo 3.1`) が description に混入 | モデル名は本文へ。description は triggering 専用 |
| `lyria` | 205 chars。「composition.json 設計」など実装詳細が description に混入 | 実装詳細は本文へ |
| `masterup` | 211 chars。前工程・次工程の説明（`/suno`、`/videoup`）が description に混入 | パイプラインフローは When to Use へ |
| `suno` | 222 chars。`SunoAI V5` バージョン番号、ファイル名 (`suno-prompts.md`) が description に混入 | 実装詳細は本文へ |
| `thumbnail` | 「main.pngなど、視覚コンテンツの作成に関わる場面で必ず使用すること」常套句 | ファイル名トリガーは除去 |
| `thumbnail-compare` | 「方向性見直し時に必ず使用すること」常套句 | 削除 |
| `video-analyze` | 210 chars。「signature 要素抽出」「retention drop の構造的原因」のように専門用語が description に羅列され、自然文 triggering を阻害 | 主要トリガー (動画解析・フック構造抽出) のみに整理 |
| `video-description` | 「など、YouTube投稿用テキストが必要な場面で必ず使用すること」常套句 | トリガー語列挙の重複（概要欄 / メタデータ生成 / 動画の説明文）を統合 |
| `video-upload` | 87 chars と短いが「Complete Collection のアップロードと live 移行を実行」と動作説明が混入 | description は triggering 専用、動作は Overview へ |
| `videoup` | 「動画変換、音声から動画への変換、generate_videos、MP3→MP4、videoup など」と曖昧トリガー語が並列で `/lyria`・`/masterup` 経由のパイプラインと区別しにくい | スキル境界を明示するキーワードに絞る |
| `viewer-voice` | 「ベンチマーク競合のコメントを収集・分析」が冒頭で済んでいるのに「コメント分析」「コメント調査」と再記述 | 重複削除 |
| `viewing-scene` | 「方向性見直し時に必ず使用すること」常套句 | 削除 |
| `wf-new` | 末尾「既存コレクションの進行は /wf-next」誘導が description に混入 | 誘導は本文へ |
| `wf-next` | description 内に「読むだけで進捗を見たい場合は /wf-status、新規コレクション開始は /wf-new」誘導が混入 | 誘導は本文へ |
| `wf-status` | 「など」が 2 回出現、「など、collections/planning/ 配下の現在地を一覧・詳細表示するときに使用する」常套句 | 「など」を 1 回に削減 |

#### 共通アンチパターン（横串）

- 「**〜など、〜場面で必ず使用すること**」常套句が **22 / 31 skill** で検出された。triggering 学習にノイズとなるだけで情報を増やさないため、**ガイドラインで明示禁止**にすべき
- description 末尾でスキル相互誘導 (`/wf-next`、`/wf-status` 等) を行う skill が 5 件。**誘導は本文 (When to Use / 連携) で記述するルール**に揃える
- description 200 字超の skill が 6 件 (`comments-reply` 225 / `discover-competitors` 202 / `lyria` 205 / `masterup` 211 / `suno` 222 / `video-analyze` 210)。**150 字を上限ガイドラインとする**

### 3.2 内部の重複・冗長

| skill | 検出箇所 | 提案修正 |
|---|---|---|
| `analytics-analyze` | `Quick Reference` 表と When to Use 本文で「`/analytics-collect` 完了後」を 2 度記載 | When to Use 側に集約 |
| `analytics-collect` | Overview / Quick Reference / 後続案内で `/analytics-analyze` 連携を 3 度記載 | 1 箇所に集約 |
| `analytics-report` | `/analytics-report latest` / `/analytics-report html` / `/analytics-report list` の説明が Quick Reference 表 + 本文セクションで重複 | 表のみに統一 |
| `collection-ideate` | 334 行と巨大。`config/skills/collection-ideate.yaml` への参照が 9 回出現。Phase 4-2 ブロックと「差別化軸」「originality」「objects」セクションは別 reference へ切り出すと SKILL.md が短くなる | 詳細仕様は `references/` へ分割 (現在は `freshness-rules.md` / `collection-lifecycle.md` / `object-design-examples.md` のみ) |
| `lyria` | 347 行と最長。`composition.json` のスキーマ説明・DJ フェーズ展開ロジック・コスト試算がすべて SKILL.md 直下 | スキーマと展開ロジックを `references/composition-schema.md` に分離 |
| `suno` | 291 行。Style 文・Lyrics テンプレ・パターン YAML の 3 詳細仕様が同居 | `references/style-templates.md`・`references/lyrics-templates.md` に分割 |
| `thumbnail` | 315 行。`single_step` / `two_phase` / `ttp_swap` の 3 モード仕様 + 画像生成プロバイダー切替 + コスト試算が同居 | モード別仕様を `references/modes.md` に分離 |
| `wf-new` | Phase 構造の説明が `SKILL.md` 本文と `references/schema.md` で重複 | 本文は概要のみ、詳細は `references/schema.md` へ集約 |
| 共通 | 12 skill で `## Quick Reference` 表を持つが、内容が `## 引数` / `## 使い方` の本文と重複している skill が 7 件 | Quick Reference を「引数表」に統合し、本文重複を削除 |

### 3.3 実装との乖離

| skill | 検出箇所 | 提案修正 |
|---|---|---|
| `analytics-analyze` | `SKILL.md:64` `channel_config.tags.themes` ← v1 の global namespace 表記。v2 では `config.content.tags.themes` (CLAUDE.md「責務別ネームスペース」参照) | `config.content.tags.themes` に置換 |
| `analytics-collect` | description 中「`analytics_system.py` の実行が必要な場面で」← `analytics_system.py` は `yt-analytics` (entry point) として `pyproject.toml` `[project.scripts]` に統合済み | `yt-analytics` に置換、実体スクリプトの直接実行は最後の手段である旨を明記 |
| `benchmark` | `yt-benchmark` CLI に統合済みだが `python scripts/benchmark_*.py` 形式の旧呼び出しが本文に残っていないか要確認 | 全件 grep で `uv run yt-*` 形式に揃える |
| `channel-setup` | `references/config-generation-rules.md` 内の skill-config 一覧表（rename 後は `collection-ideate` / `video-description`）の整合は本 PR で書換済み | 完了 |
| `lyria` | `Lyria 3` モデル名と Vertex AI Studio の API バージョンが本文と config.default.yaml で食い違う可能性 | バージョン文字列を 1 箇所定義に集約 |
| `loop-video` | `Veo 3.1` バージョン番号が description と本文の 2 箇所にハードコード | 本文の 1 箇所に集約 |
| `thumbnail` | `gemini-2.5-flash-image` などのモデル名が本文に直接記載されている可能性 | モデル名は `image_provider` の設定責務にあるため SKILL.md からは抽象化 |
| `video-upload` | `descriptions.md` 検証ロジックがプロダクション側 (`youtube_auto_uploader.py`) にある旨を明記すべき | 本 PR でメッセージ内 `/video-description` 参照は更新済み |
| 共通 | `pyproject.toml` `[project.scripts]` の `yt-*` CLI 30 件超のうち、SKILL.md から参照されているのは一部のみ。CLI 一覧と SKILL.md の対応表を `docs/cli-skill-mapping.md` として整備すべき | follow-up issue 候補 |

### 3.4 陳腐化したリンク・参照

| skill | 検出箇所 | 提案修正 |
|---|---|---|
| 全 skill 横断 | rename 前の旧スラッシュコマンド `/analyze`、`/collect`、`/report`、`/status`、`/description`、`/upload`、`/ideate`、`/persona` への参照は本 PR で全件書換済み (`tests/test_skills_rename.py` で担保) | 完了 |
| `channel-import` | description 内「config 生成」「channel-import」のように skill 名そのものをトリガー語にしている → triggering 学習を阻害 | 削除 |
| `discover-competitors` | description 内「discover-competitors」自身がトリガー語に混入 | 削除 |
| `viewer-voice` | description 内「ユーザーリサーチ」← skill 自体を表すわけではなく、ベンチマーク文脈の汎用語のため誤発動の懸念 | スコープを「コメント収集・分析」に絞る |
| 削除済み skill 参照 | `branch-clean` skill は本 repo の `.claude/skills/` に存在せず（dotfiles 由来）、SKILL.md 本文から `/branch-clean` 参照があれば dead link | 全件 grep の結果ゼロ件 (本 PR 時点) |

## 4. 修正方針

| 項目 | 方針 |
|---|---|
| 本 PR (#130) | rename 8 件 + クロスリファレンス書換 + 監査ドキュメント生成のみ |
| 個別 SKILL.md の冗長記述 fix | follow-up issue として観点別に切り出す（下記 §5）。1 PR 1 観点、もしくは 1 PR 1 高凝集グループ |
| 後方互換 alias | 提供しない（order.md 明示禁止）。下流チャンネルリポジトリの `config/skills/<old>.yaml` 移行は CHANGELOG / PR description に手順記載 |
| description の上限ガイドライン | 150 字（`writing-skills` skill / `.claude/skills/` 全体ガイドラインに反映、別 issue） |
| 「〜など、〜場面で必ず使用すること」常套句 | ガイドラインで禁止指定 |

## 5. follow-up issue 起票候補

監査結果を粒度別に切り出した起票候補。それぞれ別 issue として `gh issue create` する想定。

| # | 観点 | スコープ | 想定 issue タイトル |
|---|---|---|---|
| F1 | description triggering | 22 skill の「〜など、〜場面で必ず使用すること」常套句を一斉削除 | `chore: SKILL.md description から「〜など…必ず使用すること」常套句を削除` |
| F2 | description triggering | 6 skill (`comments-reply` / `discover-competitors` / `lyria` / `masterup` / `suno` / `video-analyze`) の description を 200 字 → 150 字以内に圧縮 | `chore: 長すぎる SKILL.md description を 150 字以内に圧縮` |
| F3 | description triggering | description 内のスキル相互誘導 5 件を本文へ移動 | `chore: description 内のスキル相互誘導を本文へ移動` |
| F4 | 内部の重複・冗長 | 巨大 SKILL.md 4 件 (`collection-ideate` / `lyria` / `suno` / `thumbnail`) を `references/*.md` 分割 | `refactor: 巨大 SKILL.md を references/ に分割` |
| F5 | 内部の重複・冗長 | Quick Reference と本文の重複（7 skill） | `chore: SKILL.md の Quick Reference と本文重複を解消` |
| F6 | 実装との乖離 | `analytics-analyze` の `channel_config.tags.themes` を v2 namespace に追従 | `fix(skill): analytics-analyze の v1 設定参照を v2 namespace に追従` |
| F7 | 実装との乖離 | `analytics-collect` description の `analytics_system.py` を `yt-analytics` に置換 | `fix(skill): analytics-collect description の旧スクリプト名を CLI 名に追従` |
| F8 | 実装との乖離 | `pyproject.toml` `[project.scripts]` と SKILL.md の対応表を `docs/cli-skill-mapping.md` として整備 | `docs: yt-* CLI と SKILL.md の対応表を整備` |
| F9 | ガイドライン | description 上限 150 字 + 常套句禁止を `writing-skills` 系ガイドラインに反映 | `docs: SKILL.md description のガイドラインを明文化` |

## 6. 検証

本 PR の rename / 書換が壊れていないことを以下で担保:

| テスト | 対象 |
|---|---|
| `tests/test_skills_rename.py` (新規 53 ケース) | 旧ディレクトリ消滅 / 新 `name:` 値 / クロスリファレンス書換 / プロダクション源 `/description` → `/video-description` 書換 / 監査ドキュメント存在 |
| `tests/test_skills_sync.py` (既存) | rename 透過 — `yt-skills sync` のディレクトリ列挙が rename 後も新名を返すこと |
| `tests/test_skill_cost_documentation.py` (パス追従) | `IDEATE_SKILL_MD` 定数を `ideate` → `collection-ideate` に追従 |
