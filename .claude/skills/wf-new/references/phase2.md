### Phase 2: 選択後の順次オーケストレーション

ユーザー選択または設定による自動選択で企画が確定したら、以下を上から順に実行する。途中で失敗したら、失敗したステップの次アクションを表示して停止する。

Phase 1 で open insights を渡していた場合は、企画選択の直後にメインが `/wf-new` の「open insights の消費と status 反映」の規則に従って `data/insights.jsonl` の該当エントリの `status` を更新する（採用企画の根拠に引用 → `adopted`、検討の上見送り → `dismissed`、未検討は `open` のまま）。判定規則を `/wf-new` 側で再定義しない。

#### 2a. コレクション初期化（ディレクトリ + workflow-state.json）

`/wf-new` の選択結果を入力にして、コレクションディレクトリと workflow-state.json を自動生成する:

```bash
uv run yt-init-collection "<Collection Name>" "<theme-slug>" \
  --track-count <N> --selected-plan <A-E> --music-engine <suno|lyria|minimax> \
  --playlist <playlist-key>
```

- `<Collection Name>`: 企画で決定したコレクション表示名
- `<theme-slug>`: ハイフン区切りのテーマスラッグ（例: `brigid-hearth`）
- `--track-count`: 確認済みトラック数（デフォルト 12）
- `--selected-plan`: 選択された企画（A〜E）
- `--music-engine`: 音楽エンジン（`suno` / `lyria` / `minimax`）。**省略時は `config/channel/youtube.json` の `music_engine` が使われる**。コレクション単位で上書きしたいときのみ明示する
- `--playlist <key>`: 所属させるプレイリスト key（`config/channel/playlists.json`）。複数回指定可。**分類プレイリスト（`auto_add` 以外）を定義しているチャンネルでは必須**。分類しないことが意図なら `--no-playlist` を明示する

