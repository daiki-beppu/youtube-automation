# アーキテクチャ詳細

CLAUDE.md の「アーキテクチャ」節の詳細版。要点は CLAUDE.md を参照。

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く。

## プロジェクト用語集

`CONTEXT.md` から移管した、本プロジェクト固有の用語と決定の正本。実装詳細ではなく、設計・運用・移行時に使う語彙を定義する。

### 配布・移行

**tayk**: cutover 後に公開する予定のブランド、npm package 名、bin 名。現行 Python 版の canonical CLI は `yt-*` であり、cutover 後の起動方式として `bunx tayk <cmd>` を計画している。

**cutover**: first-party 下流の日常運用が tayk のみで回るようになり、Python 版のメンテナンスを終了するイベント。tayk のリリース単位とは独立した判断であり、同一リポジトリ内の big-bang merge ではない。

**dogfood**: cutover 前に first-party 2 リポジトリで各コレクション 1 本のフルライフサイクルを実走させる受け入れ検証。期間ではなく完走で判定する。

**critical regression**: cutover をブロックする欠陥。誤公開・誤メタデータ、analytics 履歴または collection 成果物のデータ破壊、auth 破壊の 3 種に限る。

**first-party**: 運営者自身が保有するチャンネルリポジトリ。dogfood の対象であり、第三者 consumer が存在しないことを意味しない。

**external user**: `uv add git+https://` で Python 版を導入し skills 経由で運用する第三者コミュニティ。first-party ではないため dogfood 対象外だが、cutover の告知義務と移行コスト判断に影響する。

### 計画・設定

**Phase**: 実行順の見出しで、「いつ書くか」を表す。Tier とは直交する。

**Tier**: マイルストーンゲート所属のバッジ。[T1] は dogfood ブロッカー、[T2] は cutover ブロッカー、[T3] は port せず削除を表す。優先度ではない。

**config format**: tayk core が読み書きするファイル形式。すべて JSON とし、core は YAML パーサー依存を持たない。takt や CI など外部ツール所有ファイルは各ツールの規約に従う。

**skill config**: チャンネル固有のスキル挙動パラメータ。`config/skills/<skill>.json` のフルファイル 1 本で管理し、default と override の deep merge は行わず、zod schema の `.default()` が省略キーを補完する。

### アーキテクチャ

**MCP tool**: tayk が expose する型付き操作で、agent が直接呼ぶ第一級インターフェース。workflow tool と primitive tool の 2 層で構成する。

**workflow tool**: 人間の GO/NO-GO 判断ゲートで区切られた粗粒度の MCP tool。`collection.plan`、`collection.produce`、`collection.publish` があり、tool 内部で状態管理し resume できる。

**primitive tool**: 単一操作を行う細粒度の MCP tool。workflow tool が内部で呼ぶほか、agent が直接呼んで細かく制御できる。

**knowledge codec**: MCP tool の WHAT に対して WHEN/HOW を提供するドメイン知識パッケージ。60+ skill を `collection-lifecycle`、`channel-management`、`analytics`、`content-quality`、`distribution` の 5 本に集約し、cutover 時点で下流へ配布する操作面はこの 5 本だけとする。

**adapter**: core の MCP tool を各プロトコルへ橋渡しする薄いラッパ。MCP adapter と CLI adapter（`tayk <cmd>`）がある。

**tracer**: アーキテクチャ規約を確定させるため最初に end-to-end で通す垂直スライス。0 ベース再設計では `collection.plan` が該当し、PoC とは区別する。

### 動画生成・コンテンツ制作

**renderer**: collection の映像を生成するバックエンド。`remotion` は React コンポーネントから Chromium フレームキャプチャと ffmpeg エンコードまでを行い、`ffmpeg` は ffmpeg CLI を直接実行する。

**collection**: 1 本の YouTube 動画としてまとめられる楽曲群と成果物一式。`collections/planning/<slug>/` で制作し、公開後 `collections/live/` へ移動する。アルバムや YouTube playlist とは別概念である。

**collection lifecycle**: collection 固有の制作フロー。分析 → 企画 → GO/NO-GO → サムネ生成 → GO/NO-GO → 音源生成 → MIX/マスタリング → 動画生成 → upload → 公開後運用の順で進み、3 本の workflow tool に対応する。

**master**: collection 内の個別トラックをクロスフェード結合した最終音声ファイル（`master.mp3` / `master.wav`）。結合後に正規化し、動画生成の音声トラックにする。

### Chrome 拡張

**yield guard**: suno-helper が生成曲の `metadata.duration` を検査し、尺が閾値外なら同一プロンプトで自動再生成する品質最低ライン。良い曲を選ぶ masterup-pairs のキュレーションとは別責務である。

**community-helper**: YouTube のチャンネル投稿ページへ DOM 注入し、`yt-collection-serve` から取得した投稿データを投稿 UI へ自動入力する Chrome 拡張。`suno-helper`、`distrokid-helper` と同列に配置する。

