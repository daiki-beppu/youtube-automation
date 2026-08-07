# platform research: GitHub Actions

Issue: #3296（親: #3293「ADR: 実行基盤の選定」の入力）
調査日: 2026-08-07
調査方法: 一次情報のみ（docs.github.com / developers.cloudflare.com / code.claude.com / developers.openai.com）。二次記事は参照していない。数値はすべて調査日時点の公式ドキュメント記載値。

## 結論（要旨）

- **軽量レジーム（静止画ループ）の週次〜日次制作ランには適する**。Linux standard runner は $0.006/分と安価で、private repo でも Free プランの無料枠 2,000 分/月でかなりの部分が収まる。転送費は GitHub 側・R2 側ともゼロ。
- **最大の制約は standard runner のディスク 14 GB SSD**。9.7 GB 級の中間物 + 入力音源数 GB + 出力動画数 GB は収まらない公算が大きい。75 GB 以上のディスクを持つ larger runner は **organization の Team / Enterprise Cloud プラン限定**で、個人アカウントの private repo からは使えない。ここが重量レジームの構造的ブロッカー。
- schedule cron は「その時刻に必ず走る」保証がない（遅延・drop が公式に明記）。日次制作ランには許容範囲で、多重起動は concurrency group で機械担保できる。
- secret 面は GCP（Vertex AI）が OIDC で鍵レス化できる一方、**R2 は OIDC 非対応**で静的 Access Key を Actions secret に置く必要がある。
- AI エージェント実行は Claude Code（`anthropics/claude-code-action@v1`）・Codex（`openai/codex-action@v1` + `codex exec`）ともに**ベンダー公式の GitHub Actions 統合が存在する**。skill 呼び出し・schedule 実行・Vertex AI 経由の OIDC 認証まで公式にカバーされており、本プロジェクトの skill 駆動制作との親和性は高い。
- 撤退コストは低い。処理本体を CLI + コンテナに寄せれば workflow YAML は薄い glue に留まり、中間物受け渡しを R2 に寄せれば artifact/cache への依存も避けられる。

---

## 共通評価軸

### 1. 料金体系と無料枠

**事実**

- private repo の無料枠（月次）: Free 2,000 分 / Pro 3,000 分 / Team 3,000 分 / Enterprise Cloud 50,000 分。artifact ストレージは Free 500 MB / Pro 1 GB / Team 2 GB / Enterprise 50 GB。public repo の standard runner は無料。
  出典: <https://docs.github.com/en/billing/concepts/product-billing/github-actions>
- 分単価（standard runner）: Linux 2-core x64 $0.006 / Linux 2-core arm64 $0.005 / Windows 2-core $0.010 / macOS 3–4 core $0.062。1-core の `ubuntu-slim` は $0.002。larger runner は Linux x64 4-core $0.012、8-core $0.022、16-core $0.042 など段階制。
  出典: <https://docs.github.com/en/billing/reference/actions-minute-multipliers>
- 無料枠の消費レートは OS で異なる（Windows は Linux の 2 倍、macOS は 10 倍で included minutes を消費する minute multiplier）。larger runner には無料枠を充当できない（"Included minutes cannot be used for larger runners" / "The larger runners are not free for public repositories"）。
  出典: <https://docs.github.com/en/billing/reference/actions-minute-multipliers>, <https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions>
- self-hosted runner は Actions 利用として無料（"Are free to use with GitHub Actions, but you are responsible for the cost of maintaining your runner machines."）。
  出典: <https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners>
- 課金項目は「分」と「ストレージ（artifact / cache / カスタムイメージ）」のみで、**データ転送量への課金項目は billing ドキュメントに存在しない**。
  出典: <https://docs.github.com/en/billing/concepts/product-billing/github-actions>

**本プロジェクトへの含意**