`--playlist` を必須にしているのは、theme slug のキーワード照合（`auto_add_themes`）が新テーマのたびに漏れ、黙って `auto_add` のプレイリストだけに入る事故を防ぐため (#4346)。候補が分からないときは `uv run yt-playlist-status` で一覧を確認する。

スクリプトが以下を自動実行:
- `collections/planning/YYYYMMDD-<short>-<theme>-collection/` ディレクトリ作成
- 標準骨格サブディレクトリ（`01-master`, `02-Individual-music`, `10-assets`, `20-documentation`）作成
- `workflow-state.json` 初期化（stage=planning, phase=planning）

実行後、骨格が作り切れていることをプリフライトで検証する（fail-loud、#1494）:

```bash
uv run yt-collection-preflight <collection-dir-name>
```

- `[NG]` が出たら `uv run yt-collection-preflight <collection-dir-name> --fix` で欠落を補完してから先へ進む
- `uv run yt-init-collection` が「ディレクトリが既に存在します」で止まった場合も、**手動 mkdir で復旧しない**。`uv run yt-collection-preflight <collection-dir-name> --fix` で骨格を補完する（`workflow-state.json` が無ければ改めて `uv run yt-init-collection` の失敗原因を解消する）

出力されたパスを後続ステップで使用する。フルスキーマは `references/schema.md` を参照。

#### 2b. scene_phrases 初期化

次に、多言語タイトル生成で必須となる `workflow-state.json.scene_phrases` を投入する。

`config/localizations.json` の `supported_languages` が 2 言語以上の場合だけ、まず Agent ツールでサブエージェントを起動し、`en` 以外の `supported_languages` 全件に対する翻訳 JSON object だけを生成させる。CLI 内部から Gemini / Claude CLI を呼ばない。`config/channel/content.json` の `title.theme_scenes[<theme>]` が未定義の場合は、Agent が企画内容から英語 scene phrase も生成し、`--en` で明示指定する。

```bash
uv run yt-populate-scene-phrases <collection-dir-name> \
  --translations-file /tmp/scene-phrases.json

# theme_scenes[<theme>] が未定義の場合
uv run yt-populate-scene-phrases <collection-dir-name> \
  --en "<Agent-generated English scene phrase>" \
  --translations-file /tmp/scene-phrases.json
```

- `<collection-dir-name>`: 2a で作成された `YYYYMMDD-<short>-<theme>-collection` のディレクトリ名
- 英語フレーズは `config/channel/content.json` の `title.theme_scenes[<theme>].scene` から自動解決される。翻訳文は Agent ツールで生成し、`--translations-json` または `--translations-file` で渡す
- **`supported_languages` が 1 言語以下のチャンネルでは翻訳 JSON を生成しない**。CLI 側で自動スキップされるため、必要なら確認目的で引数なし実行してよいが、Agent に翻訳 JSON を作らせない
- 既に `scene_phrases` が存在する場合もスキップ（`--overwrite` で上書き可能）
- `theme_scenes[<theme>]` が未定義の場合は停止せず、企画内容から Agent が英語 scene phrase と翻訳 JSON を生成し、`--en "<Agent-generated English scene phrase>" --translations-file ...` で投入する。詳細は `references/scene_phrases.md` 参照

**エラーハンドリング:**
- `theme_scenes` 未定義 + `--en` 未指定 → エラー終了。`config/channel/content.json` の `title.theme_scenes` に該当 theme を追加するか、`--en` を渡して再実行
- 多言語チャンネルで翻訳 JSON 未指定 / 言語欠落 → エラーに表示されるプロンプトで Agent に JSON を再生成させる（メタデータ生成前に `/wf-next` から再実行可能）

#### 2c. サムネイル確定 + 音楽素材生成

cloud planning runner から、企画・music prompt の pair を確定したら `phase: planning` のまま停止する指示を受けている場合は、この節の thumbnail branch を起動しない。music branch だけを実行し、engine 別 prompt の JSON/HTML pair を通常契約どおり検証してから `planning.generated = true` と `assets.music_prompts = true` を owner CLI で確定する。`thumbnail` / `main` / `loop.mp4` は生成せず、`set-phase prepared`、2e、2f は実行しない。この停止点は GitHub Actions に ADC を渡さず企画工程だけを完了させるための cloud 専用契約であり、通常の local 実行は以下の全 branch を続行する。

サムネイル候補生成と音楽素材生成は initial dispatch で重ね、承認・確定・成果物検証は join 後に進める。Suno チャンネルでは、メインが対象 collection と確定企画を固定し、`config/skills/music.yaml::prompt` と利用可能な `data/video_analysis/<slug>/*.json` を fallback / 推奨入力として `/music --prompt` へ渡す。subagent は共有 config を変更せず、その collection の `20-documentation/suno-patterns.yaml` に effective Style 系の root 値を保存する。`suno_preset` が無くても確定企画と制約から collection-local Style を設計して続行し、検証前に `assets.music_prompts = true` へ更新しない。

各 branch の成果物検証、state 適用、partial failure、再開判定は、最初に [`Phase 2c 成果物・再開契約`](phase-2c-artifact-contract.md) を読み、その契約だけを正とする。

##### 2c-1. サムネイル候補生成

1. **メインが共有入力と再開対象を固定**:
   - 対象 collection の絶対 path、確定企画、`workflow-state.json::theme`、`planning.music.engine`、thumbnail の effective auto-selection / textless 設定を実ファイルから固定する。以後の 2 call に同じ値を渡し、subagent に推測させない
   - Phase 2c 成果物・再開契約で flag と実成果物を branch ごとに再検証する。flag が `true` なのに成果物が欠落・破損・不整合なら dispatch せず fail-closed に停止する
   - 両 branch が検証成功済みなら initial dispatch を省略する。片側だけが未完了なら、その 1 call だけを起動し、成功済み側を exactly-two の数合わせで再生成・再承認しない

2. **企画成果物と preview status を固定**:
   - 選択した企画のプレビュー画像は `10-assets/planning-preview.png` に保存する。`10-assets/main.png/jpg` にはコピーしない
   - Phase 1 の企画候補一覧と選択結果を `20-documentation/` に保存
   - プレビューディレクトリの自セッション分を削除
   - thumbnail branch が未完了の場合だけ、メインが次を実行して結果を固定する
   ```bash
   uv run python .claude/skills/thumbnail/references/finalize_planning_preview.py <collection-path>
   ```
   - `status: FINALIZED`: `planning-preview.png` を RGB JPEG へ原子的に形式変換した同じ画像内容の `10-assets/thumbnail.jpg` が確定済み
   - `status: MISSING`: 空ファイルや代替画像を作らず、thumbnail call の既存 `/thumbnail <theme>` フォールバックへ進む
   - コマンド失敗、symlink、画像として読めない入力、JPEG 検証失敗: 既存 `thumbnail.jpg` と state を変更せず停止する

3. **両 branch が未完了なら exactly two calls を同時起動**:
   - 1 回の Agent tool dispatch に次の独立した 2 call だけを含め、同じ message で同時起動する。順次 2 回に分けず、3 call 目や `/thumbnail --loop` を混ぜない
   - Agent 1: thumbnail branch。`status: FINALIZED` なら AI 生成を行わない（候補生成も再選択もしない）。既存 preview の品質検証・確定経路のうち、承認を伴わない `thumbnail.jpg` の実在・可読性確認だけを行い evidence を返す。`status: MISSING` なら `single_step` / provider を問わず `/thumbnail <theme>` の Subagent Contract でテキスト付き候補と `20-documentation/thumbnail-prompts.md` を候補生成する。承認、確定コピー、state 更新は行わない
   - Agent 2: music branch。`music_engine: suno` なら `/music --prompt <theme>` で `20-documentation/suno-patterns.yaml` と検証済み `suno-prompts.json` / `.html` pairを生成する。`music_engine: lyria` なら `/music --generate <theme>` のプロンプト設計だけを行い、検証済み `lyria-prompt.json` / `.html` pairを生成する。`music_engine: minimax` は generation approvalを伴う後続 `/music --generate` へstyle prompt設計を引き渡す。この Phase では Lyria 3 API / MiniMax Music API を実行しない
   - 両 Agent へ、固定した対象 collection の絶対 path、確定企画、theme、engine / effective config という具体的な入力、期待成果物の絶対 path、禁止事項、完了報告形式を渡す。両 Agent は `workflow-state.json` を更新しない、AskUserQuestion を実行しない、共有 config を変更しない
   - 片側再開では上記の該当 Agent だけへ同じ具体的な契約を渡す。両方未完了のときだけ exactly-two 同時 dispatch とする

##### 2c-2. サムネイル承認・確定 + 音楽素材生成

initial dispatch を行った場合は両 Agent の完了を待つ。片方の失敗で他方を cancel せず、両方の完了報告と実成果物を回収してから join する。メインが thumbnail の承認、auto-selection、textless 確定、`/thumbnail --compare`、両 branch の成果物検証と state 適用を所有し、music branch の完了を理由に thumbnail gate を省略しない。

このステップにテキスト付き候補の承認ゲートと `mode: full` の自動確定分岐を一元化する。最初に thumbnail の `config.default.yaml` と `config/skills/thumbnail.yaml` を deep-merge し、`textless.enabled` を確定する。未設定は既定の `true` として扱う。以下の 1〜4 は mode 別に実行する。

**`planning-preview.png` から確定済み**:

1. 企画選択時に承認済みの同じ画像なので、文字入り候補の生成・再選択・thumbnail の AskUserQuestion は行わない。`10-assets/thumbnail.jpg` を `/thumbnail --compare` で 320px 視認性検証し、署名・透かし・ロゴ・手指破綻の既存目視 QA を通す。失敗時は state を更新せず停止する
2. QA 成功後に `uv run python .claude/skills/thumbnail/references/archive-approved-thumbnail.py <collection-path>` を実行する。archive の Hard Gate は既存契約どおり維持する
3. `textless.enabled` が未設定または `true` なら、確定した `thumbnail.jpg` を入力、生成対象 `main` を指定して別 subagent へ委譲する。`mode: full` は生成可否と textless 背景承認を質問せず既存の check 成功後に確定し、それ以外は既存どおり textless 候補だけをプレビュー・承認して `main.png/jpg` へ確定する。`false` なら textless 生成・承認を省略し、`share_thumbnail_as_main.py <collection-path>` を実行して `status: SHARED`、同一 SHA-256、`main.png` 不在を検証する
4. `thumbnail.jpg` と `main.png/jpg` の確定検証結果を Phase 2c 成果物・再開契約へ thumbnail branch の結果として渡し、成功時だけメインが `uv run yt-workflow-state --collection "$COLLECTION_DIR" set-asset thumbnail true` を実行する。この `thumbnail.jpg` を再度 AskUserQuestion にかけない

以下の mode 別分岐は `status: MISSING` から既存 `/thumbnail` フォールバックへ進んだ場合だけ実行する。

**`mode: full`**:

1. AskUserQuestion と `open` を実行せず、`uv run yt-thumbnail-auto-select <collection-path> --dry-run` が exit 0 であることを確認してから `uv run yt-thumbnail-auto-select <collection-path> --apply` を実行する。`10-assets/thumbnail.jpg` と `workflow-state.json::thumbnail_auto_selection.mode == "full"` を検証する
2. `textless.enabled` が未設定または `true` なら、確定した `thumbnail.jpg` を入力、生成対象 `main` を指定して別 subagent へ委譲する。生成可否と textless 背景承認は質問せず、`yt-thumbnail-check` が exit 0 かつ候補が存在するときだけ `10-assets/main.png/jpg` へ確定コピーする。`false` なら textless 委譲・生成・承認を再要求せず、`share_thumbnail_as_main.py <collection-path>` を実行し、`status: SHARED`、`thumbnail.jpg` と `main.jpg` の同一 SHA-256、`main.png` 不在を検証する
3. `/thumbnail --compare` の 320px 視認性検証はスコープ外のまま省略せず、自動確定後に別途実行する。失敗しても不適格候補を強制採用せず、`/thumbnail` の「full モード失敗時の手動切替」を表示して state を更新せず停止する
4. `thumbnail.jpg` と `main.png/jpg` の確定検証結果を Phase 2c 成果物・再開契約へ thumbnail branch の結果として渡し、成功時だけメインが `uv run yt-workflow-state --collection "$COLLECTION_DIR" set-asset thumbnail true` を実行して、music branch の成果物検証へ進む

**`selection_only` または auto-selection 無効**（従来フロー）:

| auto_selection.enabled | approval_gates.thumbnail | 実行経路 |
|---|---|---|
| `true` (`selection_only`) | `true` / `false` | dry-run → `--apply` で最高得点候補を確定。候補承認質問だけ省略 |
| `false` | `true` | 候補を開き、人間の承認後に確定 |
| `false` | `false` | `yt-thumbnail-auto-select` は呼ばない。QA 合格候補を決定的順序（score 降順、同点はファイル名昇順）で先頭採用し、採用根拠を表示して確定 |

`enabled: false` は auto-select CLI の利用禁止であり、`approval_gates.thumbnail: false` は人間質問の省略である。この組み合わせを「CLI を実行して失敗」または「質問も選択もせず停止」と解釈しない。

1. サムネイルをプレビューで開く:
   ```bash
   open <collection-path>/10-assets/thumbnail-vN.jpg
   ```

2. `/thumbnail --compare` の 320px 視認性検証後、auto-selection 無効かつ `approval_gates.thumbnail: true` なら AskUserQuestion でテキスト付き候補の承認を求める。`selection_only` はこの質問だけを省略し、dry-run 成功後に `yt-thumbnail-auto-select --apply` で確定する。auto-selection 無効かつ approval gate も無効なら上表の決定的順序で確定する:
   ```
   question: "サムネイルを承認しますか？"
   options:
     - 承認する → `10-assets/thumbnail.jpg` に確定コピー → textless 候補生成へ
     - 再生成 → `/wf-new` のプレビュー段階で調整済みのため、diff_prompt を修正して `generate_image.py` で再生成
     - 中断 → ここで一旦停止（後で `/wf-next` で再開可能）
   ```

3. `textless.enabled` が未設定または `true` なら、承認済み `thumbnail.jpg` を入力に、生成対象 `main` を指定して別の subagent へ委譲する。メインが報告された textless 候補の存在と生成対象を検証し、候補をプレビューしてユーザー承認後に `10-assets/main.png/jpg` へ確定コピーする。`false` なら textless 候補生成・プレビュー・承認を省略し、`share_thumbnail_as_main.py <collection-path>` を実行して同一内容の通常ファイル `main.jpg` を確定する。
   - `thumbnail.jpg` と `main.png/jpg` を同一画像で代用しない。`main.png` を `thumbnail.jpg` にコピーする旧運用は禁止
   - QA が NG、再生成、または中断の場合は `/wf-new` または `/thumbnail` の該当生成ステップへ戻し、state を更新せず停止する

4. `thumbnail.jpg` と `main.png/jpg` の確定検証結果を Phase 2c 成果物・再開契約へ thumbnail branch の結果として渡し、成功時だけメインが `uv run yt-workflow-state --collection "$COLLECTION_DIR" set-asset thumbnail true` を実行する。このゲートで承認済みの `thumbnail.jpg` を再度 AskUserQuestion にかけない。

5. **join 後の branch 適用**:
   - メインが Suno の `suno-patterns.yaml` / `suno-prompts.json` / `yt-suno-verify` / semantic review、または Lyria の設計成果物を検証し、music branch の結果を Phase 2c 成果物・再開契約へ渡す
   - thumbnail / music の独立した結果は、メインが Phase 2c 成果物・再開契約どおり branch ごとに直列適用する。片側失敗時も成功側を確定・保持し、成功側は次回に再生成しない。失敗側だけを同じ collection の再開対象として表示して停止する

#### 2e. ループ動画生成

サムネイル承認後、`config/skills/loop-video.yaml::enabled` を確認する。

- `enabled: false` の場合: `/thumbnail --loop` は呼ばず、既定では textless `main.png/jpg` の静止画背景運用として続行する。`thumbnail::textless.enabled: false` では例外として文字入りの共有 `main.jpg` が正規入力である。owner CLI の `set-asset loop_video false`、続けて `set-phase prepared` を実行する
- `enabled` 未指定 or `true` の場合: Agent ツールで subagent を起動し、`main.png/jpg` を入力、`10-assets/loop.mp4` を期待成果物として `/thumbnail --loop` の生成だけを委譲する。`thumbnail::textless.enabled: false` の共有 `main.jpg` も正規入力として渡す
  - 成功: メインが `loop.mp4` の存在を確認後、owner CLI の `set-asset loop_video true`、続けて `set-phase prepared` を実行する
  - 失敗または欠落: state は更新せず、同じ loop-video 委譲から再試行できる状態で停止する

#### 2f. Suno helper server 起動（Suno のみ）

`/music --prompt` が生成した `20-documentation/suno-prompts.json` を Chrome 拡張へ配信するため、`.claude/skills/extension/references/serve.md` を読み、`--suno` の既存 server 再利用・起動・疎通確認契約を直接実行する。`/extension` skill へ委譲せず、server lifecycle のコマンドや判定を本 reference に複製しない。

起動または疎通確認に失敗しても、server は state を更新しない独立した補助工程なので、検証・更新済みの `phase = "prepared"` は維持する。失敗内容、共有契約が返した log path と再開方法を完了ガイダンスに出す。Suno UI での連続生成、playlist 追加、ZIP 一括 DL は `/music --generate` の browser use 主導フローで実行する。

#### 2g. 完了ガイダンス

```
`/wf-new` 完了！

コレクション: <collection_name>
テーマ: <theme>
トラック数: <track_count>
音楽エンジン: <suno|lyria|minimax>
ディレクトリ: collections/planning/YYYYMMDD-<short>-<theme>-collection/
現在のフェーズ: prepared
ループ動画: ✅ 生成済み / ⚠️ 失敗（`/wf-next` で再試行可能）
Suno-helper server: ✅ http://<channel>.localhost:<PORT> 起動済み / ⚠️ 未起動（Suno の場合のみ）
```

音楽エンジンに応じた次ステップ案内:
- **Suno**: 「suno-helper server は `http://<channel>.localhost:<PORT>` で起動済みです。次は `/music --generate` を実行し、browser use で Suno Custom Mode を開いて、suno-helper overlay / popup のローカル配信元からこのチャンネルを選び、対象 collection を選んで連続実行してください。全件完了で playlist 一括追加 + ZIP 一括 DL まで自動。完了後に `/wf-next` を実行（plain Suno UI への手動投入は非推奨）」
- **Lyria**: 「`/wf-next` を実行すると Lyria 3 API が呼ばれ、コレクション尺に応じてセグメントが生成されます → ミキシング+マスタリング後に再度 `/wf-next`」

**重要**: `/wf-new` が自動で行うのは Suno 用ローカル server の起動と疎通確認まで。`/music --generate` のブラウザ実行（Chrome + Suno ログイン確認 + 拡張 overlay / popup 操作 + 連続実行開始）は、次工程の `/music --generate` が browser use 主経路で進める。ログイン、CAPTCHA、拡張未ロードなどの handoff 条件は `/music --generate` 側の判断基準に従う。