**helper extension shell**: first-party Chrome helper 拡張が共有する、開発ゲート、manifest 管理、server 連携、popup/background/content の責務境界、エラー表示の考え方を揃える構造的な外枠。対象サイト固有の機能を同一にすることではない。

### マルチチャンネル運用・データ

**workspace**: 複数チャンネルを `channels/<slug>/` として同居させる単一リポジトリ。共有物はルートに 1 セット、per-channel 状態は各チャンネル配下に置く。単一チャンネルリポ構成は恒久サポートで、workspace への移行は opt-in とする。

**channel slug**: workspace 内でチャンネルを識別する `channels/` 直下のディレクトリ名。`--channel <slug>` または `CHANNEL=<slug>` で実行対象を指定する。

**competitor**: `analytics.benchmark.channels` に登録するベンチマーク分析対象の他者チャンネル。CLI フラグは `--competitor` であり、`--channel` は自チャンネル指定に予約する。

**channel registry**: first-party チャンネルの絶対パス一覧を `~/.config/tayk/channels.json` に JSON 配列で保持するもの。表示名などは各チャンネルの `config/channel/meta.json` から解決し、dashboard が消費する。

**dashboard**: 全 first-party チャンネルの analytics スナップショットを起動時に最新化して一覧表示するローカル Web UI。Python HTTP server が registry、全チャンネルの直列収集、read model/API/build asset 配信を担い、`dashboard/` の React + Vite + shadcn/ui 表示層は同一 origin の API だけを読む。SSOT は各チャンネルの `data/analytics_data_*.json`（将来は local store）。channel registry で対象チャンネルを解決し、失敗はチャンネル単位の部分エラーとして隔離する。

**audio studio**: 1 collection の `02-Individual-music/` を loopback 限定で一覧・再生し、後続の非破壊編集操作を載せるローカル Web UI。Python server が filesystem allowlist、probe、Range 配信、編集値の検証・保存、lifecycle を所有し、`audio-studio/` の React + Vite + shadcn/ui 表示層は同一 origin API だけを利用する。

**audio adjustments document**: collection の `20-documentation/audio-adjustments.json` に置く Audio Studio 編集意図の正本。`tracks.<filename>` は skill-config 既定から変えた cleanup 値だけを保持し、`order` / `shuffle_seed` / `pin_first` は master と概要欄チャプターが共有する確定曲順を保持する。`master` は master.mp3 全体へ適用する EQ・loudnorm・limiter、`finalize` は ambient layer の対象・音量・fade-in・loudnorm・mix の完全設定を保持する。原音・生成済み音声そのものは正本にしない。

**operator documentation site**: `docs/release-notes/*.md` と明示的な運用者向け Markdown allowlist を公開用の SSOT とし、`site/` の Blume workspace が目的別入口・詳細ページへ変換する静的 Web サイト。Cloudflare Pages から配信し、site workspace 自体は Python package や下流チャンネルへの asset 配布には含めない。

**channel-research report**: `/channel-research --benchmark|--market|--voice|--thumbnail` が生成する分析文書。`.claude/skills/channel-research/references/channel-research-report.schema.json` と `domains.documents.schema_registry` が契約を所有し、JSON が唯一の正本、同 basename HTML は表示用派生物である。skill writer は `application.documents.migration` を通し、下流 reader は `infrastructure.documents.publishing.read_published_json_document()` が返す検証済み JSON だけを使う。API 収集の `data/benchmark_*.json` / `data/comments_*.json` は source provenance 付き入力であり、分析正本ではない。

**channel-strategy document**: `/channel-strategy --direction|--persona|--scene|--constraints` が生成する4文書。`.claude/skills/channel-strategy/references/channel-strategy.schema.json` を共通 schema 正本とし、JSON は唯一の正本、同 basename HTML は表示専用派生物とする。`application.documents.channel_strategy` が persona→scene→constraints と evidence/constraint ID の参照を保存前に検証し、downstream reader は検証済み JSON+HTML pair の JSON だけを読む。旧 Markdown の直接 parse は禁止する。

**collection-plan document**: `/wf-new` の通常企画と batch record 投影が生成する `20-documentation/plan_proposals.json`。候補・制約適合・evidence・insight ID・preview asset・選択statusを正本とし、同 basename HTML は承認表示専用とする。`application.documents.collection_plan` が pair 再読込に成功した後だけ workflow-state owner API へ planning state を投影する。後工程は検証済み JSON だけを読む。

**データ 4 分類**: SSOT を、① git 管理 JSON の宣言的インテント、② local store のランタイム状態・履歴、③ SSOT を持たない再生成可能な生成成果物、④ YouTube のリモート実状態、に分類するもの。④のローカルデータは reconcile 対象のミラーである。

**local store**: チャンネルごとの `<CHANNEL_DIR>/data/local.db` に置く libSQL (Turso) embedded DB。時系列データと collection 状態を保持し、チャンネル設定の SSOT ではない。

**read model**: local store が提供する読み取り専用のクエリ面。① と ④ のミラーを読むが、SSOT はそれぞれ git と YouTube のままである。