- 実行は Linux 一択（macOS は単価 10 倍かつ無料枠消費 10 倍で、ffmpeg バッチに選ぶ理由がない）。
- 粗い試算: 軽量レジームで 1 ラン 30〜90 分（2-core Linux）とすると、週次なら月 120〜360 分で Free 枠内。日次でも月 900〜2,700 分で、超過してもたかだか $0.006/分 ≒ 月数ドル。重量レジームで 1 ラン 3〜6 時間 × 日次でも超過分は月 $20〜$55 程度で、**計算資源のコストは意思決定の主要因にならない**。
- 効くのは分単価ではなくディスク（軸 3）と larger runner のプラン制約。

### 2. 実行時間上限

**事実**

- job の実行時間上限: GitHub-hosted runner で **6 時間**、self-hosted runner で **5 日**。
- workflow run 全体の上限: **35 日**（実行・待機・承認を含む）。
- self-hosted の job がキューに残れるのは 24 時間まで。workflow trigger は 1,500 events / 10 秒 / repo。
  出典: <https://docs.github.com/en/actions/reference/limits>

**本プロジェクトへの含意**

- 軽量レジーム（数分〜数十分）には余裕。重量レジーム（エフェクト・スペクトラム描画で大幅増）が 2-core で 6 時間を超えるなら、job 分割（曲単位・disc 単位）か self-hosted 化が必要。分割時の中間物受け渡しは artifact ではなく R2 を使う（軸 3・固有論点 3 参照）。

### 3. 一時ディスク容量と IO

**事実**

- standard runner（private repo）: Linux x64 2 vCPU / RAM 8 GB / **SSD 14 GB**。public repo だと 4 vCPU / 16 GB / SSD 14 GB。macOS も SSD 14 GB。
  出典: <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
- larger runner: Linux/Windows で 2 vCPU / 8 GB / 75 GB から 96 vCPU / 384 GB / 2,040 GB SSD まで。GPU runner（4 vCPU / Tesla T4 / SSD 176 GB）もある。
  出典: <https://docs.github.com/en/actions/reference/runners/larger-runners>
- larger runner は **organization / enterprise の Team または Enterprise Cloud プラン限定**（個人アカウントでは使えない）。
  出典: <https://docs.github.com/en/actions/concepts/runners/larger-runners>（"GitHub-hosted larger runners are only available for organizations and enterprises using the GitHub Team or GitHub Enterprise Cloud plans"）
- IO 性能（SSD スループット・IOPS）の公表値はドキュメントに存在しない。

**本プロジェクトへの含意**

- **ここが最大の適性境界**。「入力音源数 GB pull + 9.7 GB 級中間物 + 出力数 GB」は 14 GB に収まらない。軽量レジームでも、中間物を作った端から消す・R2 からのストリーム処理にする等のディスク節約設計が前提になる。
- 重量レジームを hosted runner で回すには larger runner（75 GB〜）が事実上必須だが、それには organization + Team プラン（有償）への移行が要る。個人アカウント運用のままなら **重量レジームは self-hosted runner か別基盤**に逃がすのが自然。

### 4. R2 との転送

**事実**

- R2 の egress（データ転送）は **無料**（S3 API / Workers API / r2.dev 経由の直接 egress が対象）。ストレージ $0.015/GB-月、Class A $4.50/100 万リクエスト、Class B $0.36/100 万リクエスト。無料枠: ストレージ 10 GB-月、Class A 100 万 / Class B 1,000 万リクエスト/月。
  出典: <https://developers.cloudflare.com/r2/pricing/>
- GitHub 側にもデータ転送への課金項目はない（軸 1 参照）。
- hosted runner のネットワーク帯域の公表値はない（self-hosted の最低要件として 70 kbps という記述があるのみで、hosted 側の保証値は非公表）。
  出典: <https://docs.github.com/en/actions/using-github-hosted-runners/using-github-hosted-runners/about-github-hosted-runners>

**本プロジェクトへの含意**

- **音源 pull 数百 MB〜数 GB / 動画 push 数 GB のどちらにも転送費は一切かからない**。R2 を挟む設計と Actions は費用面で最も相性が良い組み合わせ。
- 転送コストは「分課金に乗る転送時間」のみ。帯域は非公表なので、採用判断の前に実測（数 GB の pull/push で何分かかるか）を 1 本走らせて確かめるのが妥当。

### 5. CPU 性能と ffmpeg 適性

