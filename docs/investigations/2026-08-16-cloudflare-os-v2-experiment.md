# Cloudflare OS v2 試用調査（#4033）

調査日: 2026-08-16（Asia/Tokyo）
暫定結論: **追加調査**

## 結論

Cloudflare OS v2 は、agent chat UI、Gadget、Gatekeeper の遅延承認をまとめた将来の人間向けフロント候補として有望である。一方、現行の YouTube 制作基盤で Cloudflare OS を制御面や実行 owner に置き換える根拠はまだない。Git を制御面、R2 をデータ面、GitHub Actions と local runner を実行面とする ADR-0024 / ADR-0025 の境界は維持し、Cloudflare OS はそれらを限定 capability 経由で観測・指示・承認する上位 UI としてだけ次回実機評価する。

今回は公式資料・公開ソースで確認できる範囲を検証した。公式デプロイ、agent chat UI、Gadget、Gatekeeper／GitHub OAuth、Workers AI 推論は実行していない。これらは Cloudflare アカウントへのログイン、課金プラン、外部リソース作成、secret 登録、GitHub OAuth 同意、ブラウザ操作を伴うためである。したがって実操作結果は未観測で、採用判断には進まない。

## 調査対象と証跡

| 対象 | 固定した版 | 確認方法 | 結果 |
|---|---|---|---|
| Cloudflare OS | `02377767e684aedcbb12f44025cd6331d08b1b50` | 公式 repository の README／Gatekeeper 実装資料を読み取り | v2 は early access。UI、Gadget、Gatekeeper の設計を確認 |
| Cloudflare OS starter | `93f14dfd68ed1c218d2a7c2168753a6d9b22e145` | 公式 starter の README／customization を読み取り | deploy、認証、resource、AI secret の前提を確認 |
| 既存基盤 | この変更の親 commit | ADR-0024、ADR-0025、architecture を読み取り | 現行 owner と比較 |
| 実行環境 | macOS、空き約 12 GiB | `df -h .` | issue 起票時の約 4.2 GiB より増えているが、外部変更を避ける判断は不変 |

実行した操作は GitHub issue／公開 repository／公式ドキュメントの読み取り、`git ls-remote`、ディスク確認、レポート契約テストだけである。Cloudflare API、Workers AI API、R2、GitHub OAuth、ブラウザ UI、deploy、課金設定は操作していない。

## 公式仕様から確認できたこと

### agent chat UI と Gadget

- Cloudflare OS v2 は agent chat UI、AI が生成する私有 Gadget、Gatekeeper を主要機能とする。ただし 2026-08 公開版は complete rewrite の early access で、公式自身が rough edges を明記している。
- 各 workspace は Durable Object、各 Gadget は Dynamic Worker Facet で動く。Gadget server は既定でインターネット接続を持たず、明示 binding だけを受け取る。client も sandboxed iframe と CSP で制限される。
- `pnpm run-local` は workerd／Wrangler 上の非本番プレビューである。UI を開くだけならローカル起動経路があるが、agent／Gadget 生成の品質評価にはモデル推論が必要であり、今回の無認証・無課金・非対話条件では評価できない。

### Gatekeeper と GitHub resource

- Gatekeeper は外部 API を Cap'n Web API に包み、特定 resource だけを capability として渡し、全操作を記録する。副作用は先に simulation され、後から人間が個別または一括で approve／reject する設計である。
- GitHub 接続には GitHub **OAuth App** が推奨される。sign-in は `read:user user:email` だが、Gadget の connection は `repo read:user user:email` を要求する。`repo` は選択画面の resource scope より広い OAuth grant なので、テスト専用 GitHub account／repository での実測なしに「最小権限」とは判断しない。
- 接続確認には OAuth App 登録、client secret、callback URL、GitHub の同意画面、新規 tab での対話が必要である。今回は作成も同意もしていないため、限定接続と遅延承認の実操作結果は **blocker** として未観測である。

### デプロイ、認証、secret

- hosted one-click flow は利用者の Cloudflare account へデプロイする。再現性を重視する starter は `wrangler login`、account ID、Worker 名、hostname、Cloudflare Access audience、admin email、`pnpm deploy` を要求する。
- starter は Workers、KV、R2、Browser Rendering、Dynamic Worker Loaders を要求する。未指定時は 3 個の KV namespace と 1 個の R2 bucket を自動作成し、複数 Worker を deploy する。
- Cloudflare Access の Free plan でも onboarding と payment details 入力が必要である。Dynamic Workers は Workers Paid plan 限定で、最低料金は月額 $5 である。このため「課金設定を変更せず完全無料で公式 v2 を hosted 試用する」前提は成立しない。
- Workers AI は deploy 自体には任意だが、現行 starter の HTTPS transport で platform-funded catalog を使うには direct mode でも `CF_AI_GATEWAY_API_TOKEN` が必要である。secret は追跡設定や本書に記録してはならない。