### クラウド移譲

**workflow-state**: collection の制作・公開進捗を Git 管理の `workflow-state.json` に保持する制御面 document。schema の正本と読み書き owner は `domains.collections.workflow_state` であり、追従文書は `.claude/skills/wf-new/references/schema.md`。新規 consumer は owner の `read()` / `read_or_none()` / `update()` を使い、JSON の直パース・直接書き込みを追加しない。既存の直アクセスは段階移行対象で、未知キーを保持したまま移行する。Git同期境界は `infrastructure.vcs.state_sync` が所有し、読む前のfast-forward pullと更新後のcommit + pushを強制する。non-fast-forwardは通知eventを発火して自動merge/rebaseなしで停止する。ADR-0024 の single-writer 原則では `phase` が local / cloud 間の引き渡しトークンとなり、R2 のメディアデータとは分離する。

**制御面 / データ面**: ハイブリッド制作基盤の 2 面。制御面は Git（`workflow-state.json` と冪等性 tracking 群が正本）、データ面は R2（メディアの受け渡し）で、状態をデータ面に置かない（ADR-0024）。

**工程所有権**: 各工程の実行者（local / cloud）が境界規則により常に一意である性質。「いま誰の番か」は Git 上の state の phase が表し、single-writer 原則により state 自体が引き渡しトークンになる。Suno DL後はowner APIがmanifest key + root SHA-256だけを `handoff` に記録して `phase: cloud_owned` へ一方向遷移する。resolverは明示executorとownerが一致しなければ`no-op`にし、ネットワーク越しの分散ロックを作らない（ADR-0024）。

**サンドイッチ実行モデル**: クラウドジョブが Git clone + マニフェスト検証つき R2 pull でローカル FS を再構成し、既存のローカル前提コードを無改造で動かし、終了時に成果物 push + state commit する実行方式。MediaStore 抽象は pull / push を行う転送層としてのみ導入する（ADR-0024）。

**受け渡しマニフェスト**: 境界を越えるメディア受け渡しの完了マーカー。v1 は `<channel>/<collection>/<handoff>/manifest.json` に、path 昇順の正準ファイル一覧（相対 POSIX path・size・SHA-256）と、その一覧の canonical compact JSON に対する SHA-256 `root_sha256` を保持する。全 object の remote metadata と pull 後 content を検証した後、manifest を最後に atomic PUT する。R2 の強い read-after-write 整合性を completion marker 成立の必須前提とし、この保証を持たない MediaStore adapter は利用しない。後工程は bucket listing を行わず manifest 記載 key だけを検証付きで読み、manifest が無ければ「存在しない」扱いとする。正本は R2 で、Git state にはキー + root checksum のみ記録する（ADR-0024）。

**サンドイッチ runner**: cloud/local共通の基盤非依存実行境界。配布済み `wf-new/references/run-sandwich.sh` がchannel repository clone後にNixを介さず `uv run --frozen yt-hybrid-runner` を呼び、disk空き・MediaStore滞留量・生成費・月間Actions分数概算の開始前guard → Git state参照と一致するmanifest pull → 既存workflowを動かす単一agent CLI境界 → manifest-last成果物push → 制御面state commit/pushを順序固定する。`planning` stageは最古のplanning collection（なければ新規）だけをClaude Code headlessへ渡し、企画・promptの構造化pairと`prepared` stateが揃った場合だけ同じGit commitで確定する。guard拒否時はGit・MediaStore・agentへ副作用を起こさず通知eventを発火する。GitHub Actions固有のtrigger/concurrency/secret記述は後続の薄いworkflowだけが所有する（ADR-0024 決定7 / ADR-0025 決定5・6）。

**MediaStore**: 境界を越えるメディアの pull / push を行う転送層の抽象。第一実装は R2 で、将来のストレージ交換点をここに限定する。工程や resolver へのストレージ抽象の注入は行わない（ADR-0024）。

**軽量レジーム / 重量レジーム**: メディア工程（動画生成）の負荷 2 分類。分岐の正体は `config/channel/youtube.json::overlays.enabled` で、軽量は映像 stream copy（2 時間尺でも数分・クラウド実行対象）、重量はオーディオスペクトラム visualizer 等を全尺 filter_complex + libx264 再エンコード（当面 local 実行の暫定例外）。実行基盤の適性はこの 2 レジームで別々に評価する（ADR-0025）。

**正常完了**: ローカル音源・成果物の削除可能条件。Git 正本 state の 3 条件（`stage: "live"` / `phase: "complete"` / `upload.video_id` 非空）に加え、`upload.publish_at` が存在すればその経過、distrokid 有効チャンネルでは DistroKid 提出完了の記録を要する。判定は pull 成功後の state で行い、pull 失敗は fail-closed で削除しない。削除は `/publish --clean` の手動承認フローに一本化する（ADR-0027）。

## 自リポジトリ

### 再配置後の責務境界と配置規則

