# wf-new 企画規則

Phase 2〜3 で候補を設計するときにだけ本書を読む。入力モード、鮮度判定、停止条件、Phase 順、承認、保存と state 更新は `../SKILL.md` を正とし、本書では再定義しない。

## 現在のチャンネル規定（固定制約）

`../SKILL.md` の「固定制約の解決」で存在確認済みの channel config と規定文書を、候補生成中に変更できない境界として扱う。対象は `config/channel/*.json` の世界観・コンテンツ・音声等の明示設定と、検証済み JSON+HTML pair の `docs/channel/channel-direction.json`、`docs/channel/personas/persona-definition.json`、`docs/plans/viewing-scene-matrix.json`、`docs/channel/creative-constraints.json` のうち存在するものだけとする。各 pair は `RepositorySchema.CHANNEL_STRATEGY` で検証し、JSON だけを読む。片方だけ・HTML 不一致・schema/参照不正は fail-closed とし、旧 Markdown/HTML を parse しない。欠落文書から規定を推測せず、既存の fallback / 非停止契約を維持する。

Analytics、benchmark、open insights、ユーザー直接入力は候補を発見・順位付けする材料であり、現在の規定より優先しない。明示的な上流の方向性再設計で正本自体が更新されていない限り、これらの材料と規定が衝突した場合は規定を維持する。

Phase 3 の候補生成後、候補ごとに次を検証する。

| 項目 | 契約 |
|---|---|
| 適用規定 | 解決済みの規定から、この候補へ適用した具体的な制約と出典を列挙する |
| 適合根拠 | タイトル、視聴シーン、ペルソナ、音楽性、映像・サムネ方針が各規定を満たす理由を示す |
| 適合結果 | すべて満たす場合だけ `PASS`。1 件でも不明・違反なら `FAIL` |

`FAIL` 候補は警告付きで残さない。ユーザー判断へ委ねない。不合格候補だけを規定内で再生成し、再検証後の `PASS` 候補が `preview.candidate_count` 件になるまで繰り返す。規定を緩和して候補数を満たしてはならない。

必要件数を規定内で生成できない場合は、候補、`plan_proposals.md`、ユーザー選択肢を出力せず停止する。違反した規定、生成できなかった件数、再開条件（上流で正本を明示更新する、または規定内の追加材料を与える）を返す。

## ペルソナベース企画フレームワーク

前提スキル状態確認で確定した **第一ペルソナ 1 人** に対し、`preview.candidate_count` 個の企画候補を生成する。persona / viewing-scene の存在確認、停止 / fallback 条件、fallback 入力は `freshness-rules.md` の判定結果をそのまま適用し、fallback で作った第一ペルソナには使用した入力と根拠を明記する。

- `ttp_mode: false`: 同じ人物の別シーン・別感情・別利用文脈から情景を導出し、`differentiation_axes` と掛け合わせる
- `ttp_mode: true`: ペルソナは維持するが差別化軸は使わず、高再生パターンの転写をテーマ決定の直接根拠にする

`ttp_mode: false` では候補ごとに異なる差別化軸の組み合わせを割り当てる。`candidate_count=3` の例:

| 企画 | 差別化の切り口 |
|---|---|
| 企画 1 | 軸 A × 軸 B のバリエーション |
| 企画 2 | 軸 C × 軸 D のバリエーション |
| 企画 3 | analytics / benchmark fallback mode では競合の高再生パターンをペルソナ視点で再解釈。minimal mode では直接入力のテーマを別の差別化軸で再解釈 |

`candidate_count` を変更した場合は枠を増減する。analytics / benchmark fallback mode では競合パターン再解釈を含め、minimal mode ではユーザー直接入力と config だけを根拠にする。

`ttp_mode: true` では `candidate_count` 件を競合の高再生パターン順に割り当て、各候補に次を記録する。

| 項目 | 内容 |
|---|---|
| 転写元 | 競合チャンネル名 + 高再生コレクションまたは勝ちパターン |
| 転写する型 | タイトル構造、テーマ構造、利用シーンなどの構造・パターン・型 |
| 参照元が満たす欲求 | 欲求語彙 + ソース + 競合コメント / タイトル上の根拠 |
| 欲求整合 | タイトル・サムネイル・楽曲 / 音楽性が同じ欲求を満たす根拠 |
| 採用根拠 | ベンチマーク上の高再生実績 |

各企画にはターゲットペルソナ（名前・視聴シーン・ユースケース）と情景没入スコアを含め、`objects` が定義されていれば `objects.swappable` のオブジェクト定義も含める。`ttp_mode: false` では差別化ポイントを、`true` では転写元と欲求整合の根拠を加える。analytics / benchmark fallback mode では競合パターン参照を必須とする。minimal mode は `ttp_mode: false` の場合だけ、直接入力、config、仮説ペルソナ / 視聴シーンを根拠にし、競合パターン参照を要求しない。

背景色は `config/skills/thumbnail.yaml` の `image_generation.gemini.brand_background` が定義されていれば全コレクションで統一する。

