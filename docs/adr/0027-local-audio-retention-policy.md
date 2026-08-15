# ローカル音源の保持・削除ポリシー（正常完了の定義と publish clean 連携）

## Status

accepted (2026-08-13, #3943)

## Context

ハイブリッド制作基盤では、ローカル Mac 上の音源・成果物（Suno DL 原本 `02-Individual-music/*.mp3`、master 類、`30-distrokid/`）をいつ・何をもって安全に削除できるかが決まっていなかった。「R2 push 済み = 削除可」ではない: ADR-0024 決定 5 により R2 は境界越えの受け渡し専用で lifecycle 削除されるため、公開までの期間はローカルが唯一の原本になる。

前提となる事実は次のとおり。

- 現行 `/publish --clean` の削除条件は `stage: "live"` / `phase: "complete"` / `upload.video_id` 非空の 3 条件で、ローカル FS の `workflow-state.json` を判定に使う。ADR-0024 決定 2 により state の正本は Git 管理へ移る。
- `phase: "complete"` は publish 完了後（= 公開後）に到達するが、`post_publish_configured` が偽のチャンネルではアップロード直後（publishAt が未来 = 未公開）でも complete になりうる。`upload.publish_at` は state に記録されている。
- `02-Individual-music/*.mp3` は DistroKid prep（`30-distrokid/` 生成）の入力でもある。DistroKid の Web 操作は自動化せず human-task として残す方針が確定済み。
- ADR-0025 決定 3 により、重量チャンネル（002ch 型）はアップロードまで local 所有、軽量チャンネル（003ch 型）は cloud 完結する。「完了」を state に書く主体がチャンネル型で異なる。

## Decision

### 1. 削除可能条件 =「正常完了」を機械判定可能な条件列で定義する

以下がすべて成立したとき、当該コレクションのローカル音源・成果物は削除可能とする。

1. **Git 正本 state の 3 条件**: `stage: "live"` / `phase: "complete"` / `upload.video_id` 非空（現行 clean mode 条件を継続）
2. **publishAt 経過（存在時のみ）**: `upload.publish_at` が state に存在する場合、その経過（= 実公開済み）を必須とする。欠如時は後方互換として条件 1 のみで成立する
3. **DistroKid 提出完了（distrokid 有効チャンネルのみ）**: `config/channel/distrokid.json` が存在するチャンネルでは、DistroKid への**提出時点**の human-task 完了記録が state にあることを必須とする。記録フィールドの実装形は実装ツリー側で確定する（human-tasks の決定的生成と整合させる）

### 2. 判定は pull 成功後の state で行い、pull 失敗は fail-closed とする

削除判定の前に `git pull` を必須とし、pull が成功しない限り（オフライン / non-fast-forward / リモート不達）削除に進まない。ADR-0024 の「non-ff は異常停止」と一貫し、古い state を根拠にした削除（クラウド側の書き込み中を見落とす事故）を構造的に防ぐ。

### 3. 削除は `/publish --clean` の手動承認フローに一本化する

クラウド完了通知（Discord）を契機とする自動削除フックは作らない。無人パイプラインに破壊的操作（rm）を組み込まず、`/publish --clean` の実績ある安全フロー（スキャン → ドライラン → 明示承認 → 削除）に乗せる。clean mode の改修は「判定前 pull ゲート + 条件 2・3 の追加」に限定する。

### 4. 早期削除パスと保持猶予は設けない

- クラウド受入検証パス後の公開前削除（早期削除パス）は作らない。削除タイミングは「正常完了後」の 1 つに保つ。容量圧迫は公開までの数日〜数週間に限られる
- 正常完了後の機械的な保持猶予（N 日）も設けない。`/publish --clean` が手動実行である事実が実質的な猶予として機能する

### 5. DistroKid 提出完了後は 30-distrokid/ の disc 配下音声のみ削除対象に加える

`spec.json` / `metadata.md` / `cover_art_3000.jpg` / `README.md` は保持する。提出内容の監査性（何をどう分割して出したか）は軽量ファイルが担い、容量の本体（disc 配下の音声コピー）だけを回収する。

## Consequences

- clean mode の改修（pull ゲート・publish_at 条件・distrokid 分岐・30-distrokid disc 音声の条件付き削除対象化）が実装ツリーの対象になる。
- DistroKid 提出完了を state に記録する実装（human-task 完了の記録経路）が実装ツリーの対象になる。
- 軽量チャンネル（cloud 完結）ではローカルの削除対象は実質 `02-Individual-music/` と `30-distrokid/` disc 音声になる（master 類・Master.mp4 はローカルに存在しない）。重量チャンネルは現行 clean mode とほぼ同じで、差分は「pull してから判定」のみ。
- `publish_at` が記録されていない既存 live コレクションは後方互換により従来どおり回収できる（回帰なし）。
- 用語集に「正常完了」を追加する（本 PR）。

## Considered Options

- **YouTube API での動画実在・公開状態の再確認を削除条件に追加**: ADR-0024 の fail-closed 遠隔再検証は外部 write 直前の規律であり、削除はローカル read + 人間承認ゲート付きのため過剰。不採用。
- **R2 マニフェストの存在を削除条件に使う**: マニフェストは lifecycle 削除で消える前提のため、削除条件としては参照できない。不採用。
- **クラウド完了通知を契機とする自動削除**: 無人パイプラインに破壊的操作を持ち込み、通知経路の誤発火が即データ喪失になる。不採用。
- **受入検証パス後の早期削除パス**: 公開まではローカルが唯一の原本（R2 は消える）であり、削除タイミングが 2 つに増える複雑さに見合わない。不採用。
- **DistroKid の配信開始確認まで保持**: human-task が「提出」と「確認」の 2 つに増え、確認の無人化手段もない（API 非対応）。差し戻しはレアケースで、DistroKid 自体が提出物を保持し Suno ライブラリからの再取得も可能。不採用。
- **30-distrokid/ 全体の削除対象化**: 提出記録の監査性を失う。音声のみ回収で容量目的は達成できる。不採用。

## Related

- ADR-0024（クラウド移譲アーキテクチャの原則 — R2 受け渡し専用・state 正本 Git・fail-closed）
- ADR-0025（実行基盤の選定 — チャンネル型による「完了」の書き手の違い）
- `docs/architecture.md::プロジェクト用語集::クラウド移譲`（正常完了）
- `.claude/skills/publish/references/clean.md`（本 ADR が判定条件の拡張を課す）
- Wayfinder 地図 #3293 / #3943