この節は、再配置後のファイル配置と依存方向を判断するための正本である。`CLAUDE.md` はこの文書への入口と開発規約を示し、`AGENTS.md` は Codex CLI 固有の補足を示す。構成・owner・配置判断を変更するときは、まずこの節と「主要モジュール」を確認する。

#### 層と許可される依存方向

依存は外側から内側へ一方向に流す。`commands/` は `application/`、`domains/`、`infrastructure/`、`configuration/`、`core/` を利用できるが、domain や infrastructure は commands を import しない。`domains/` は `core/` と設定の契約に依存する。`domains/` から `infrastructure/` への direct import は、provider-neutral な authoritative module である `infrastructure.filesystem`、`infrastructure.process`、`infrastructure.quota`、`infrastructure.browser`、`infrastructure.google.youtube`、`infrastructure.google.upload` の完全一致だけを許可する。外部 SDK・認証・network・subprocess と、列挙外の infrastructure module は引き続き adapter 境界の外へ漏らさない。SDK・認証の禁止 inventory は project dependency と infrastructure の実使用に基づく `google.auth`、`google.genai`、`google.oauth2`、`google_auth_httplib2`、`google_auth_oauthlib`、`googleapiclient`、`httplib2`、`oauthlib`、`openai` の exact namespace とその子であり、無関係な `google` namespace 全体には拡張しない。移行前から残る `domains/metadata/service.py` の `subprocess` edge は新規許可ではなく、consumer migration を行わない段階の exact baseline exception として固定し、別 domain・別 module への拡張を拒否する。`application/` は workflow 単位の orchestration を持ち、commands から呼び出される。`configuration/` は設定の読み込み・検証と dataclass を所有する。設定境界で必要な正規化処理に限り `configuration/` から `infrastructure/` の provider-neutral な utility を利用するが、`infrastructure/` から設定機能層へは依存しない。

Python 版 skill-config の正規キーは `configuration/skills.py` が所有する。アプリケーションコードから読むキーは `SKILL_CONFIG_KEYS`、SKILL.md の実行手順からだけ読むキーは `SKILL_ONLY_CONFIG_KEYS` に分け、両集合と `.claude/skills/<key>/config.default.yaml` の双方向一致を `yt-skills lint` で検証する。`music.prompt` のような名前空間キーは `.claude/skills/music/config.default.yaml` と `config/skills/music.yaml` を deep-merge した後に `prompt` 節だけを返す。

統合で owner が変わる下流 override は `yt-skills migrate-config --channel-dir <path> --dry-run` で差分を確認してから明示適用する。移行対応表は吸収先 skill と名前空間キーが実在してから有効化し、統合前の候補を先行登録しない。`yt-skills sync` はデータ移行を副作用として実行せず、未移行と孤児の警告だけを分けて表示する。

`infrastructure/legacy_utils/` と `utils/` は下流公開 import のための compatibility facade であり、canonical implementation の owner ではない。canonical source、tests、skills、bench から facade へ依存してはならない。`dashboard/`、`audio-studio/`、`extensions/` はそれぞれ独立した表示層・編集表示層・拡張層で、Python domain 実装の owner にはしない。

#### `core/adapters` の最終 surface

#3895 の移行後、`core/adapters` は wildcard facade を持たず、既存 domain が利用する明示 re-export と package file の次の集合だけを保持する。拡張子を問わない file の追加・削除、adapter 内または consumer 側からの `import *`、literal dynamic import による adapter consumer の再導入は repository-reorganization contract が拒否する。

<!-- core-adapter-surface:start -->
- `src/youtube_automation/core/adapters/__init__.py`
- `src/youtube_automation/core/adapters/google/__init__.py`
- `src/youtube_automation/core/adapters/media.py`
- `src/youtube_automation/core/adapters/observability.py`
- `src/youtube_automation/core/adapters/runtime.py`
- `src/youtube_automation/core/adapters/security.py`
- `src/youtube_automation/core/adapters/youtube.py`
<!-- core-adapter-surface:end -->

`runtime.py`、`media.py`、`youtube.py` を含む各明示 adapter の symbol と runtime behavior はこの最終 surface 固定では変更しない。`infrastructure/legacy_utils/` の compatibility facade は別契約であり、この集合には含めない。

#### 新規ファイルの配置判断

新しいファイルは、次の順で最も狭い責務の owner に置く。

1. 設定の schema、loader、dataclass は `src/youtube_automation/configuration/`。
2. 外部 API、SDK、認証、filesystem、network、subprocess の adapter は `src/youtube_automation/infrastructure/`。
3. 業務ルールと provider-neutral な model / policy は `src/youtube_automation/domains/`。
4. 複数 domain を束ねる状態付き workflow は `src/youtube_automation/application/`。
5. CLI の argparse、stdio、exit、composition は対応する `src/youtube_automation/commands/<domain>/`。
6. 共通のドメイン例外・横断 primitive は `src/youtube_automation/core/`。
7. 既存機能の回帰テストは対象層に対応する `tests/` の領域、skill の実行補助はその skill の `.claude/skills/<skill>/references/`。