### 第一ペルソナの企画バリエーション

複数ペルソナをローテーションしない。`collections/` 配下の `workflow-state.json` から `planning.target_persona` を収集する場合も人物の切り替えには使わず、`ttp_mode: false` では同一人物内の未使用シーン・感情・活動軸の選択に、`true` では persona の一貫性確認にだけ使う。

## 企画ルール

`config/channel/meta.json` の `channel.core_message` と `config/channel/content.json` の `genre.*` から世界観を読み取り、一貫した企画を作る。

### タイトルテンプレート

`config/channel/content.json` の `title.template` を使い、テーマに合わせて動的要素を調整する。

analytics mode / benchmark fallback mode では、ベンチマークの高再生タイトルにある情景描写の具体性と再生数の相関を判断材料にする。抽象的・汎用的なテーマ、場所のない形容詞、カタログ的なタイトルを避け、具体的な場所 + 天候 / 時間帯 + ムードで情景想起を助ける。minimal mode はこの分析をスキップする。

`ttp_mode: true` は高再生コレクションの実績テーマも優先するが、競合固有のタイトルや表現を複製せず、構造・パターン・型と欲求訴求の構造だけを転写する。

### 差別化軸

`ttp_mode: false` の場合だけ `config/skills/collection-ideate.yaml` の `differentiation_axes` を使う。既定軸は `location`、`time_of_day`、`activity`、`mood`。`ttp_mode: true` は掛け合わせをすべてスキップする。

`ttp_mode: false` かつ `composition_lock: true`（既定）では差別化軸を音楽プロンプト、概要欄訴求、タイトルバリエーションの内部メタデータとして扱い、サムネ構図には反映しない。サムネは TTP 参照画像 + `objects.fixed` で固定し、差分は `objects.swappable` の slot 値だけで作る。Phase 4 のプロンプトで軸の値そのものが露出していないことは `youtube_automation.infrastructure.media.composition_lock.axes_in_thumbnail_prompt()` で検証できる。

`composition_lock: false` は TTP を使わず毎回構図を設計する派生チャンネルだけで使う。`ttp_mode: true` では `composition_lock` にかかわらず差別化軸を候補生成に使わず、転写元だけを根拠にする。後続 skill の生成方針は変更しない。

### vote-log hook

`data/community/weekly-vote-log.json` があれば Sunday Vote の結果を theme weight に取り込み、第一ペルソナ内の候補順位へ反映する。ログ不在・空なら既存の差別化ロジックを変更せず続行する。この skill は read-only で、append は Studio 投票結果の確認後に `yt-vote-log append` が担う。

```python
from youtube_automation.configuration import channel_dir
from youtube_automation.domains.collections.weekly_vote_log import (
    compute_vote_log_weights,
    load_weekly_vote_log,
)

log = load_weekly_vote_log(channel_dir=channel_dir(), missing_ok=True)
result = compute_vote_log_weights(log, recent_weeks=4, decay=0.7)
```

`ttp_mode: true` はこの hook をスキップする。`false` では、`forced_axis` があればその軸を含む案を最低 1 つ残し、連続 2 週 1 位を別軸探索より優先する。`weights` は最新 1.0 から `decay=0.7` で減衰する重み付き平均として順位へ反映する。同じ計算は次で確認できる。

```bash
uv run yt-vote-log weights --recent 4 --decay 0.7
```

## オブジェクトデザインルール

`config/skills/collection-ideate.yaml` に `objects` がある場合だけ適用する。`objects.fixed` は全候補で固定し、`ttp_mode: false` は `objects.swappable` の slot 値を候補ごとに変える。`true` は差別化軸から値を作らず、転写元の高再生コレクションまたは勝ちパターンに基づいて定義する。

名前は短く詩的にし、ストーリーは「誰が、どんな場面で、なぜ」を描写し、ビジュアルは形状・色・質感まで具体化する。具体例は [object design examples](object-design-examples.md) を参照する。`objects` がなければこの規則をスキップし、`ttp_mode: false` はカラー・構図、`true` は転写元で視覚方針を決める。

## オリジナリティ保証ルール

`config/skills/collection-ideate.yaml` の `originality` を適用する。

- 競合タイトル・テーマとの類似度が `originality.max_similarity` を超えた場合、または既存コレクションとの類似度が高い場合は警告する
- `ttp_mode: false` は競合からパターン（構造）だけを学び、テーマそのものを複製しない
- `ttp_mode: true` は実績テーマを優先できるが、競合固有のタイトル・シリーズ名・表現は複製せず、構造・パターン・型として転写する
- `ttp_mode: true` は `originality.require_pattern_reference` にかかわらず転写元を各企画へ記録する
- `ttp_mode: false` かつ `originality.require_pattern_reference: true` は、analytics / benchmark fallback mode では競合パターン参照元と差別化ポイントを、minimal mode では直接入力 + config の根拠と差別化ポイントを記録する