**事実**

- private repo の standard Linux runner は 2 vCPU / 8 GB RAM（x64・arm64 とも）。public repo は 4 vCPU / 16 GB。
  出典: <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
- CPU の世代・クロック等の絶対性能はドキュメントで保証されていない。より多くのコアが必要なら larger runner（最大 96 vCPU、ただしプラン制約は軸 3 のとおり）。
  出典: <https://docs.github.com/en/actions/reference/runners/larger-runners>

**本プロジェクトへの含意**

- 軽量レジーム（静止画ループ 2 時間尺、ローカルで 1〜2 分）は入力静止画 + 音声の再エンコードが主で並列度への依存が小さく、2 vCPU でも数倍以内の時間で収まる見込み。分課金的にも問題にならない。
- 重量レジーム（フィルタグラフ・オーディオスペクトラム）は CPU バウンドで、2 vCPU では実時間の数倍〜十数倍に伸びるリスクがある。6 時間上限（軸 2）と合わせ、hosted standard runner での重量レジームは「動くが遅い」領域。arm64 runner（$0.005/分）は ffmpeg が arm64 ネイティブで動くため、コスト最適化の選択肢になる。
- 性能の公表値がない以上、レジームごとの実測ベンチ（同一入力でローカル Mac と runner の所要時間比較）を ADR の前提データにすべき。

### 6. スケジュール実行

**事実**

- `schedule:`（cron）の最短間隔は 5 分。**遅延と drop が公式に明記されている**: "The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour. If the load is sufficiently high enough, some queued jobs may be dropped."
- public repo では 60 日間リポジトリ活動がないと scheduled workflow が自動無効化される（private repo への言及はない）。scheduled workflow は default branch の最新 commit でのみ走る。
  出典: <https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows>
- concurrency group で多重起動を防げる。既定では group 内の pending は 1 つだけで、新しい run が来ると既存 pending はキャンセルされ置き換わる。`cancel-in-progress: true` で実行中もキャンセル可能。
  出典: <https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs>

**本プロジェクトへの含意**

- 「毎時 0 分」を避けた cron（例: `17 3 * * *`）にするのが公式ドキュメントから直接導ける運用。分単位の正確さは保証されないが、日次制作ランに求める精度としては十分。
- **drop があり得る**前提の設計が必要: 次回 run が未処理分を拾う冪等な状態駆動（既存の `/wf-auto` の再開設計と同型）にしておけば、1 回の drop は自然に吸収できる。手動 `workflow_dispatch` を併設して取りこぼしを即時回収できるようにする。
- 多重起動防止は concurrency group 1 行で機械担保でき、cron 二重発火・手動と定期の衝突の双方に効く。この点は cron を自前運用する VPS より優位。

### 7. secret 管理

**事実**

- secrets は repository / environment / organization の 3 レベル。48 KB を超える値は直接格納できない（暗号化ファイルで回避する公式手順あり）。ログには自動マスクされる。
  出典: <https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions>
- OIDC により長期クレデンシャルを GitHub に保存せず、クラウド側から短期トークンを直接取得できる（"No cloud secrets: You won't need to duplicate your cloud credentials as long-lived GitHub secrets"）。
  出典: <https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect>
- GCP は Workload Identity Federation + `google-github-actions/auth` で OIDC 連携でき、サービスアカウントキー不要。workflow 側は `permissions: id-token: write` を付ける。
  出典: <https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-google-cloud-platform>
- **R2 に OIDC federation はない**。S3 互換 API の認証は API token 由来の Access Key ID / Secret Access Key。短命の temporary credentials API はあるが、それを発行するために親 API token が必要（静的 secret ゼロにはならない）。
  出典: <https://developers.cloudflare.com/r2/api/tokens/>

**本プロジェクトへの含意**