既存 owner がある場合は同じ責務の新 directory を作らず、canonical owner に追加する。下流公開 import を維持する必要がある場合だけ、`infrastructure/legacy_utils/` に明示的な薄い facade を置き、実装を複製しない。新規 CLI は `commands/` に置き、`pyproject.toml` の `yt-*` entrypoint と対応する契約テストを同時に更新する。

#### 変更時に辿る対応表

機能を変更するときは、実装だけで完了とせず、次の対応する成果物を順に確認する。

| 変更内容 | 最初に確認する実装 | 次に確認する設定・テスト | 参照する文書・配布物 |
|---|---|---|---|
| 設定項目・schema | `configuration/<section>.py` と `configuration/loader.py` | `config/channel/*.json`、configuration 契約テスト | `docs/architecture.md`、`docs/development.md` |
| CLI・実行入口 | `commands/<domain>/` と `entrypoints.py` | `pyproject.toml`、CLI 契約テスト | 対応 skill の `SKILL.md`、`docs/development.md` |
| domain workflow・業務ルール | `domains/` または `application/` | domain/application テスト、fixture | `docs/architecture.md` の主要モジュール表 |
| 外部サービス・adapter | `infrastructure/<area>/` | adapter 契約テスト、認証・secret 設定 | `docs/development.md`、該当 migration 文書 |
| skill・配布リソース | `.claude/skills/`、`.claude/CLAUDE.template.md` | skill lint、sync / installed-wheel テスト | `CLAUDE.md`、`AGENTS.md`、配布設定 |
| dashboard・audio studio・extension | `dashboard/`、`audio-studio/` または `extensions/` | frontend / extension テスト・build | `docs/development.md`、各領域の案内文書 |

移動や owner 変更を伴う場合は、`docs/architecture/repository-reorganization-receipt.json`、参照元全体、下流公開 import、CLI、設定パス、package resource を追加で確認する。履歴監査文書の旧 path は履歴証跡として保持するが、active source・tests・skills・案内文書には canonical path だけを記載する。

- `src/youtube_automation/configuration/` — 設定 loader / dataclass owner
- `src/youtube_automation/infrastructure/legacy_utils/` — 再配置後も下流公開 import を維持する compatibility adapter 群
- `src/youtube_automation/commands/` — `yt-*` CLI の thin adapter。`analytics` / `channel` / `collections` / `distrokid` / `documents` / `media` / `metadata` / `suno` / `system` / `thumbnail` / `uploads` / `youtube` の 12 domain に分割し、argparse・stdio・exit・composition を所有する。アップロード CLI（Auto / Collection / Shorts）は `commands/uploads/` が入口で、実装は `domains/uploads/` が持つ
- `src/youtube_automation/domains/media/audio_adjustments.py` — `audio-adjustments.json` の cleanup 差分・確定曲順・master 全体調整・ambient finalize 調整を検証し、実ファイル集合との一致確認と他段キーを保つ原子的更新を所有する
- `src/youtube_automation/entrypoints.py` — console script wrapper。`pyproject.toml [project.scripts]` の全 `yt-*` がここを経由し、**例外なく** `commands/` 配下の module を `import_module` して `main` を呼ぶ
- `src/youtube_automation/commands/channel/channel_init_templates.py` — channel-init が生成する設定テンプレート
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に `_skills/` として `force-include` され、`yt-skills sync` で各チャンネルへ展開される
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ（共通骨格）。wheel に `_claude_md/CLAUDE.template.md` として `force-include` され、`yt-skills sync --asset claude-md` で各チャンネルの `.claude/CLAUDE.md` として展開される
- `src/youtube_automation/infrastructure/resources/channel/youtube-automation.yml` — 下流チャンネルの日次 GitHub Actions workflow 正本。`yt-skills sync --asset channel-workflow` で `.github/workflows/youtube-automation.yml` へ配布し、基盤非依存のサンドイッチrunnerだけを呼び出す
- `.claude/skills/wf-new/references/github_actions_schedule.py` — 配布 workflow 内の schedule 管理 marker だけを原子的に configure / status / disable する GitHub Actions backend adapter
- `.claude/skills/wf-new/references/run-github-actions.sh` — GHA の Claude subscription token preflight と、credential を含まない failure summary を所有する wrapper
- `.claude/skills/wf-new/references/github-actions-oauth.md` — 下流へ配布する Claude subscription token の初回配備・検証・rotation runbook
- `.agents/skills` — `.claude/skills` への symlink。Codex CLI 用の探索パス（Codex 規約 `$REPO_ROOT/.agents/skills`）
- `AGENTS.md` — Codex CLI 向けエージェント指示。CLAUDE.md と並立し、Codex 視点のドキュメント補足を含む
- `site/` — Blume ベースの運用者向け公開ドキュメントサイト。release notes と明示 allowlist の原本を読み、Python 配布物とは独立して build・deploy する
- `audio-studio/` — collection 音源編集 UI の独立 React / Vite / shadcn workspace。build asset だけを Python package へ同梱する

## 下流チャンネルリポジトリ（`CHANNEL_DIR` が指す先）

