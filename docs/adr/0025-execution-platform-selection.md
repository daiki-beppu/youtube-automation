# 実行基盤の選定（AI 工程 / メディア工程 / スケジューラ）

## Status

accepted (2026-08-12, #3300)

## Context

ADR-0024 はクラウド移譲の原則（能力ベース境界・状態正本 Git・サンドイッチ実行）を確定し、本 ADR に 2 つの要求条件を課した: クラウド側の多重起動は実行基盤内ロックで完結させること（決定 3）、メディア工程を 1 ジョブで完走できるディスク・実行時間を持つこと（決定 5・7）。

入力となる事実は次のとおり（調査全文は `research/platform-{cloud-run,github-actions,codex-cloud,vps}` / `research/r2-facts` ブランチ）。

- クラウドジョブが動く対象はチャンネルリポジトリ（private）。GitHub プランは Free で、private リポジトリの Actions 無料枠は 2,000 分/月・既定の支出上限 $0（超過時は課金されず停止する）。本体リポジトリ（public）の CI は無料枠を消費しない。
- メディア工程の負荷は `overlays.enabled` で 2 レジームに分岐する。軽量レジーム（映像 stream copy、2 時間尺でも数分）と重量レジーム（オーディオスペクトラム visualizer 等を全尺 filter_complex + libx264 再エンコード）。パイロットの実態は deepfocus365（002ch）= 重量、soulful-grooves（003ch）= 軽量。
- GitHub Actions のディスクは 14GB。軽量レジームの中間物 + ツールチェーンは約 11.5GB で収まるが余裕は小さい。重量レジームは実行時間・ディスクの両面で不成立（research #3296）。転送課金はなく、R2 の egress も無料。
- `schedule:` cron の遅延・drop は公式に明記されている。パイプラインは状態駆動・冪等再開であり、公開時刻は publishAt（アップロード時の絶対時刻指定）が守るため、起動遅延は数時間・稀な drop まで許容できる（グリリングで確定）。
- Claude Code はサブスクリプションの OAuth token（`claude setup-token`）を CI secret に置く公式経路があり、API 従量なしで headless 実行できる。Codex は CI でのサブスク認証経路が未整備で、公式文書化されているのは `openai/codex-action@v1`（API キー従量）と、時刻起点トリガを持たない Codex Cloud（`@codex` メンション等のイベント起点のみ）。
- コスト制約はチャーティング時に「0 円」で確定済み。グリリングで「完全 0 円を原則とし、金額次第で小額従量を許容」まで解像度を上げた。

## Decision

### 1. クラウド工程のホストは GitHub Actions（チャンネルリポジトリ）とする

AI 工程（企画・プロンプト作成）と軽量レジームのメディア工程は、チャンネルリポジトリの GitHub Actions で実行する。AI 工程とメディア工程でホストを分けず、運用を 1 系統に保つ。

### 2. AI 工程は Claude Code headless + サブスク OAuth token で実行する

`claude setup-token` で発行した OAuth token を GHA secret に置き、サブスクリプション消費（API 従量なし）で実行する。agent CLI の起動はスクリプト内の 1 境界に隔離し、Codex への差し替え点とする（決定 7）。

### 3. メディア工程はレジームで分岐する

- **軽量レジーム**（`overlays.enabled: false`・映像 stream copy）: GitHub Actions で実行する。
- **重量レジーム**（`overlays.enabled: true`・全尺再エンコード）: 当面 local で実行する。これは ADR-0024 決定 1 の能力ベース境界に対する**基盤制約による暫定例外**であり、境界規則そのものの変更ではない。重量チャンネルでは Master.mp4（7.8GB 級）の R2 往復を避けるため、動画化に続く publishAt アップロードまでを local の工程所有権に置く。

### 4. スケジューラは GHA `schedule:` cron + `concurrency:` グループとする

日次ポーリングの cron で起動し、workflow の `concurrency:` グループを ADR-0024 決定 3 が要求する「クラウド側実行基盤内ロック」の実装とする。外部トリガー補強（Cloud Scheduler → `repository_dispatch`）は行わない（決定 8 の切替条件へ送る）。automation-schedule には cloud 工程用の第 5 backend（github-actions）を追加し、local 側（重量メディア工程・Suno ブラウザ工程）は既存 backend + flock リースを続投する。

### 5. ランナー定義はスクリプト集約とし、コンテナ化しない

ジョブ本体は「git clone → R2 pull → `uv run yt-*` コマンド列 → 成果物 push + state commit」の POSIX スクリプトに集約し、workflow YAML は「スクリプトを呼ぶだけの薄い皮」に制限する。基盤固有の記述（トリガ・concurrency・secret 参照）だけを YAML に置く。クラウドでは Nix devShell を使わず uv 直行とする（devShell 必須規約のクラウド例外）。

### 6. コスト規律は完全 0 円を原則とする

支出上限 $0 を維持し、無料枠超過 = 自動停止を fail-closed として受け入れる。上限を解除する場合の許容額は月 $5 とする（常用予算ではなく、解除判断の上限線）。

### 7. Codex escape は両建て序列 + 月次 canary とする

Claude 経路が塞がれた場合の切替先を 2 段で定義する。

- **第一 escape: `openai/codex-action@v1`**（API キー従量・公式文書化済み）。決定 5 のスクリプト境界で CLI を差し替えるだけで移行できる。GHA cron から自動起動できる経路はこれを正本とする。
- **第二 escape: Codex Cloud**（0 円・ChatGPT サブスク消費）。人間 actor の `@codex` メンションでは受付を確認できるが、GHA の `github-actions[bot]` actor が投稿した同内容のメンションでは受付されなかった（#4059）。そのため自動 cron には使わず、人間が開始する復旧経路として保持する。

「日常的な両対応」の担保として、第一 escape 経路を**月次 canary** で実際に実行し、生存確認する。

bot / human actor の比較条件と観測結果は `docs/investigations/2026-08-16-codex-cloud-bot-trigger.md` に固定する。

### 8. 撤退・切替条件

1. **無料枠の恒常超過**: Actions 2,000 分/月を 2 か月連続で使い切る、または R2 無料枠成立条件（滞留日数 × 月間コレクション数 ≤ 約 30）が恒常的に崩れる → Cloud Run Jobs を月 $5 枠内で再評価する。
2. **重量レジームのクラウド化需要**: overlay 有効チャンネルの増加や local 運用の負担増 → Cloud Run Jobs / VPS を予算再交渉つきで再評価する（GitHub Actions は重量不成立の結論を維持）。
3. **cron の遅延・drop の実害**: 引き渡し後の追従遅れが常態化 → `repository_dispatch` による外部トリガー補強を追加する(基盤は替えない)。
4. **サブスク OAuth 経路の変更・停止**: CI でのサブスク消費が塞がれた → API 従量（$5 枠で足りるか実測）または決定 7 の Codex 経路へ切り替える。
5. **軽量レジームのディスク超過**: 尺・ビットレート増で 14GB を超えた → まず R2 経由の多段ジョブ分割（ADR-0024 決定 5 の逃げ道 + lifecycle 削除）を試し、それでも不足なら基盤を再評価する。

## Consequences

- automation-schedule の backend 分類に github-actions を追加する実装と、Hard Gate 3 の境界規則追従（ADR-0024 の帰結）が実装ツリーの対象になる。
- 002ch はメディア工程 + アップロードが local に残るため、パイプラインは cloud（企画）→ local（Suno）→ local（メディア・公開）となり、cloud 完結するのは 003ch 型の軽量チャンネルのみ。無人化の実証は 003ch が先行する。
- AI 工程と軽量メディア工程が 2,000 分/月を分け合う。1 コレクションの軽量メディアジョブは転送支配で 30〜60 分の見積り。超過時は支出上限 $0 により自動停止し、パイプラインは停止側に倒れる（ADR-0024 の fail-closed と一貫）。
- 軽量レジームでもディスク余裕は約 2.5GB しかなく、尺・ビットレートの増加が切替条件 5 に直結する。
- サブスク OAuth token（長命 credential）が GHA secret に置かれる。トークンのローテーション手順が運用に加わる。
- 月次 canary と検証 issue（`@codex` bot メンション発火）が実装ツリーに含まれる。
- 用語集に軽量レジーム / 重量レジームを追加する（本 PR）。

## Considered Options

- **claude-code-cloud（Claude Code Cloud Job）**: サブスク消費・マネージド環境だが、ランナー定義が製品固有になり、agent CLI 差し替えによる Codex escape が構造的に塞がる。ホスト中立性を優先し不採用。
- **Cloud Run Jobs**: バッチ適性は高い（上限 168h）が、R2 への egress $0.12/GiB（Master.mp4 で約 $1/コレクション）が 0 円原則と衝突し、Cloud Scheduler の at-least-once に対する多重起動防止をアプリ側で実装する必要もある。切替条件 1・2 の第一再評価候補として保持。
- **VPS（Vultr）常駐**: 既存 streaming 資産を流用でき無人要件も cron + flock で完結するが、新規固定費 $10〜24/月が 0 円原則と正面衝突するため不採用。オンデマンド化は apply を叩く外部装置が別途必要になり本末転倒。
- **Codex Cloud を主基盤にする**: 時刻起点トリガの公式経路が存在せず、メディア工程は実行時間・ディスク・CPU が三重に非公表。escape 経路（決定 7）としてのみ採用。
- **コンテナイメージによるランナー定義**: 移植性は最強だが、イメージのビルド・レジストリ管理という新規運用が増える。依存は uv + apt（ffmpeg）で再現でき、スクリプト集約で可搬性は足りるため不採用。
- **外部トリガー補強（Cloud Scheduler → `repository_dispatch`）**: cron の遅延・drop 対策になるが、遅延許容の要件下では複雑さに見合わない。切替条件 3 に送り不採用。

## Related

- ADR-0024（クラウド移譲アーキテクチャの原則 — 本 ADR に要求条件を課す）
- `docs/architecture.md::プロジェクト用語集::クラウド移譲`（軽量レジーム / 重量レジーム）
- Wayfinder 地図 #3293 / 調査 #3294〜#3298（`research/r2-facts` ほか 5 ブランチ）
- `.claude/skills/automation-schedule/SKILL.md`（backend 分類 — 本 ADR が第 5 backend を追加）
- #3300