## Workers AI の使用量と実費

今回の実測値は次のとおりである。

| 指標 | 実測値 | 根拠 |
|---|---:|---|
| Workers AI request | 0 | API／UI 推論を実行していない |
| Workers AI 使用量 | **0 neurons** | 同上 |
| Workers AI 実費 | **$0.00** | 同上 |
| Worker／Dynamic Worker／Browser Rendering／KV／R2 実費 | **$0.00** | deploy、作成、呼び出しを実行していない |
| 合計実費 | **$0.00** | 月額上限 $5 未満 |

この $0.00 は製品試用の費用ではなく、机上調査の費用である。Cloudflare の 2026-08-16 時点の公開価格では Workers AI は日次 10,000 neurons まで無料枠、超過分は $0.011 / 1,000 neurons だが、一部大型モデルは Workers Paid が必須である。さらに Dynamic Workers 自体が Workers Paid 限定で最低 $5／月のため、issue の「月額 $5 上限」は超過従量を一切発生させない場合にだけ満たせる。実機時は 10,000 neurons／日、Browser Rendering 10 時間／月、Dynamic Worker 1,000 unique／月などの included usage と dashboard 実測を同時に監視する。

Workers AI の Customer Content は他顧客へ提供されず、明示同意なしにモデル学習やサービス改善へ使わないと公式文書にある。ただし prompt／output は Customer Content であり、R2、KV、Durable Objects 等を併用すれば保存され得る。次回も本番チャンネル情報、OAuth token、個人情報を prompt に入れない。

## 既存アーキテクチャとの責務分割

| 要素 | 現行 owner | Cloudflare OS を採用する場合の境界 | 評価 |
|---|---|---|---|
| tayk／MCP | typed workflow／tool 境界 | Gatekeeper は MCP に似るが Cap'n Web API であり、そのまま互換ではない。専用 Gatekeeper が tayk／MCP の狭い command を呼び、OS 内に workflow logic を複製しない | 追加実装と契約試験が必要 |
| Git 制御面 | repository の versioned state | GitHub Gatekeeper は対象 repository の read と、承認待ち mutation だけを仲介する。Cloudflare OS の Durable Object を正本にしない | 遅延承認は有望、OAuth scope は要検証 |
| R2 データ面 | manifest completion marker を伴う media handoff | OS 内部の R2／KV と制作 R2 を分離する。制作 R2 は prefix と manifest 操作を限定した custom Gatekeeper だけを通す | 直接 bucket binding は不可 |
| GitHub Actions | cloud job の single writer | OS は dispatch／進捗表示／承認 UI に限定し、実行 owner と concurrency は GHA に残す | ADR-0025 と両立可能 |
| local runner | 人間 browser、Suno、重い media 処理 | OS は job request と receipt を仲介するだけで、local filesystem や browser session を直接所有しない | 置換ではなく補助 |

Cloudflare OS の「agent／Gadget は既定で何も持たず、resource を明示 introduction する」設計は ADR-0024 の fail-closed 方針と整合する。一方、Gatekeeper の独立配布 lifecycle は公式資料でも未確定で、early access の trust boundary と upstream 変更を継続監査する必要がある。

## 観点別評価

| 観点 | 今回の結果 | 暫定評価 |
|---|---|---|
| agent chat UI の操作感／長時間作業 | 実操作結果は未観測 | browser 実機が必要 |
| Gadget の生成・実行・修正 | 実操作結果は未観測 | Workers AI と Dynamic Workers が必要 |
| Gatekeeper の限定接続／承認 | source 上の capability、simulation、遅延承認を確認 | 設計は適合。副作用が承認前に外部へ出ないことを実測すべき |
| GitHub resource | OAuth App、scope、選択 resource の流れを確認 | `repo` grant と resource-level enforcement の差を実測すべき |
| Workers AI 品質 | 未観測 | task completion、修正反復、token／neuron を同一 rubric で測る必要あり |
| 費用 | 今回 $0.00、product trial は未実施 | Workers Paid 最低 $5 と超過防止策の事前承認が必要 |
| 既存基盤への適合 | owner を変えない UI／approval layer として机上適合 | custom Gatekeeper PoC 前に Wayfinder で境界合意が必要 |