```
config/channel/         # 責務別分割設定（v2.0.0 以降）
  meta.json             # channel / youtube_channel
  content.json          # genre / tags / descriptions / title
  youtube.json          # youtube / music_engine / content_model
  analytics.json        # analytics / benchmark
  playlists.json        # playlists
  workflow.json         # wf_next / publish / scheduled_automation の optional workflow 設定
  audio.json            # audio
  shorts.json           # shorts (optional)
  comments.json         # comments (optional)
  pinned-comment.json   # pinned_comment (optional)
  distrokid.json        # distrokid (optional)
  community-draft.json  # community_draft (optional)
config/localizations.json
auth/{client_secrets,token}.json  # + 任意の token.readonly.json（read-only 系用。docs/oauth-scopes.md）
.claude/skills/         # yt-skills sync で展開
.agents/skills          # → ../.claude/skills の symlink。skills sync が併設（Codex 探索パス）
collections/            # コンテンツ成果物
assets/stock/           # ボツ画像ストック (#364)。<theme-slug>/ 配下に画像 + .meta.json
```

## 主要モジュール

| モジュール | 責務 |
|---|---|
| `configuration` | `config/channel/*.json` の glob ロード／バリデーション。`load_config()` / `channel_dir()` / `reset()` / `ChannelConfig` を export |
| `configuration.{meta,content,youtube,analytics,playlists,workflow,shorts,audio,localizations,comments,pinned_comment,distrokid,community_draft}` | 責務別 dataclass |
| `infrastructure.google.youtube` | YouTube API clients（instance-scoped） |
| `domains.uploads.youtube` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `core.errors` | ドメイン例外（`AutomationError` 基底、`ConfigError` / `YouTubeAPIError` / `ValidationError` / `UploadError`） |
| `infrastructure.media.collection_paths` | コレクションディレクトリ構造の解決 |
| `infrastructure.media_store` | 境界転送専用の fail-closed Local / Cloudflare R2 adapter（工程内部へは注入しない） |
| `domains.suno` | Suno 設定、歌詞、プロンプト、プレイリスト、選曲の生成・検証 |
| `domains.suno.downloaded` | downloaded payload、workflow、検証、archive、apply transaction |
| `domains.suno.name_matching` | prompt・playlist・downloaded filename 共通の名前正規化と曖昧性検出 |
| `domains.skills` | skill 列挙、frontmatter、Markdown セクション、reference 解決の provider-neutral inventory |
| `domains.metadata` | `service` の状態付き orchestration と titles / descriptions / tags / localizations leaf |
| `domains.analytics` | Analytics の Protocol、収集、分析、レポート、時系列 policy。SDK/client は adapter 境界で解決 |
| `domains.channel_readiness` | TTP 対象・branding・benchmark・制作設定の provider-neutral なチャンネル準備判定 |
| `domains.thumbnail` | サムネ特徴量、相関、参照、archive、選択 policy（Pillow） |
| `domains.media` | 音声、字幕、画像、動画の provider-neutral model / policy |
| `domains.media_store` | 工程境界の `<channel>/<collection>/<handoff>/` key、checksum metadata、push / pull / exists port |
| `domains.media_handoff_manifest` | versioned handoff manifest schema、正準 file list、root checksum の typed owner |
| `domains.notifications` | ハイブリッドpipelineの正常／異常event種別とprovider-neutralな分類 |
| `domains.human_tasks` | canonical stateからAPI非対応の未完了作業を決定的に抽出し、Markdown／通知要約へ投影する純粋モデル |
| `domains.distrokid` | DistroKid naming、metadata、specification、preparation、release policy |
| `domains.collections.weekly_vote_log` | 週次投票ログ reader、initializer、schema、保存・検証 |
| `domains.documents.schema_registry` | リポジトリ所有 JSON Schema の固定 inventory、Draft 7 compile cache、値非表示の検証エラー変換。外部 schema path は受け取らない |
| `domains.documents.operational_artifacts` / `operational-artifacts.json` | `reports/`、`docs/channel/`、`docs/plans/`、`docs/benchmarks/`、`20-documentation/` の生成成果物について owner skill・schema・consumer を一意に列挙する正本。`yt-skills lint` は全配布 skill の本体/reference、writer script、schema registry を走査し、Markdown writer、JSON/HTML pair 欠落、orphan、未検証 consumer、stale allowlist を具体 path 付きで拒否する。手書き入力・repository docs・machine-only は理由付き allowlist だけを許可する |
| `domains.documents.rendering` | schema annotation / `x-view` による card・table・media の自己完結 HTML 化と escape / CSP / embedded JSON 検証 |
| `application.documents.migration` | skill 生成運用文書の new / Markdown 明示移行 / JSON+HTML 再更新を判定し、pair の検証付き transaction と旧 Markdown 削除を一操作として調停 |
| `application.documents.channel_strategy` | direction / persona / scene / constraints の schema と文書間 ID 参照を検証し、共通 migration workflow による原子的保存を調停 |
| `application.documents.collection_plan` | collection plan の schema・候補/evidence ID・選択状態を検証し、JSON+HTML pair 公開成功後の planning state 投影を調停 |
| `application.media_handoff` | 全 object の remote metadata/content 検証、manifest-last push、manifest-only pull、local rollback を調停 |
| `application.pipeline_notifications` | 各pipeline ownerのtyped eventと公開・guard結果をprovider-neutral通知eventへ写像し、配送sinkへ委譲 |
| `application.human_tasks` | collection stateを列挙し、固定`human-tasks.md`の原子公開後にprovider-neutral notifierへ要約を渡す |
| `application.analytics.video_report` | 動画解析結果を audit report schema へ写像し、共通運用文書 migration による JSON+HTML 公開を調停 |
| `.claude/skills/channel-research/references/channel-research-report.schema.json` | benchmark / market / viewer voice / thumbnail 調査の比較表・勝ちパターン・根拠・適用候補を共通定義し、skill writer と全 downstream reader の正本になる |
| `infrastructure.filesystem` | provider-neutral な filesystem I/O と、複数 text file の fsync・rollback・公開後 verifier 付き transaction |
| `infrastructure.localserver` | loopback server 共通の collection 探索、server-kind 別 PID / stop / startup-lock path と lifecycle record 読取、CORS origin policy |
| `infrastructure.documents.publishing` | 構造化 JSON と同 basename の HTML を temp・fsync・再読込検証・replace で原子的に公開し、consumer 向けに schema 検証済み JSON+HTML 対応 pair を再読込する |
| `commands.documents.migrate` | skill writer の未公開 candidate JSON と明示 yes/no を共通移行 workflow へ渡す `yt-document-migrate` adapter |
| `commands.documents.render` | 固定 schema registry から選択して HTML を生成する `yt-document-render` adapter |
| `infrastructure.media.image_provider` | 画像生成プロバイダー抽象化（Gemini / OpenAI 切り替え） |
| `infrastructure.media.stock` | ボツ画像ストック化（`assets/stock/<theme>/` への退避・列挙・整理、隣接 `.meta.json` 管理） |
| `infrastructure.auth` | OAuth 2.0 token の読み込み・refresh・atomic 永続化、scope と YouTube service 生成 |
| `infrastructure.secrets` | シークレット解決（`_SECRET_REFS` で参照定義） |
| `infrastructure.notifications.discord` | typed pipeline eventを既存secret・webhook owner経由でbest-effort配信するDiscord sink |
| `application.live_chat.{codex,filters,history,models,runner}` | active broadcast のチャット取得、Codex 構造化判定、入出力フィルタ、PT 日次・時間・連続 user 上限、重複防止履歴、返信投稿 loop |
| `commands.youtube.live_chat_reply` | `yt-live-chat-reply` 常駐 CLI。`comments.live_chat.enabled` を opt-in とし、VPS では独立した `live-chat-reply.service` から起動 |
| `commands.system.skills_sync` | `yt-skills` 本体 |
| `commands.collections.collection_serve_discovery` | 固定 loopback endpoint の稼働 server registry、heartbeat、TTL、owner takeover |
| `commands.media.audio_studio` | collection 音源の loopback 限定 API、Range 配信、static asset、server lifecycle |
| `extensions/shared/server-discovery.ts` | registry schema v1 の検証と `/server-info` probe を両 helper 拡張へ提供 |
| `extensions/shared/server-source-migration.ts` | 廃止した配信元候補履歴 storage key の共通 migration |