- 本リポジトリのシークレット解決順（`os.environ` → `op read`）とは Actions secrets → 環境変数注入がそのまま接続でき、`infrastructure/secrets.py` の変更は不要（env が先に解決される）。
- Vertex AI（AI 系）は OIDC で鍵レス化でき、現行の「ADC 認証のため op 取得不要」という整理と一貫する。
- R2 だけは静的キーを Actions secret に置くことになる。bucket 単位・権限最小の token を切り、必要なら temporary credentials で job 内スコープを絞るのが現実解。YouTube OAuth の `token.json` も secret（48 KB 制限内）として注入することになり、リフレッシュ後の書き戻し先を R2 等に設計する必要がある点は ADR で扱うべき論点。

### 8. コンテナ可搬性

**事実**

- container job（`jobs.<job_id>.container`）で任意の Docker イメージを job の実行環境にできる。イメージは Docker Hub でも任意 registry でもよく、`credentials` で `docker login` 相当の認証を渡せる。`--network` と `--entrypoint` オプションは非対応。Docker コンテナアクションを使う場合は Linux マシンが必須。
  出典: <https://docs.github.com/en/actions/using-jobs/running-jobs-in-a-container>, <https://docs.github.com/en/actions/reference/runners/self-hosted-runners>

**本プロジェクトへの含意**

- ffmpeg・uv・本パッケージを焼いたイメージを 1 つ作れば、hosted / self-hosted / 他基盤（Cloud Run・VPS 等）で同一環境を再現できる。**処理本体をイメージ + `yt-*` CLI に閉じ込めるほど、Actions は「cron + secret 配布 + ログ UI」だけの薄い層になり、撤退容易性（軸 10）が上がる**。

### 9. AI エージェント実行適性

**事実**

- Claude Code は公式 GitHub Action `anthropics/claude-code-action@v1` を提供。`prompt` 入力を与える automation mode で `schedule` を含む任意イベントから headless 実行でき、`prompt` には `.claude/skills/` の **skill 呼び出し（`/skill-name`）をそのまま渡せる**。認証は `ANTHROPIC_API_KEY` または `CLAUDE_CODE_OAUTH_TOKEN` を secrets で渡すほか、OIDC ベースの workload identity federation（`anthropic_federation_rule_id` 等）で静的キーなし運用も可能。`use_vertex: "true"` で Vertex AI 経由にでき、その場合も OIDC 認証。コスト管理として `--max-turns`・workflow timeout・concurrency 制御が公式に推奨されている。
  出典: <https://code.claude.com/docs/en/github-actions>
- Codex は公式 Action `openai/codex-action@v1` があり、CI では `codex exec`（non-interactive mode）を実行する。
  出典: <https://developers.openai.com/codex/github-action>, <https://developers.openai.com/codex/noninteractive>

**本プロジェクトへの含意**

- 本プロジェクトの制作は skill 駆動（`/wf-auto` 等）なので、「checkout した下流 repo + `claude-code-action` の automation mode + `prompt: "/wf-auto"`」という構成が公式サポートの範囲内で成立する。エージェントの長考も job 6 時間上限に対して通常は十分。
- schedule 実行時のトリガー actor はボット扱いになり得るため `allowed_bots` の考慮が要る、CI を Claude の commit で回すには `GITHUB_TOKEN` ではなく App token を使う、など運用上の注意も公式 docs に明記済みで、未知のハックに頼る必要がない。
- API キー消費は GitHub の分課金と独立に発生する。subscription の OAuth token 認証も公式サポートされている点は個人運用でのコスト面で有利。

### 10. ベンダーロックイン度

**事実**

- workflow YAML（`on:` / `jobs:` / `runs-on:` 等）は GitHub Actions 固有の文法。
  出典: <https://docs.github.com/en/actions/writing-workflows>
- artifact / cache は GitHub 固有の仕組みで、保存量は課金対象（軸 1）。cache はリポジトリあたり既定 10 GB・7 日未アクセスで削除。
  出典: <https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/caching-dependencies-to-speed-up-workflows>
- self-hosted runner を使えば実行環境だけを自前ホストへ差し替えられる（YAML・secret・スケジューラは GitHub 側のまま）。
  出典: <https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners>

**本プロジェクトへの含意**