## 未実施の blocker

1. Cloudflare account へのログイン、Workers Paid の契約・支払情報、Cloudflare Access onboarding はアカウント状態と課金を変更する。
2. one-click deploy／`pnpm deploy` は Worker、KV、R2、DNS／route 等を作成する外部変更である。
3. Workers AI direct mode は account ID と API token を必要とし、推論は使用量を発生させる。
4. GitHub Gatekeeper は OAuth App 登録、secret 発行、`repo` scope へのブラウザ同意を必要とする。
5. agent UI、Gadget、遅延承認の評価は browser 実機がなければ成立しない。

これらはユーザーのアカウント、規約同意、課金、外部データへ影響するため、今回変更しなかった。

## 最後にまとめて行う実機確認手順

1. Wayfinder で「Cloudflare OS は UI／approval layer、Git／R2／GHA／local runner は既存 owner」と確認し、実験専用 Cloudflare account、専用 `workers.dev` route、空の GitHub test repository、使い捨て admin email を用意する。本番 secret と本番 channel data は使わない。
2. Workers Paid の最低 $5、Workers AI 超過、Dynamic Workers、Browser Rendering の価格と規約を人間が再確認する。月額上限を $5 とするなら、Paid 基本料金以外の従量を $0 に保つ停止条件を合意する。
3. 公式 starter を commit pin し、`deployment.jsonc` は `workersDev: true`、AI 無効、Artifacts 無効、狭い admin allowlist で `pnpm check` する。`pnpm deploy` の計画対象を確認してから明示承認し、作成された Worker、3 KV、R2 を記録する。
4. `/admin` と agent chat UI を開き、sign-in、workspace 作成、長い指示、再開性を確認する。secret や個人情報は入力しない。
5. Workers AI は `cloudflare` provider の direct modeだけを有効にし、token を `wrangler secret put` の標準入力で登録する。Free 対象の小型モデル、短い固定 prompt、最大 3 セッションから始め、各回の input／output tokens、neurons、latency、task success、修正回数を dashboard と receipt に記録する。10,000 neurons／日または見積 $0.00 超過前に停止する。
6. Gadget は「静的チェックリスト」「読み取り専用集計」の 2 件だけ生成し、server の外部通信不可、client CSP、修正反復、再読み込み後の状態を確認する。Browser Rendering は使わない課題を選ぶ。
7. GitHub OAuth App を test repository 用に作成し、callback を実験 host に限定する。connection の `repo read:user user:email` grant を確認後、対象 test repository だけを UI で紹介する。read を確認し、最初の write は reject、次の write は approve して、承認前に GitHub 側へ副作用がないこと、監査 log と simulation が一致することを確認する。
8. tayk／MCP、Git、R2、local runner の各ユースケースを「観測」「指示」「副作用」「承認」「owner」で採点し、採用／不採用／追加調査を Wayfinder で決める。採用でも本 issue では統合しない。
9. 終了時に OAuth App／token を revoke し、実験 Worker、KV、R2、Access application、route を列挙して削除する。dashboard で最終 neurons と請求見込みを確認し、secret を含まない証跡だけを追記する。

## 参照した一次資料

- [Cloudflare OS README](https://github.com/cloudflare/cloudflare-os/blob/main/README.md)
- [Cloudflare OS GitHub Gatekeeper](https://github.com/cloudflare/cloudflare-os/blob/main/packages/gatekeeper-github/README.md)
- [Cloudflare OS starter README](https://github.com/cloudflare/cloudflare-os-starter/blob/main/README.md)
- [Cloudflare OS starter customization](https://github.com/cloudflare/cloudflare-os-starter/blob/main/docs/customization.md)
- [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Workers AI data usage](https://developers.cloudflare.com/workers-ai/platform/data-usage/)
- [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
- [Dynamic Workers pricing](https://developers.cloudflare.com/dynamic-workers/pricing/)
- [Browser Run pricing](https://developers.cloudflare.com/browser-run/pricing/)
- [Cloudflare One setup](https://developers.cloudflare.com/cloudflare-one/setup/)
- [ADR-0024: Cloud migration principles](../adr/0024-cloud-migration-principles.md)
- [ADR-0025: Execution platform selection](../adr/0025-execution-platform-selection.md)

価格、plan 条件、early-access の仕様、OAuth scope は変更され得る。実機確認開始時に必ず公式資料を再確認する。