### dashboard architecture

`yt-dashboard` は channel registry、起動時および `POST /api/refresh` の排他的な収集、read model、JSON API、loopback 限定配信を担当する。通常起動と画面からの更新では全チャンネルを更新し、1 チャンネルの更新失敗は部分エラーとして隔離する。`--skip-refresh` 時の endpoint は保存済み snapshot から read model だけを再構築する。pipeline 表示は Git 管理の `workflow-state.json` を owner API 経由で投影し、R2 や通知履歴を第二の正本にしない。`dashboard/` の React + Vite frontend は shadcn/ui を使った同一 origin JSON API の表示・更新操作だけを担当し、dashboard 限定の TypeScript 例外として `extensions/shared-ui` を直接 import しない。

### operator documentation site architecture

`docs/release-notes/*.md` の公開 frontmatter と本文に加え、`site/operator-doc-source.ts` の allowlist が次の運用者向け原本だけを read-in-place で公開する。

- `ONBOARDING.md`
- `docs/tool-setup.md`
- `docs/oauth-setup.md`
- `docs/features.md`
- `docs/workflow-cheatsheet.md`
- `docs/chrome-extension-install-guide.md`
- `docs/dashboard.md`
- `docs/channel-workspace-migration.md`
- `docs/cloud-execution.md`
- `docs/live-streaming.md`
- `docs/live-chat-reply.md`
- `docs/ambient-layers.md`
- `docs/scheduled-publish.md`

