# クラウド移譲アーキテクチャの原則（境界・状態正本・冪等性・R2 配置）

## Status

accepted (2026-08-08, #3299)

## Context

複数チャンネル共通のハイブリッド制作基盤として、Suno のブラウザ工程だけをローカル Mac に残し、引き渡し後はクラウドで無人完走させる。先行決定（#3293 チャーティング時のグリリング）で、コントロールプレーン = Git、データプレーン = Cloudflare R2（MediaStore 抽象の第一実装）、IaC = Terraform、通知 = Discord、OAuth token は ephemeral パターンでの持ち出し容認、起動はスケジュール駆動ポーリングまで確定している。

現行実装には次の制約がある。automation-schedule の Hard Gate 3 は「ローカルファイル / OAuth / Chrome / Suno Helper / ffmpeg / ローカル media のいずれかが必要なら local」という列挙式で、wf-auto 全体を local 判定している。状態機械（`wf-auto-state.py`）の真の正本は JSON state ではなくローカル FS 上の実成果物であり、resolver は毎回実ファイルを stat する。排他は channel-dir 単位の `fcntl.flock` + TTL リースで、ネットワーク越しには使えない。冪等性 tracking（`upload_tracking.json` / `post_publish_history.json` / `pinned_comment_history.json`）はロックなしの read-modify-write で、単一実行者の直列化に安全性を依存している。R2 無料枠 10GB に対し 1 コレクションの中間物は最大 9.7GB（`master-mix.wav` 1.5GB + `Master.mp4` 7.8GB 実測）。

## Decision

### 1. cloud/local 境界は能力ベースの規則 1 本で定義する

local に残る条件は「人間のブラウザ工程（Suno UI）を必要とすること」のみとする。OAuth（ephemeral 持ち出し決定済み）・ffmpeg（クラウドで実行可能）・media（R2 経由で受け渡し）は local 判定理由から撤廃し、Hard Gate 3 の列挙定義をこの規則で置き換える。AI 工程（企画・プロンプト作成）は cloud で実行する。パイプラインは cloud（企画 → prompts 生成）→ local（Suno 生成・DL・R2 push）→ cloud（受入検証 → 公開）のサンドイッチ構造になる。工程ごとの local/cloud 対応表は実装 issue 側の成果物とし、本 ADR には載せない。

### 2. 状態正本は Git 管理へ移す

`workflow-state.json` と冪等性 tracking 群をチャンネルリポジトリの git 管理に入れる。local / cloud とも「読む前に pull、書いたら即 commit + push」。書き手は工程を所有する側に限定する（single-writer）。non-fast-forward push は自動マージせず即異常停止 + Discord 通知とする。

### 3. ネットワーク越しの分散ロックは作らない

cloud/local 間の競合は工程所有権で構造的に排除する。「いま誰の番か」は Git 上の state の phase が表し、single-writer 原則により state 自体が引き渡しトークンになる。スケジューラの at-least-once による同側内の多重起動は各実行環境内のロックで完結させる（local = 既存 flock + TTL リース続投、cloud = 実行基盤内ロックで ADR-0025 に委譲）。

### 4. 冪等性は二重チェック + fail-closed

- 各工程は「tracking 記録 + 実成果物（またはマニフェスト）確認」の二重チェックで再実行安全にする。
- 外部 write（YouTube insert 等）の直前に遠隔側の再検証（同タイトル検索等）を必須とし、検証エラー時は fail-open ではなく fail-closed（中止 + Discord 通知）とする。
- tracking 群のロックなし read-modify-write は「実行者が常に一意」（決定 3）の直列化に安全性を依存する。この前提を破る変更は本 ADR の改訂を要する。
- 冪等キー（video_id / collection 名 / step 名）はホスト非依存であり継続する。

### 5. R2 は境界を越える受け渡し専用とする

工程内中間物は R2 に置かない。実行基盤の制約でメディア工程が多段ジョブになる場合のみ、当該中間物を置いてよい（完了後の lifecycle 削除を必須とする）。クラウド生成物（`Master.mp4` 等）のローカル還流は行わないことを既定とし、必要時のみ手動 pull する。

### 6. 受け渡しはマニフェスト = 完了マーカーで規約化する

キー配置は `<channel>/<collection>/<受け渡し点>/` とし、ファイル一覧 + サイズ + SHA-256 checksum を持つマニフェストを、全ファイル PUT + 検証後に最後に PUT する（R2 の強整合により完了マーカーとして成立する）。後工程はマニフェスト経由でのみオブジェクトを読み、バケット listing を信じない。マニフェストが無ければ「存在しない」扱いとし、不完全ファイルの後工程流入を構造的に防止する。マニフェストの正本は R2 とし、Git 側の state には受け渡し完了時にマニフェストのキー + ルート checksum のみを記録する。

### 7. クラウド実行は pull → run → push のサンドイッチ実行モデル

クラウドジョブは開始時に Git clone + マニフェスト検証つき R2 pull でローカル FS を再構成し、既存のローカル前提コード（resolver 含む）を無改造で動かし、終了時に成果物 push + state commit する。MediaStore 抽象は pull / push を行う転送層としてのみ導入し、resolver や各工程へのストレージ抽象の注入は行わない。

### 8. Lyria 分岐点

音源確保ステージは `engine` による分岐点である。ブラウザ工程を持たない engine（lyria）は決定 1 の境界規則が自動的に全工程 cloud を導くため、追加の決定は不要（実装は将来・低優先）。

## Consequences

- 新工程の local/cloud 判定は「ブラウザ工程か否か」だけで自明になり、automation-schedule Hard Gate 3 の列挙定義は本規則へ追従する実装変更が必要になる。
- `workflow-state.json` / tracking 群の gitignore 解除と push 運用の実装が必要になる。state の変更履歴が Git に残り、監査可能になる。
- 既存の flock リース・冪等キー・`allow_external_publish` ゲートは無傷で継続する。
- 外部 write 直前検証の fail-closed 化により、検証系の一時障害でもパイプラインは停止側に倒れる（無人運用では望ましい）。
- R2 滞留は境界越えの受け渡し物（個別音源、数百 MB 規模）が主となり、無料枠の成立条件「滞留日数 × 月間コレクション数 ≤ 約 30」を満たしやすくなる。逃げ道（多段ジョブの中間物）を使う実装は lifecycle 削除の実装を伴う義務を負う。
- サンドイッチ実行モデルにより、メディア工程を 1 ジョブで完走できるディスク・実行時間を持つことが実行基盤（ADR-0025）の要求条件になる。

## Considered Options

- **列挙式の境界定義の継続**: 工程追加のたびに表を更新する必要があり、wf-auto を local に縛った現状の再生産になるため不採用。
- **state 正本を R2 に置く**: 強整合はあるが「Git = 制御面 / R2 = データ面」の先行決定と矛盾し、変更履歴・レビュー可能性も失うため不採用。
- **Git ベースの分散リース**: lease ファイルの commit/push は遅く、失敗時の残骸が履歴を汚す。工程所有権で競合自体を排除できるため不要と判断し不採用。
- **resolver への MediaStore 抽象注入（R2 直接 stat）**: 全 reader/writer への抽象注入が必要で改造範囲が爆発する。pull による FS 再構成なら既存コード無改造で済むため不採用。
- **マニフェスト全文の Git 複製**: 二重正本を生むだけで完了マーカー性は R2 側にしかないため不採用。

## Related

- ADR-0025（実行基盤の選定 — 本 ADR の決定 3・5・7 が要求条件を課す、#3300）
- `docs/architecture.md::プロジェクト用語集::クラウド移譲`
- Wayfinder 地図 #3293 / 調査 #3294〜#3298（`research/r2-facts` ほか 5 ブランチ）
- `.claude/skills/automation-schedule/SKILL.md` Hard Gate 3（本 ADR が置き換える境界定義）
- #3299