- ロックインの実体は YAML 文法と artifact/cache だが、後者は本プロジェクトでは R2 に寄せるため依存しない。処理本体が `yt-*` CLI + コンテナに閉じている限り、撤退コストは「cron 定義と secret の移設 + YAML の書き換え」程度で低い。
- 段階的な移行パスが両方向にある（hosted → self-hosted → 別基盤）。「まず Actions で始めて、重量レジームだけ self-hosted に逃がす」という漸進が可能なのは選定上の利点。

---

## この基盤に固有の論点

### リポジトリ構成との関係

- 実行場所は**下流チャンネル repo（private）が自然**。`config/channel/*.json`・collection 状態・sync 済み skill がそこに揃っており、checkout だけで制作コンテキストが再現できる。workflow YAML も下流 repo の `.github/workflows/` に置くことになる（`yt-skills sync` の配布対象に含めるかは ADR / 実装 issue の論点）。
- 「メディアは Git 管理外」という制約とは**両立する**。runner のワークスペースは ephemeral なローカルディスクであり、音源は R2 から pull → 処理 → 成果物を R2 / YouTube へ push、で Git には何も入らない。artifact ストレージ（Free 500 MB）に中間物を置く設計はそもそも容量的に不可能なので、「中間物も R2」という現行方針がそのまま強制される形になり、むしろ整合的。
- private repo なので実行分数は無料枠を消費する（public 化して standard runner を無料にする道は、コンテンツ戦略上の理由がない限り選択肢にならない）。

### self-hosted runner という選択肢

- 位置づけ: **「スケジューラ・secret 配布・ログ UI・workflow 定義は GitHub に任せ、計算資源（CPU・ディスク）だけ自前」**というハイブリッド。分課金ゼロ・job 上限 5 日・ディスクはマシン依存なので、軸 2・3・5 の制約（6 時間・14 GB・2 vCPU）が一挙に外れる。重量レジームや 9.7 GB 級中間物と最も相性が良い Actions 内の解。
- ローカル Mac を runner 化する場合は常時稼働とスリープ運用の両立が、VPS を runner 化する場合は VPS 維持費がそれぞれ論点（VPS 自体の評価は VPS research に委ねる。ここでは「VPS を選ぶ場合でも cron / secret / ログを自前実装せず Actions の制御面だけ借りる構成があり得る」という接続のみ指摘する）。
- セキュリティ: 公式が "Self-hosted runners should almost never be used for public repositories" と警告している（fork PR からの任意コード実行で環境が侵害され得るため）。本件は private repo 前提なのでこのリスクは限定的だが、runner マシンに置く R2 キー等の到達範囲は設計時に意識する。
  出典: <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions>

### artifact / cache と R2 の住み分け

- artifact: private repo の無料枠は Free 500 MB、超過 $0.25/GB-月。**数 GB 級の中間物受け渡しには容量・単価とも不適**（R2 は $0.015/GB-月 + egress 無料）。job 間受け渡しが必要な場合も R2 経由にする。
  出典: <https://docs.github.com/en/billing/concepts/product-billing/github-actions>
- cache: リポジトリあたり既定 10 GB・7 日未アクセスで evict・容量超過時は古い順に削除。**依存関係（uv / pip 等）のキャッシュ専用**と割り切り、メディアを置かない。
  出典: <https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/caching-dependencies-to-speed-up-workflows>
- 整理: 「永続・大容量・run 横断 = R2」「run 内の使い捨て = runner ローカルディスク」「依存キャッシュ = Actions cache」「artifact = ログ・小さな成果物レポートのみ」。

## ADR への持ち込み事項（このドキュメントの範囲外だが調査から直接導かれるもの)

1. 軽量レジームは hosted standard runner（Linux 2-core）で成立見込み。ただし採用前に (a) 数 GB の R2 pull/push 所要時間 (b) 代表的な 1 ラン のエンコード所要時間、の 2 点を実測する 1 本の検証 workflow を先に走らせる。
2. 重量レジームは「organization + Team プランで larger runner」か「self-hosted runner」の二択。個人アカウント + hosted のままでは成立しない。
3. R2 静的キーと YouTube OAuth token の保管・ローテーション設計（Actions secrets の 48 KB 制限内・書き戻し経路）を ADR の必須論点にする。