source は build ごとに原本を読み、掲載対象間の相対 Markdown link を site route、対象外の repository 内 Markdown link を GitHub の原本へ解決する。加えて `site/skill-page-source.ts` は `.claude/skills/*/SKILL.md` を動的に走査し、frontmatter の `name` / `description` と `## 前提` / `## 前後工程` だけから `/skills` と個別ページを生成する。カテゴリの正は `docs/features.md` の9分類に置き、実行手順や内部契約は公開しない。どちらも原本を移動・永続コピーせず、Blume が所有する `site/.blume/` の一時 staging と `site/dist/` の生成だけを行う。GitHub Actions の site workflow は13原本を個別 path として、skill ページは `.claude/skills/**` として監視し、broad な `docs/**` は使わない。

公開境界は allowlist で閉じる。`docs/adr/`、`docs/audits/`、`docs/investigations/`、`docs/research/`、`docs/strategy/`、`docs/benchmarks/`、および `docs/development.md` や `docs/takt-operations.md` などの development workflow 文書は暗黙収集せず、navigation・search・生成 route に含めない。

公開対象であることと Python 配布対象であることは別契約である。既存用途により一部原本が wheel / sdist に含まれていても、site 公開を理由に Python package allowlist は拡張しない。`site/`、`site/.blume/`、`site/dist/` は Python wheel / sdist から除外し、Cloudflare Pages の preview / production 配信境界へだけ渡す。

### B2 domain ownership receipt / B3 handoff

B3 の owner と後続 handoff は機械可読な
[`b3-owner-receipt.json`](architecture/b3-owner-receipt.json) に固定する。domain は
SDK・ADC・network・subprocess の実装を持たず、それらは B4 の adapter 境界へ渡す。

Issue #2305 で Suno の旧 `utils.suno_*` 14 module と `utils.metadata_generator` を削除し、実行 consumer と patch seam を新 owner へ移行した。`domains.metadata.__all__` は次の9 symbolに固定する。

`BAHMetadataGenerator`, `LOCALIZED_TITLE_PLACEHOLDERS`, `SceneTitleViolation`, `build_short_description`, `build_short_localizations`, `format_scene_title_violations`, `format_title_template`, `validate_localizations_title_templates`, `validate_scene_phrases`.

B3 が直接利用する leaf API は `domains.metadata.descriptions.build_short_description` / `domains.metadata.localizations.build_short_localizations` と、placeholder 検証の `domains.metadata.titles.format_title_template` / `domains.metadata.localizations.validate_localizations_title_templates`。既知 downstream の `wf_batch_runner.py` と `bulk_update_collection_localizations.py` は、旧 metadata import を `domains.metadata`（または owner leaf）へ置換する。

歴史監査資料の旧パス表記は監査時点の記録として保持し、active source / skill / docs では新 owner のみを参照する。

### collection-serve discovery schema v1

固定 endpoint は `http://localhost:7872/.well-known/yt-collection-serve`。`yt-collection-serve` は起動時と heartbeat ごとに `Content-Type: application/json`、`Origin` なしで次を POST する。

```json
{
  "instance_id": "fixture-instance",
  "server_info": {
    "channel_name": "Fixture Channel",
    "channel_short": "fixture",
    "hostname": "fixture.localhost",
    "port": 49152,
    "base_url": "http://fixture.localhost:49152",
    "label": "Fixture Channel"
  }
}
```

GET の schema v1 応答は次の完全形。`schema_version` は互換性番号、`ttl_seconds` は heartbeat が更新する生存期間、`servers` は `base_url` 順の稼働登録である。各 entry の `instance_id` はプロセス識別子、`expires_at` は Unix time の失効時刻、`server_info` はチャンネル名・短縮名・loopback host/port/base URL・selector 表示 label を表す。

```json
{
  "schema_version": 1,
  "ttl_seconds": 30,
  "servers": [
    {
      "instance_id": "fixture-instance",
      "expires_at": 130.0,
      "server_info": {
        "channel_name": "Fixture Channel",
        "channel_short": "fixture",
        "hostname": "fixture.localhost",
        "port": 49152,
        "base_url": "http://fixture.localhost:49152",
        "label": "Fixture Channel"
      }
    }
  ]
}
```

同じ `instance_id` の POST は entry を増やさず `expires_at` を更新する。正常終了は `{"instance_id":"fixture-instance"}` を DELETE して即時削除し、異常終了した entry は TTL 境界（`expires_at` と同時刻）で失効する。最大 body は 16384 bytes、`instance_id` は最大 128 文字、同時登録は最大 128 件。POST/DELETE は JSON 以外を 415、`Origin` 付き要求を 403、不正 schema を 400、body 超過を 413、登録数超過を 429 にし、状態を変更しない。未知 path は 404、未対応 method は 405。

拡張側 storage schema は Suno が `chrome.storage.local["sunoServerUrl"]`、DistroKid が `chrome.storage.local["serverUrl"]` に選択中 URL 文字列だけを保存する。共通の旧候補配列 `chrome.storage.local["ytCollectionServeSources"]` は更新時 migration で削除し、以後は再作成しない。
