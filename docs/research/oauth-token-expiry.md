# OAuth refresh token 頻繁失効の根本原因調査

- 調査日: 2026-08-29（#4716、地図 #4714）
- 対象: `auth/token.json` ほか用途別 YouTube OAuth token（`token.readonly.json` / `token_streaming.json`）の refresh token が頻繁に失効する事象
- 結論: **最有力原因は「OAuth 同意画面の Publishing status が Testing のまま」であることによる Google 仕様の 7 日失効**。本リポジトリの `docs/oauth-setup.md` 自体が「Testing のまま保存」と指示しており、構造的に全チャンネルが該当する
- 未実施: GCP 上の現在ステータスの実測（Console 確認が必要 — 後述）、失効発生日時と token ファイルの突き合わせ

## 要約

Google の公式仕様では、External user type かつ Publishing status = **Testing** の同意画面を持つプロジェクトが発行する refresh token は **7 日で失効する**。本リポジトリのセットアップ正本（`docs/oauth-setup.md`「Audience で User type は External、Publishing status は Testing のまま保存」）はまさにこの構成を指示しているため、全下流チャンネルの token が仕様どおり毎週失効していると考えるのが最も整合的である。

対策として In production 化すると 7 日失効は解消するが、本リポジトリの scope（YouTube Data / Analytics）は **sensitive 分類**のため「verification が必要」という警告が出る。ただし **restricted ではない**ので年次 security assessment は不要であり、個人利用（開発者本人のみが認証する）なら verification 自体が任意 — 未審査のまま In production にしても「unverified app 警告画面 + 生涯 100 新規ユーザー上限」だけが残り、運用者本人 1 アカウントで使う本リポジトリの用途では実害がない。**ただし Testing 中に発行済みの既存 token は 7 日失効のまま**なので、In production 化後にチャンネルごと・token ファイルごとに 1 回だけ再認証が必要になる。

7 日失効以外の失効条件（6 ヶ月未使用、client あたり 100 token 上限、パスワード変更、revoke 等）はいずれも本リポジトリの運用（ADR-0024 の ephemeral 持ち出し含む）では成立しにくく、頻繁失効の説明にならない。

## 症状と第一仮説

- 症状: `auth/token.json` の refresh token が頻繁に失効し、`uv run yt-oauth` によるブラウザ再認証が繰り返し必要になる（refresh 失敗時は `infrastructure/auth/youtube.py::authenticate()` が warning を出して新規ブラウザ認証へフォールスルーする実装）
- 第一仮説（#4716）: 同意画面が Testing ステータスのままで、Google 仕様により refresh token が 7 日で強制失効している → **本調査は仮説を支持**

### 仮説を支持する根拠

1. Google 公式の失効条件に次の明記がある:
   > "A Google Cloud Platform project with an OAuth consent screen configured for an external user type and a publishing status of 'Testing' is issued a refresh token expiring in 7 days"
   （[OAuth 2.0 の Refresh token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)）
2. Google Auth Platform ヘルプにも「Test user の authorization は同意から 7 日で失効し、offline access で得た refresh token も同様に失効する」とある（[Manage App Audience](https://support.google.com/cloud/answer/15549945)）。例外は `userinfo.email` / `userinfo.profile` / `openid` のみを要求する場合だが、本リポジトリの scope は該当しない
3. 本リポジトリのセットアップ正本が Testing 構成を明示的に指示している:
   - `docs/oauth-setup.md`: 「**Audience** で User type は **External**、Publishing status は **Testing** のまま保存し、**Test users** に OAuth 認証でログインする Google アカウントを追加」
   - `ONBOARDING.md` 経由の `/setup --tool` HUMAN STEP も同一（「Audience は External / Testing とし…」）
   - つまり手順どおりに構築された全チャンネルの GCP project が 7 日失効の対象構成になる
4. 失効の周期性（「頻繁」= 概ね週次でどの token も切れる）は他の失効条件では説明できない（後述の網羅表参照）

## 本リポジトリの scope と sensitive / restricted 分類

scope の単一ソースは `src/youtube_automation/infrastructure/auth/youtube.py` の `SCOPES` / `READONLY_SCOPES`（対応表は `docs/oauth-scopes.md`）。

| token ファイル | scope | 分類 |
|---|---|---|
| `auth/token.json` | `youtube` / `youtube.force-ssl` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | sensitive |
| `auth/token.readonly.json` | `youtube.readonly` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | sensitive |
| `auth/token_streaming.json` | `youtube` | sensitive |

分類の根拠:

- Google は sensitive scope の例として「deleting a YouTube video」を明示しており、YouTube Data / Analytics 系 scope は sensitive 扱い（[Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)）
- **restricted scope の現行リスト**（Gmail / Drive / Google Fit / Google Chat / Data Portability / Photos Ambient / Google Health）に YouTube Data / Analytics の上記 scope は**含まれない**（[Restricted Scopes](https://support.google.com/cloud/answer/13464325)。Data Portability API に YouTube 関連の restricted scope があるが、本リポジトリは使用していない）
- restricted に該当しないため、restricted 専用の追加要件（年次 **security assessment**）は不要（[Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)、[Security Assessment](https://support.google.com/cloud/answer/13465431)）

## 現在の Publishing status を CLI / API で読めるか

**読めない — Console 確認が必要。**

- Google Auth Platform（旧 OAuth consent screen）の Branding / Audience / Clients は GUI 専用で、公開 API・gcloud・Terraform のいずれからも読み書きできない。これは本リポジトリの正本にも明記済み（`docs/oauth-setup.md`「Google Auth Platform の GUI は API で自動化できないため」「`gcloud` / Terraform いずれも…対応していない」）。地図 #4714 の wizard 責務（IaC 化不可能ステップの案内）とも整合する
- `gcloud iap oauth-brands describe` で読めるのは IAP 用 brand（`orgInternalOnly` フィールド）だけで、External / Testing / In production の Publishing status は公開 API に露出していない
- なお本セッションはツールキット環境の不具合（worktree の venv 未構築による hook ブロック）でコマンド実行自体ができなかったため、実測でも未確認。**確定には Console の Google Auth Platform > Audience で Publishing status を目視確認する**（チャンネルごとの GCP project 単位）

## In production 化の副作用一覧

「Publish app」ボタンで Testing → In production に切り替えた場合（[Manage App Audience](https://support.google.com/cloud/answer/15549945)）:

| # | 副作用 | 影響評価（本リポジトリの個人利用前提） |
|---|---|---|
| 1 | **7 日失効が解消**（refresh token は revoke / 6 ヶ月未使用等がない限り存続） | 目的そのもの。VPS 無人運用（ADR-0024/0025 のクラウド移譲）とも整合 |
| 2 | **既存 token は救済されない**: Testing 中に発行された refresh token は 7 日失効のまま。切替後に再認証して新 token を得る必要がある | チャンネルごと・token ファイルごと（token.json / token.readonly.json / token_streaming.json）に 1 回ずつ `uv run yt-oauth` 等の再認証が必要（出典: [Google Ads API チーム回答](https://groups.google.com/g/adwords-api/c/Z_kihrf6VCE)。一次ドキュメントに明文はないため、切替後の初回失効時に再認証、でも実害はない） |
| 3 | **sensitive scope のため verification を促される**が、未審査のまま In production にできる。個人利用（「you are the only user of your app or if your app is used by only a few users, all of whom are known personally to you」）は verification 任意（[Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)） | 審査（scope 正当性説明 + デモ動画 + ホームページ / プライバシーポリシー）は不要。放置してよい |
| 4 | 未審査のまま運用すると、新規の同意時に **unverified app 警告画面**が表示される（[Unverified apps](https://support.google.com/cloud/answer/7454865)） | 認証するのは運用者本人のみ。警告画面から続行すればよく実害なし |
| 5 | 未審査アプリには **生涯 100 新規ユーザー上限**（unverified app 画面を提示した後の新規許可アカウント数。リセット不可）（[Manage App Audience](https://support.google.com/cloud/answer/15549945)、[Unverified apps](https://support.google.com/cloud/answer/7454865)） | 認証アカウントは運用者の 1〜数個で、チャンネル追加もプロジェクト単位（client 単位）なので上限に達しない |
| 6 | restricted scope ではないため **security assessment（年次・有償）は発生しない** | 影響なし |
| 7 | Test users リストの管理が不要になる（Testing 限定の概念） | `docs/oauth-setup.md` / `ONBOARDING.md` / setup skill の HUMAN STEP 文言・トラブルシューティング（`403 access_denied` 対処）の更新が必要になる |

## 7 日失効以外の失効原因の網羅と評価

[OAuth 2.0 の Refresh token expiration](https://developers.google.com/identity/protocols/oauth2#expiration) に列挙された全条件と、本リポジトリ運用への該当性:

| 失効条件 | 本リポジトリでの該当性 |
|---|---|
| Testing ステータス（7 日） | **該当（最有力）**。上述 |
| ユーザーによる revoke | 手動操作なので「頻繁失効」の説明にならない |
| **6 ヶ月未使用** | 非該当。analytics / 配信 daemon が定常的に refresh しており、ADR-0024 の ephemeral 持ち出し（VPS 側でも同じ refresh token を使用）はむしろ「使用実績」を増やす方向 |
| **token 上限**: 1 Google アカウント × 1 OAuth client あたり **100 refresh token**（超過時は最古の token が警告なしで無効化）。※issue #4716 記載の「50 個」は旧仕様で、現行ドキュメントは 100 | 非該当。client（= チャンネル別 GCP project）あたりの live token は用途別 3 ファイル + 再認証の積み残し程度で 100 に遠く及ばない。仮に達しても失効するのは最古のみ |
| **パスワード変更**: 「refresh token が **Gmail scope を含む**場合」のみ | 非該当。本リポジトリは Gmail scope を使用しない |
| 時間制限付きアクセス（time-based access）の期限切れ | 非該当（EU 圏の一部同意 UI の話で、恒常的な週次失効を説明しない） |
| Workspace 管理者が対象サービスを Restricted に設定 / Google Cloud session length 超過 | 通常非該当。ただし OAuth に使う Google アカウントが Workspace 管理下（例: `allsmile.co.jp`）の場合のみ、管理コンソールのポリシーが token を落とし得る。Console 確認時に、認証アカウントが個人アカウントか Workspace アカウントかも併せて記録しておくとよい |

### ADR-0024（ephemeral 持ち出し）との関係

- ADR-0024 は token を VPS / クラウドへ **ephemeral（`YOUTUBE_OAUTH_TOKEN_JSON` 環境変数、ディスク非永続）** に持ち出す方針。実装は `infrastructure/auth/youtube.py::_load_secret_credentials()`（refresh 後も永続化しない）
- Google の refresh token は使用時にローテーションされないため、**ローカルと VPS が同一 refresh token を並行使用しても相互失効は起きない**（失効条件のどれにも該当しない）。access token の refresh は token ごとに独立
- よって ephemeral 持ち出しは上表のどの失効条件にも触れない。逆に Testing の 7 日失効は VPS 側の無人運用を毎週壊すため、クラウド移譲を進めるほど In production 化の必要性が増す

## 結論

1. **最も可能性の高い原因**: 同意画面 Publishing status = Testing による Google 仕様の 7 日失効。セットアップ正本自体が Testing 構成を指示しているため、全チャンネルが構造的に該当する。確定には Console（Google Auth Platform > Audience）での目視確認のみが必要（API では読めない）
2. **In production 化の副作用**: 上の一覧のとおり。個人利用では「unverified 警告画面から続行する一手間」「既存 token の再認証 1 回」「ドキュメント / setup skill の文言更新」だけで、審査・security assessment・ユーザー上限の実害はない
3. 対策の選択（In production 化するか、7 日ごと再認証を自動化で緩和するか等）は #4717（grilling)で決定する。本調査は事実確定まで

## 出典

- Refresh token の失効条件・Testing 7 日失効・100 token 上限: https://developers.google.com/identity/protocols/oauth2#expiration
- Publishing status（Testing の test user 100 人上限・7 日失効・Publish app・unverified 時の生涯 100 ユーザー上限）: https://support.google.com/cloud/answer/15549945
- Sensitive scope の定義（YouTube 動画削除が例示）と personal use の verification 例外: https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- Restricted scope の現行リスト（YouTube Data / Analytics は非該当）: https://support.google.com/cloud/answer/13464325
- Restricted scope の追加要件（security assessment）: https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification / https://support.google.com/cloud/answer/13465431
- Unverified apps の警告画面と 100 新規ユーザー上限: https://support.google.com/cloud/answer/7454865
- Testing 中発行 token は production 切替後も失効し再認証が必要（Google Ads API チームのフォーラム回答 — 準一次情報）: https://groups.google.com/g/adwords-api/c/Z_kihrf6VCE
- リポジトリ側: `docs/oauth-setup.md`（Testing 指示・GUI 非自動化）、`docs/oauth-scopes.md`（scope 対応表）、`src/youtube_automation/infrastructure/auth/youtube.py`（SCOPES / ephemeral 実装）、`docs/adr/0024-cloud-migration-principles.md`（ephemeral 持ち出し決定）
