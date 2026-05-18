# 観点 3: 失敗時挙動 / Idempotency / リカバリ — 再調査レポート (A-1)

**調査日**: 2026-05-18
**担当ステップ**: `dig.part-a1-failure-recovery`
**作業ディレクトリ**: `/Users/mba/02-yt/takt-worktrees/20260518T0905-372-issue-372-chore-skills-sukiru`
**対象**: `.claude/skills/**`（35 skill）+ `src/youtube_automation/**` 実装
**前提**: PR #367 で扱った「汎用化・整合性」、および Part B `data-security-secrets.md` の論点は除外。本書は「運用時に痛い失敗系」のみを扱う。
**スキル数の検証**: `find .claude/skills -name SKILL.md` で 35 件、`ls .claude/skills/` で 35 件、一致を確認した。

---

## 0. severity 別サマリー

| severity | 件数 | 概要 |
|---|---|---|
| **P0** | 5 | 再実行で課金/quota が即痛む or 二重投稿の経路があるもの |
| **P1** | 8 | リカバリ手順未記載 / partial 状態の管理が弱い |
| **P2** | 6 | tmp 残骸・set -e 不在・cosmetic な atomicity |
| **P3** | 3 | 推奨はあるが運用負債は軽い |

合計 22 件（既存 11 件 + 新規検出 11 件）。重複は除外。

---

## 1. 観点 3.1 — 「リカバリ手順」記載監査

全 35 件の SKILL.md / references を grep + 目視で確認した。`grep -lE "リカバリ|失敗時|再実行|途中で|resume|再開できる|trap|エラー時|失敗したら|途中で中断"` のヒットは 13 件、ただしヒットしただけで「リカバリ手順」として機能する記述があるかは別問題。

### 1.1 評価マトリクス（35 skill 全件）

| skill | 評価 | 主たる出典 | 備考 |
|---|---|---|---|
| alignment-check | △ | `.claude/skills/alignment-check/SKILL.md:85-94` | 不整合検出時に **他 skill を再実行する** フィードバックループは記載。alignment-check 自体の失敗時手順は無し |
| analytics-analyze | × | — | OAuth/quota/JSON 破損のリカバリなし |
| analytics-collect | × | — | OAuth 失敗時の再認証案内なし |
| analytics-report | × | — | レポート JSON 壊れた時の対処なし |
| audience-persona | × | — | — |
| benchmark | △ | `src/youtube_automation/scripts/benchmark_collector.py:75-93` | コード側に **`freshness_days` による再収集ガード** あり。SKILL.md には未記載 |
| channel-direction | × | — | — |
| channel-import | × | — | OAuth/API 失敗の対処なし |
| channel-new | △ | `.claude/skills/channel-new/SKILL.md:86` 周辺 | GCP bootstrap は `channel-setup` 参照のみ |
| channel-research | × | — | — |
| channel-setup | ○ | `.claude/skills/channel-setup/SKILL.md:61` + `.claude/skills/channel-setup/references/gcp-bootstrap.md:84-94` | billing 未紐付け / IAM 403 / tfstate 壊れ / quota project ズレを表で整理 |
| channel-status | × | — | — |
| collection-ideate | △ | `.claude/skills/collection-ideate/SKILL.md:72` | `reports/` が stale なら中断指示はあるが、画像生成中断のリカバリなし |
| comments-reply | ○ | `.claude/skills/comments-reply/SKILL.md:62-66` + `src/youtube_automation/utils/comments/history.py:51-58` | dry-run 必須化 + atomic save の二段構え |
| discover-competitors | × | — | quota 超過時のリカバリ手順なし（HttpError は `YouTubeAPIError` で raise しっぱなし、`competitor_discovery.py:57-58`） |
| live-clean | × | — | 大容量削除中断時の手順なし |
| loop-video | △ | `.claude/skills/loop-video/SKILL.md:59` | 「`--smooth` で再実行」とあるが、後述のとおりこれは **Veo 再課金経路** |
| lyria | ○ | `.claude/skills/lyria/SKILL.md:169` + `src/youtube_automation/scripts/generate_lyria_master.py:384` | 「成功済みセグメントは保持されています。再実行で続行できます」と明示。実装も裏付け済み |
| masterup | △ | `.claude/skills/masterup/SKILL.md:130` | rain layer の atomic rename のみ言及。Suno DL 中断・`master.{mp3,wav}` 再生成挙動の記述なし |
| metadata-audit | × | — | — |
| playlist | △ | `.claude/skills/playlist/SKILL.md:50-54` | dry-run 案内はあるが、init 途中失敗時の手順は記述なし。実装は idempotent（`playlist_manager.py:144-145` の既存 ID skip + `:168-181` の書き戻し） |
| postmortem | △ | `.claude/skills/postmortem/SKILL.md:23-25` | `/analytics-collect` への送り返し案内のみ |
| streaming | ○ | `.claude/skills/streaming/SKILL.md:101-128` | §4 トラブルシュート表（7 行）+ §5 `terraform destroy` を明示 |
| suno | △ | `.claude/skills/suno/SKILL.md:314` | **冪等性を明示**（`planning.music` を上書き、merge しない）— ただし楽曲生成中断のリカバリは Web UI 側で対象外 |
| thumbnail | △ | `.claude/skills/thumbnail/SKILL.md:183` 付近 | 「2〜3 回リトライで通る」のみ。`-vN` 自動採番は実装側で対応（`composition.py:81-99`） |
| thumbnail-compare | × | — | — |
| video-analyze | △（コードのみ） | `src/youtube_automation/scripts/video_analyze.py:243-261` | `_run_analysis` が 1 件ずつ try/except で失敗を `failures[]` に積む。**SKILL.md には記述なし**、かつ既存 JSON skip も無し（後述 3.3） |
| video-description | × | — | — |
| video-upload | ○ | `.claude/skills/video-upload/SKILL.md:96-98` | `upload_tracking.json` v3 schema による resume + exponential backoff 5 回まで明示 |
| videoup | △ | `.claude/skills/videoup/SKILL.md:59` + `generate_videos.sh:125` | **`set -e` は使用しない（明示的エラーハンドリング）と明記** + `trap 'rm -f "$PROGRESS_FILE"' EXIT` あり。SKILL.md にリカバリ手順は薄い |
| viewer-voice | × | — | — |
| viewing-scene | × | — | — |
| wf-new | △ | `.claude/skills/wf-new/SKILL.md:80-81` | Gemini 呼び出し失敗時の `/wf-next` 再実行案内のみ |
| wf-next | ○ | `.claude/skills/wf-next/SKILL.md:8,60` | 「`workflow-state.json` を更新し、途中で中断しても同じ状態から再開できる」を skill 全体の主軸として明示 |
| wf-status | n/a | — | read-only のためリカバリ不要（skip 妥当） |

### 1.2 集計

- **○（明確な手順あり）**: 6 件 — channel-setup, comments-reply, lyria, streaming, video-upload, wf-next
- **△（断片的言及、または実装にはあるが SKILL.md 未記載）**: 13 件 — alignment-check, benchmark, channel-new, collection-ideate, loop-video, masterup, playlist, postmortem, suno, thumbnail, video-analyze, videoup, wf-new
- **×（記載なし）**: 15 件 — analytics-analyze, analytics-collect, analytics-report, audience-persona, channel-direction, channel-import, channel-research, channel-status, discover-competitors, live-clean, metadata-audit, thumbnail-compare, video-description, viewer-voice, viewing-scene
- **n/a**: 1 件 — wf-status

### 1.3 既存レポートとの差分

既存 `data-failure-recovery.md` は ×=21 件と評価していたが、以下を再分類した:

- **suno** → ×→△（`SKILL.md:314` で冪等性明示を発見）
- **benchmark** → ×→△（コード側に `freshness_days` ガードが存在）
- **alignment-check** → ×→△（`:85-94` で再実行スキル表を発見）
- **videoup** → ×→△（`SKILL.md:59` の「`set -e` は使用しない（明示的エラーハンドリング）」が**意図的設計**であることを発見。trap も `:125` で存在）

逆に、既存レポートが「○」とした `comments-reply` には史実上は窓があり（後述 3.3）。

### 1.4 P1 案件: SKILL.md にリカバリ手順がない skill 群

| skill | 失敗想定シナリオ | 副作用 | severity |
|---|---|---|---|
| analytics-collect | OAuth token 期限切れ / Reporting API 429 | `data/analytics_*.json` が中途半端なまま残る | P1 |
| analytics-analyze | 入力 JSON が中途半端 | レポートが嘘の数字を出す | P1 |
| analytics-report | 古いレポートを誤読 | 意思決定が腐ったデータで動く | P2 |
| channel-import | OAuth/Branding API 失敗 | `config/channel/*.json` が中途半端な分割で残る | P1 |
| discover-competitors | search.list quota 切れ | 結果 CSV/MD が部分書き込み | P1 |
| live-clean | 大容量 unlink 中の SIGINT | 50% 削除されたコレクションが残る | P1 |
| metadata-audit | YouTube API 失敗 | 監査結果が偽陰性 | P2 |
| video-description | Gemini quota | descriptions.md が中途半端 | P1 |
| thumbnail-compare | 画像 fetch 失敗 | 比較レポートが穴あき | P2 |
| viewer-voice | コメント取得 quota | 取得済み分のみで分析される（=サンプル偏り） | P2 |

---

## 2. 観点 3.2 — 部分生成物のクリーンアップ責任

### 2.1 実装側の tmp/partial 処理

| 検出箇所 | パターン | 評価 |
|---|---|---|
| `src/youtube_automation/utils/comments/history.py:51-58` | `tmp = path.with_suffix(suffix + ".tmp")` → `os.replace(tmp, path)` | ○ atomic rename。中断時は `*.tmp` 残骸の可能性はあるが本体は無傷 |
| `src/youtube_automation/scripts/finalize_master.py:286-294` | `try/finally` で `master.tmp.mp3` を unlink。「主目的の master.mp3 はこの時点で無傷」コメント | ○ 例外経路含めて掃除責任明示 |
| `src/youtube_automation/scripts/generate_lyria_master.py:89-113` | `tmp_path = path.with_suffix(suffix + ".tmp")` + try/finally の `if tmp_path.exists(): tmp_path.unlink()` | ○ ffmpeg 失敗時に MP3 tmp を掃除 |
| `src/youtube_automation/utils/veo_generator.py:120-132` | `strip_audio` で `_tmp.mp4` 作成。CalledProcessError 経路で `tmp.unlink()` | ○ |
| `src/youtube_automation/utils/veo_generator.py:159-174` | `trim_tail` で `_trimmed.mp4` 作成。CalledProcessError 経路で `tmp.unlink()` | ○ |
| `src/youtube_automation/utils/veo_generator.py:177-253` | `smooth_loop` で `_smooth.mp4` 作成。**CalledProcessError 経路で `return False` のみ、unlink 無し**（`:242-244`）| × **P2 残骸あり** |
| `src/youtube_automation/utils/upload_core.py:179-201` | `tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)` でサムネ圧縮 tmp。正常系のみ `:162-163` で unlink。ffmpeg 失敗時の cleanup が `_compress_thumbnail` 内に無い | △ **P2 残骸あり** |
| `src/youtube_automation/scripts/generate_master.py:220-256` | `ffmpeg -y ... output -loglevel error`。**出力 master.{mp3,wav} は無条件上書き**。残骸という概念がそもそも存在しない（同名で潰す） | △ idempotency 観点で別問題（後述 3.3） |
| `src/youtube_automation/scripts/generate_loop_video.py:59-67` | 既存 `loop.mp4` を `loop-v{n}.mp4` に**rename して退避**してから新規生成。Veo 失敗時は退避済み旧 mp4 + 新規未生成という状態に | △ **退避は idempotent だが旧版が永遠に残る** |
| `src/youtube_automation/utils/veo_generator.py:246-249` | smooth_loop 成功時、元 mp4 を `_raw` にバックアップ + `_smooth` を本体に rename | ○ atomic rename 相当 |

### 2.2 Shell scripts の trap / set -e

実測（`grep -lnE "set -e|trap "` で全件確認）:

| ファイル | フラグ | 評価 |
|---|---|---|
| `.claude/skills/streaming/references/notify.sh:14` | `set -euo pipefail` | ○ |
| `.claude/skills/streaming/references/healthcheck.sh:15` | `set -euo pipefail` | ○ |
| `.claude/skills/streaming/references/swap_video.sh:18` | `set -euo pipefail` | ○ ただし terraform apply 中断時の rollback は無記述 |
| `.claude/skills/streaming/references/run-ffmpeg.sh:23` | `set -eu`（pipefail なし） | △ |
| `.claude/skills/lyria/references/worktree_sync.sh:16` | `set -euo pipefail` | ○ rsync は idempotent |
| `.claude/skills/channel-setup/references/gcp-bootstrap.sh:36` | `set -euo pipefail`、trap なし | △ 途中失敗時に部分作成 GCP リソース残骸（API 有効化済み / billing 未紐付け 等） |
| `.claude/skills/channel-setup/references/gcp-terraform-apply.sh:13` | `set -euo pipefail`、trap なし | △ terraform state が中途半端の可能性 |
| `.claude/skills/videoup/references/generate_videos.sh:125` | **`set -e` なし**（意図的、`videoup/SKILL.md:59` で明記）+ `trap 'rm -f "$PROGRESS_FILE"' EXIT` | ○ 明示エラーハンドリング設計。`exit 1` を個別箇所で呼ぶ |

### 2.3 YouTube 側の部分生成物

| skill | 中途半端な状態 | 掃除責任の所在 |
|---|---|---|
| `video-upload` | resumable upload 中断後、再実行は **新規 insert になる**（後述 3.3） | YouTube 側の死蔵 video_id を掃除する仕組みは無い |
| `comments-reply` | API insert 成功直後 → `history.save()` 失敗（極めて稀） | atomic save で防御済みだが、`replier.py:243-245` の窓は理論上残る |
| `playlist --init` | 一部 playlist 作成成功 + 残り失敗 | `playlist_manager.py:163-181` の書き戻しで idempotent（再実行で残りだけ作る）|
| `lyria` | `02-Individual-music/{NN}_{name}.wav` が一部完成 | `generate_lyria_master.py:137-138` で既存 skip = resume |
| `loop-video` | Veo 生成失敗時の空 mp4 | `:59-67` で旧版を `loop-v{n}.mp4` にリネームしたあとで失敗するため、**新 loop.mp4 は未生成のまま残らない**（write_bytes 失敗で例外）。次回実行で再度 backup が走る → `loop-v{n}` が無限に増殖する余地あり |
| `streaming terraform apply` | VPS 作成失敗 | `streaming/SKILL.md:120-127` の destroy 案内のみ。state ロックで再実行ブロックの可能性は記述なし |

---

## 3. 観点 3.3 — 二重生成 / 二重投稿リスク

「同じコマンドを 2 回叩いたら何が起きるか」を skill ごとに 1 行で判定。

### 3.1 skill × idempotency マトリクス（35 件）

| skill | 2 回叩いた時の挙動 | 二重実行ガード | severity |
|---|---|---|---|
| alignment-check | レポート上書き（読み取り中心） | n/a | safe |
| analytics-analyze | レポート上書き | n/a | safe |
| analytics-collect | 新規 timestamp JSON | スナップショット型なので冪等 | safe |
| analytics-report | n/a（参照のみ） | — | safe |
| audience-persona | 上書き | — | safe |
| benchmark | `freshness_days` 内なら skip、超過したらマージして上書き | `benchmark_collector.py:75-93` | P3 ○ |
| channel-direction | 上書き | — | safe |
| channel-import | **YouTube branding API 二重 push の可能性**。コード未確認 | 不明 | P2 |
| channel-new | リポジトリ scaffold は git で守られる | — | safe |
| channel-research | レポート上書き | — | safe |
| channel-setup | **GCP bootstrap は部分実行を許容**（API 有効化は idempotent、project create のみ`--create` ガード） | `gcp-bootstrap.sh:90-94` | P3 △ |
| channel-status | API 読み取りのみ | — | safe |
| collection-ideate | 上書き | — | safe |
| comments-reply | `history.has_replied()` で skip。**ただし `replier.py:213-243` の window で `comments.insert` 成功直後 `history.save()` 失敗なら理論上の二重返信余地** | `comments/history.py:45-58` | P3 △ |
| discover-competitors | 結果ファイル上書き。**search.list を毎回叩く（quota 660 units/run）** | 無 | **P1** quota 焼き |
| live-clean | 既に削除済みファイルは skip | — | safe |
| **loop-video** | **既存 `loop.mp4` を `loop-v{n}.mp4` に rename して退避 → Veo 再課金で新規生成**。`--smooth` 単独で再エンコードだけ走らせる経路なし（`generate_loop_video.py:160-163` で `generate_loop_video()` が無条件で先行） | 無（バックアップだけ） | **P0** Veo 課金 |
| lyria | 既存セグメント skip = resume | `generate_lyria_master.py:137-138` | ○ |
| **masterup** | `yt-generate-master` は `ffmpeg -y` で **`master.{mp3,wav}` 無条件上書き**（`generate_master.py:220-256`）。yt-finalize-master は `master.tmp.mp3` 経由 atomic rename | △ 上書きするだけで二重課金ではない（ローカル ffmpeg）| P2 |
| metadata-audit | 読み取りのみ | — | safe |
| playlist --init | 既存 playlist_id を skip + 書き戻し | `playlist_manager.py:144-145,168-181` | ○ |
| playlist --assign | `_list_playlist_video_ids` で既存チェック | `playlist_manager.py:255-260` | ○ |
| postmortem | レポート上書き | — | safe |
| release | git tag / npm version で衝突 → エラー | — | ○ |
| pr | gh が同名 PR で 422 | — | ○ |
| streaming swap | `null_resource.deploy.triggers.video_hash = filemd5(...)` で hash 不変なら no-op | `streaming/SKILL.md:63,134` | ○ |
| suno | `planning.music` を **merge せず上書き**（明示的に冪等）。Suno UI 側の楽曲生成は人手なので skill 範囲外 | `suno/SKILL.md:314` | ○ |
| thumbnail | `resolve_unique_path()` で `-vN` 自動採番（`-y`/`yes=True` 時）。対話モードは上書き確認プロンプト | `composition.py:81-99,223-253` | ○ |
| thumbnail-compare | レポート上書き | — | safe |
| **video-analyze** | **同一 `<video_id>.json` の存在チェックなし**（`video_analyzer.py:79-104`）。`--top 5` を 2 回叩くと 10 動画分 Gemini に再課金 | 無 | **P1** Gemini 課金 |
| video-description | Gemini で descriptions.md 上書き | — | △ |
| **video-upload** | `upload_tracking.json` の `status == "completed"` で `already_completed` 分岐（`collection_uploader.py:273-282`）。**ただし `failed` 状態からの再実行は新規 insert になる**（`_resumable_upload` 内で session URI を永続化していない、`upload_core.py:108-128`） | △ | **P0** video_id 重複の余地 |
| videoup | `MASTER_OUTPUT` を `ffmpeg -y` で無条件上書き。既存版退避なし | 無 | P2（過去版が残らない）|
| viewer-voice | レポート上書き | — | safe |
| viewing-scene | レポート上書き | — | safe |
| wf-new | workflow-state.json 初期化のみ。既存があればスキップ判定はコード次第（未確認） | △ | P2 |
| wf-next | workflow-state.json の `status` で次ステップ自動判定 = resume 設計の核 | `wf-next/SKILL.md:8,60` | ○ |
| wf-status | 読み取りのみ | — | safe |

### 3.2 仮説検証

**H1: `loop-video` 再実行で Veo 二重課金**
**結論: 確認済み（P0）**。`generate_loop_video.py:59-67` は既存 `loop.mp4` を `loop-v{n}.mp4` に rename するだけで skip しない。`main()` は `generate_loop_video()` を無条件で先行呼び出し（`:160`）、その後にだけ `--smooth` 経由で `smooth_loop()` を呼ぶ。**`--smooth` 単独で「Veo は呼ばずローカル ffmpeg 補正だけ」という経路はソース上に存在しない**。SKILL.md `:59` の「`--smooth` で再実行」案内は **Veo 再課金を前提とした文言**であり、想定外コストになりうる。

**H2: `comment_reply_history.json` 競合で二重返信**
**結論: 実装的に防御済み（P3）。** `history.py:51-58` で `os.replace` による atomic save、`replier.py:243-245` で 1 件 insert ごとに save。並列実行は `max_replies_per_run` で抑制。残る理論的な窓は `comments.insert` 成功 → `history.save()` プロセス死。極めて稀だが「絶対に二重投稿しない」とは言えない。

**H3: video-upload の resumable upload 再開で video_id 重複**
**結論: 部分的に検証 — 重複の余地あり（P0）。** `upload_tracking.json` v3 は `complete_collection.status="completed"` 後の二重実行を防ぐ。しかし `_resumable_upload` 内で **`insert_request` を作り直して chunk を打ち直す**設計（`upload_core.py:67-78`）で、**resumable upload session URI を永続化していない**。
- 結果: resumable upload 中断（ネットワーク断 / CLI Ctrl+C 等）→ 再実行は新規 `videos().insert()` になる
- YouTube 側で前回 chunk が finalize 済みだった場合: video_id が **2 つ生成され、片方は description ない / private のまま死蔵**
- finalize されていなかった場合: video_id は 1 つだけ生成され問題なし
- どちらに転ぶかはネットワーク中断点に依存する

**H4: video-analyze 再実行コスト**
**結論: 確認済み（P1）。** `video_analyzer.py:79-104` の `analyze_url` は `save_json()` で `<video_id>.json` を上書きするだけ。既存ファイル skip ロジックなし。CLI `_run_analysis` も `target` ループの先頭で skip 判定をしていない（`video_analyze.py:243-261`）。`--top 5` を 2 回叩けば 10 動画分の Gemini API call が課金される。

**H5: lyria 再実行コスト**
**結論: 否定 — resume 設計（safe）。** `generate_lyria_master.py:137-138` で `seg_path.exists()` ガード。

**H6: masterup 再実行で `master.{mp3,wav}` が上書きされる**
**結論: 確認済み（P2）。** `generate_master.py:220-256` は `ffmpeg -y` で出力を無条件上書き。ローカル ffmpeg なので二重課金ではないが、ユーザーが過去版を保護したい場合の退避は **呼び出し側の責任**。SKILL.md `:100-118` に注意書きなし。

---

## 4. 観点 3.4 — リトライ・バックオフ・quota 例外

### 4.1 retry 装着マトリクス

| 対象 | リトライ | バックオフ | 上限 | 429 / quota |
|---|---|---|---|---|
| `upload_core._resumable_upload` `:108-128` | ○ | ○ `2^attempt` 秒（`upload_policy.py:53`）| 5 回 | × **429 は `RETRYABLE_HTTP_STATUSES = {500,502,503,504}` に含まれず即 abort**（`upload_policy.py:14,47-50`）|
| `image_provider/gemini.py:57-110` | ○ | ○ `RETRY_BACKOFF=(10,30,60)` | 3 回（`base.py:14`）| △ SAFETY/RECITATION のみ即 skip、他は全例外 retry |
| `image_provider/openai.py:88-134` | ○ | ○ 同上 | 3 回 | △ ConfigError のみ即 raise、他は全例外 retry |
| `lyria_client.generate_music` `:138-154` | × | — | 1（単発） | × `requests.RequestException` で None 返却 / response.ok 否なら None |
| `generate_lyria_master._generate_one_segment` `:143-147` | ○ | ○ `min(30, 10 * attempt)` | `--max-retries` (default 3) | △ 何でも retry（quota も） |
| `veo_generator.generate_loop_video` `:46-115` | × | — | 1 | × ポーリング中断もタイムアウト 600 秒のみ |
| `populate_scene_phrases._generate_with_retry` `:74-87` | ○ | ○ `_RETRY_BACKOFF_SEC` | `_RETRY_MAX` | △ 「一過性 429/503 に備えた」コメント明示 |
| `analytics_collector` `:80-92` | × | — | — | × `raise` のみ |
| `benchmark_collector` API call 一式 | × | — | — | × ServiceRegistry 経由で直 `.execute()` |
| `playlist_manager` API call | × | — | — | × |
| `comments-reply` `comments.insert` `:213-231` | × | — | — | × **HttpError を `errors[]` に積むだけ** |
| `youtube_service.get_youtube` | n/a | — | — | n/a service factory のみ |
| `competitor_discovery._search_channels` `:46-58` | × | — | — | × HttpError を `YouTubeAPIError` で raise |
| `video_analyzer.analyze_url` `:79-95` | × | — | — | × Gemini API 単発呼び出し |

### 4.2 評価

- **YouTube Data API 系（playlist, benchmark, analytics, comments-reply, discover-competitors, channel-import 推定）は retry ゼロ**。429 / 503 で即失敗 → ユーザーが手動再実行 → quota 焼き続ける
- **Gemini / OpenAI 画像生成は 3 回 retry**（reasonable、上限 backoff 60 秒）
- **Lyria は client 単発 + CLI 側で 3 回 retry**（バックオフ最大 30 秒）
- **Veo は client 単発、retry 一切なし**。タイムアウト 600 秒のみ
- **upload_core が 429 を非リトライ扱い** は **P0 級**。quota 切れ寸前のチャンネルで `video-upload` を叩くと resume 不可能な失敗になる

### 4.3 shell script の `set -euo pipefail` 装着

- `gcp-bootstrap.sh` / `gcp-terraform-apply.sh` / `healthcheck.sh` / `notify.sh` / `swap_video.sh` / `worktree_sync.sh`: **`set -euo pipefail`** あり
- `run-ffmpeg.sh:23`: `set -eu`（pipefail なし）
- `generate_videos.sh`: **意図的に `set -e` なし**（`videoup/SKILL.md:59` で明記）+ trap で `PROGRESS_FILE` 掃除

---

## 5. 観点 3.5 — SIGINT / SIGTERM ハンドリング

### 5.1 KeyboardInterrupt 捕捉箇所（grep 全件）

| 対象 | 場所 | 挙動 |
|---|---|---|
| `auth/oauth_handler.py:295-296` | OAuth flow | UNIX 慣例 128+SIGINT=130 で exit |
| `agents/collection_uploader.py:450-457` | daemon ループ | `Scheduler 停止` ログ出して終了 |
| `agents/collection_uploader.py:514-515` | 手動実行 entry | `処理が中断されました` 出して exit |
| `agents/youtube_auto_uploader.py:495` | CLI entry | KeyboardInterrupt 捕捉あり |
| `scripts/playlist_status.py:94` | playlist status CLI | KeyboardInterrupt 捕捉 |
| `scripts/playlist_manager.py:461` | playlist CLI | KeyboardInterrupt 捕捉 |
| `utils/analytics_collector.py:140-141` | analytics CLI | `分析が中断されました` |
| `utils/image_provider/composition.py:73-77` | confirm_cost 入力 | EOFError + KeyboardInterrupt で False |
| `utils/image_provider/composition.py:245-250` | 上書き確認 | EOFError + KeyboardInterrupt で None |

### 5.2 SIGINT が問題になる長時間処理

| 対象 | 問題 |
|---|---|
| `veo_generator.generate_loop_video` `:64-77` | **POLL 中の Ctrl+C で例外発生**。`time.sleep(POLL_INTERVAL_SEC)` 中断 → スタックトレースで死亡。**Veo Operation は API 側で続行する**（クライアントの中断は API call をキャンセルしない）= **API は完走しクレジット消費、結果は受け取らない**（**最悪コスト**）|
| `lyria_client.generate_music` `:138-141` | `requests.post` の `_TIMEOUT_SEC=300` 中の Ctrl+C で例外。tmp ファイル `.tmp` は `_save_audio_as_wav` 内 try/finally で unlink（`generate_lyria_master.py:111-113`）。**API call そのものは 1 リクエスト ≒ 完了 or 失敗で billing が確定するが、Ctrl+C はその後の保存処理だけを止める** |
| `gemini.py:57-110` / `openai.py:88-134` | 画像生成 API call 中の Ctrl+C で例外。retry 待機 `time.sleep(backoff)` 中なら復帰しない |
| `streaming swap_video.sh` | `terraform apply` 中の SIGINT → ローカル `terraform.tfstate` に partial state 書き込み。Vultr 側は API 完了済みリソースだけ残る = state lock or drift |
| `generate_videos.sh` | `PROGRESS_FILE` は `trap EXIT` で掃除されるが、**ffmpeg 子プロセスが SIGINT で kill されると `MASTER_OUTPUT` が partial mp4 として残る**（unlink 無し） |
| `live-clean` | unlink 中断時の手順なし。`SKILL.md` 未確認 |
| `analytics-collect` | 取得中の中断で `data/analytics_*.json` の部分書き込みは無いはず（json.dump は 1 file write）。Reporting API の paged fetch 途中なら次回 raw_data 不整合の可能性 |

### 5.3 評価

- **shell script は trap / `set -e` でそれなりに固まっている**
- **Python の長時間 API call で signal handler を入れている箇所は皆無**（`signal.signal` で grep して 0 件確認）
- **Veo の SIGINT 中断は API 側継続のため最悪コスト**。Ctrl+C で「あ、止めよう」と思っても課金は走る
- **terraform 系は中断時の rollback / unlock 案内が SKILL.md に無い**

---

## 6. skill × idempotency マトリクス（35 件まとめ・1 行判定）

| # | skill | 2 回叩いたら | severity |
|---|---|---|---|
| 1 | alignment-check | レポート上書き、副作用なし | safe |
| 2 | analytics-analyze | レポート上書き | safe |
| 3 | analytics-collect | timestamp 別 JSON、毎回新規 | safe |
| 4 | analytics-report | 表示のみ | safe |
| 5 | audience-persona | レポート上書き | safe |
| 6 | benchmark | freshness ガード + マージ書き | safe |
| 7 | channel-direction | レポート上書き | safe |
| 8 | channel-import | branding API 上書き（リスク残） | P2 |
| 9 | channel-new | git scaffold | safe |
| 10 | channel-research | レポート上書き | safe |
| 11 | channel-setup | gcloud は idempotent、project create は --create ガード | safe |
| 12 | channel-status | 読み取りのみ | safe |
| 13 | collection-ideate | レポート上書き | safe |
| 14 | comments-reply | history で skip、稀に窓 | P3 |
| 15 | discover-competitors | quota 660 units を毎回焼く | **P1** |
| 16 | live-clean | 削除済みは skip | safe |
| 17 | loop-video | **Veo を毎回再課金** | **P0** |
| 18 | lyria | 既存セグメント skip = resume | safe |
| 19 | masterup | master.{mp3,wav} 無条件上書き | P2 |
| 20 | metadata-audit | 読み取りのみ | safe |
| 21 | playlist | 既存 ID + 既存 video skip | safe |
| 22 | postmortem | レポート上書き | safe |
| 23 | release | npm version 衝突 = エラー | safe |
| 24 | pr | gh が 422 で阻止 | safe |
| 25 | streaming swap | filemd5 不変なら no-op | safe |
| 26 | suno | `planning.music` を上書き | safe |
| 27 | thumbnail | -vN 自動採番 | safe |
| 28 | thumbnail-compare | レポート上書き | safe |
| 29 | video-analyze | **Gemini を毎回再課金** | **P1** |
| 30 | video-description | Gemini 再課金 + descriptions.md 上書き | P2 |
| 31 | video-upload | completed なら skip、failed→success で **video_id 重複の余地** | **P0** |
| 32 | videoup | MASTER_OUTPUT 無条件上書き | P2 |
| 33 | viewer-voice | レポート上書き | safe |
| 34 | viewing-scene | レポート上書き | safe |
| 35 | wf-new | 既存検出は要確認 | P2 |
| - | wf-next | status で resume | safe |
| - | wf-status | 読み取りのみ | safe |

---

## 7. 注意点・リスク

### 7.1 P0 — 運用直撃

| # | 件名 | 引用 | リスク |
|---|---|---|---|
| 1 | **`loop-video` 再実行は Veo を必ず再課金** | `generate_loop_video.py:59-67,160-163` + `SKILL.md:59` | 「`--smooth` で再実行」の案内が **API 再課金経路** に直結。Veo は 1080p 8 秒で **数百円 / 件オーダー** |
| 2 | **`upload_policy.RETRYABLE_HTTP_STATUSES` に 429 が含まれない** | `upload_policy.py:14,47-50` | quota 切れ寸前で `video-upload` を叩くと resume 不可能な panic 終了 |
| 3 | **Veo の Ctrl+C 中断は API 側継続でクレジット焼き** | `veo_generator.py:64-77` | 中断したつもりが課金は走る |
| 4 | **`video-upload` 失敗 → 再実行で video_id 重複の余地** | `upload_core.py:108-128` resumable session URI 未永続化 | YouTube 側に死蔵 video_id（private / no description）が残る |
| 5 | **`comments-reply` の `comments.insert` 成功直後 history.save 失敗の窓** | `replier.py:213-243` + `history.py:51-58` | 理論上の二重返信余地（極めて稀だが「絶対に出ない」とは言えない）|

### 7.2 P1 — 重要

| # | 件名 | 引用 |
|---|---|---|
| 6 | 35 skill 中 15 件で SKILL.md にリカバリ手順が**完全に**無い | §1.2 |
| 7 | `video-analyze` の既存 JSON skip なし → 再実行で Gemini 再課金 | `video_analyzer.py:97-104` |
| 8 | `discover-competitors` は実行ごとに search.list（quota 660 units）を毎回焼く | `competitor_discovery.py:46-67` |
| 9 | YouTube Data API 系（playlist, benchmark, analytics, comments-reply, discover-competitors）の API call が **retry 一切なし** | §4.1 |
| 10 | `live-clean` の SIGINT 時のリカバリ未記述（途中削除されたコレクション残骸）| SKILL.md 確認 |
| 11 | `analytics-collect` の OAuth token 期限切れ時のリカバリ手順未記述 | SKILL.md 確認 |
| 12 | `streaming swap_video.sh` の terraform apply 中断時の rollback / state unlock 案内なし | `swap_video.sh:18-122` |
| 13 | `loop-video` のバックアップ `loop-v{n}.mp4` が無限増殖の可能性（rotation なし） | `generate_loop_video.py:59-67` |

### 7.3 P2 — あれば良い

| # | 件名 | 引用 |
|---|---|---|
| 14 | `smooth_loop` の `_smooth.mp4` tmp が CalledProcessError 経路で unlink されない | `veo_generator.py:242-244` |
| 15 | `_compress_thumbnail` の `tempfile.NamedTemporaryFile(delete=False)` が ffmpeg 失敗時に残骸化する経路あり | `upload_core.py:179-201` |
| 16 | `gcp-bootstrap.sh` の途中失敗で中途半端な GCP リソース残骸（API 有効化済み・billing 未紐付け 等） | `gcp-bootstrap.sh:36-103` |
| 17 | `videoup/generate_videos.sh` が `MASTER_OUTPUT` を `ffmpeg -y` で無条件上書き（過去版退避なし） | `generate_videos.sh:160-180` |
| 18 | `masterup` の `yt-generate-master` も `master.{mp3,wav}` を `ffmpeg -y` で無条件上書き | `generate_master.py:220-256` |
| 19 | `channel-import` の二重実行で branding API が上書きする可能性（未検証）| `cli/channel_init.py` |

### 7.4 P3

| # | 件名 |
|---|---|
| 20 | suno `:314` の冪等性明示は他 skill のお手本になる |
| 21 | benchmark の `freshness_days` ガードを SKILL.md に書き出すと運用者の認知負荷が下がる |
| 22 | wf-next の resume 設計は強い。他 skill にも同じ書き方を展開できる |

---

## 8. 調査不可項目

1. **Suno Web UI からの DL 中断時挙動**: Suno はブラウザ DL のみで API 提供なし。skill 側に記述は要るが、実装側調査は不能
2. **Vertex AI / Lyria の 429 詳細**: 実際の rate limit 値は GCP Console 側で確認するしかなく、コード調査では出ない
3. **YouTube Data API の resumable upload session URI の有効期間**: 公式ドキュメントが「week ほど有効」と書いている件は本リポジトリ側で永続化していないため意味なし
4. **`channel-import` の branding push 冪等性**: `cli/channel_init.py` 全体を未読。skill 単体の責務が広い疑い
5. **`live-clean` の挙動**: SKILL.md は読んだが実装エントリ（`cli/live_clean.py` 等）は本回未読
6. **`wf-new` の workflow-state.json 重複初期化挙動**: SKILL.md `:80-81` の案内のみで実装未確認

---

## 9. 推奨アクション

severity 付きで列挙。「修正は提案レベル」で、本 part の範囲はあくまで報告まで。

| # | severity | アクション | 想定影響 |
|---|---|---|---|
| 1 | **P0** | `generate_loop_video.py` に既存 `loop.mp4` 検出 + `--force` フラグ追加。`--smooth` 単独で post-process のみ走らせる経路を追加 | Veo 再課金を防ぐ。SKILL.md `:59` の文言も修正必須 |
| 2 | **P0** | `upload_policy.RETRYABLE_HTTP_STATUSES` に 429 を加える、もしくは別経路で **quota exhaustion path = 長い待機 + retry** を入れる | quota 切れ運用の resume を可能に |
| 3 | **P0** | Veo / Lyria 等の長時間 API call に SIGINT handler を入れ、Ctrl+C 時に Operation cancel を呼ぶ。Veo は cancel API があるか要検証 | Ctrl+C で API 側も止める |
| 4 | **P0** | `upload_core._resumable_upload` の session URI を `upload_tracking.json` に永続化し、再実行で session を再利用 | video_id 重複の根本対策 |
| 5 | **P0** | `comments-reply` の `_post_reply` を **history.save → comments.insert** の順に変更する（または mark_replied を「送信予定」状態として先に書き込む）。コミット-ログ的に二段階にして window を消す | 二重返信を実装的に不可能化 |
| 6 | **P1** | `video-analyze` に `<video_id>.json` 既存 skip + `--force` フラグ追加 | Gemini 再課金防止 |
| 7 | **P1** | YouTube Data API call の共通 retry / backoff utility を新設（少なくとも 503 系）。`benchmark_collector` / `playlist_manager` / `comments-reply` / `discover-competitors` / `analytics_collector` / `channel_settings` を一括で乗せ換え | quota は焼くが少なくとも一過性 5xx で死なない |
| 8 | **P1** | SKILL.md リカバリ手順テンプレートを定め、最低限「同コマンドで再実行 / 既存生成物の扱い（skip/上書き/採番）/ API 側残骸の対処」を 15 件の × skill に追記 | 運用負債の解消 |
| 9 | **P1** | `loop-video` のバックアップに rotation を入れる（古い `loop-v{n}.mp4` を `loop-archive/` へ移動 or 上限を設ける） | ディスク無限消費の防止 |
| 10 | **P1** | `live-clean` の SIGINT トラップを実装し、進捗 JSON で resume 可能にする | 途中削除されたコレクションの可視化 |
| 11 | **P1** | `streaming swap_video.sh` の trap で `terraform force-unlock` 案内 + state ロック検出 | apply 中断時の運用負債解消 |
| 12 | **P2** | `smooth_loop` の `_smooth.mp4` を try/finally で unlink | tmp 残骸防止 |
| 13 | **P2** | `_compress_thumbnail` を try/finally に包む | 同上 |
| 14 | **P2** | `generate_master` / `generate_videos.sh` の出力上書き前に「既存ファイル → `.prev.{mp3,mp4}` リネーム」を入れる（または `--force` ガード） | 過去版保護 |
| 15 | **P2** | `gcp-bootstrap.sh` に `trap` で「部分作成済みリソース一覧をログ出力」を入れる | 中途半端な GCP project の発見性向上 |
| 16 | **P3** | `suno:314` 風の「冪等性明示」を SKILL.md テンプレに含める | 認知負荷の低減 |
| 17 | **P3** | `benchmark` の `freshness_days` ガードを SKILL.md に明記 | 運用者のメンタルモデル整備 |

---

## 10. 既存レポートとの主要差分（再走の意義）

| 項目 | 既存レポート | 本レポート |
|---|---|---|
| ×件数 | 21 件 | 15 件（4 件を △ に補正） |
| benchmark | × | △（コード側 freshness ガードを発見） |
| suno | × | △（`SKILL.md:314` で冪等性明示を発見） |
| alignment-check | × | △（`:85-94` で再実行スキル表を発見） |
| videoup | × | △（`:59` の `set -e` 不使用は意図的設計と判明）|
| discover-competitors | △ | **P1 quota 焼き**として再分類（660 units/run 明示） |
| comments-reply window | 1 行言及 | P0 で本格的に推奨アクション化（コミットログ的二段階） |
| skill × idempotency 1 行マトリクス | なし | 35 件分新設 |
| videoup `set -e` 取扱い | 異質と評価 | 意図的設計と再評価 |
| loop-video バックアップ無限増殖 | 未検出 | 新規検出 (P1) |
| live-clean SIGINT | 未検出 | 新規検出 (P1) |
| streaming swap rollback | 未検出 | 新規検出 (P1) |

---

## 11. 次ステップへの引き継ぎ

- 本レポートは P0 5 件 / P1 8 件 / P2 6 件 / P3 3 件 を提示。実装はしない（part 制約）
- analyze step / supervise step では **P0 のうち #2 (upload_core 429) と #4 (resumable URI) は密接に関連** している点に注意。同じ箇所を 2 度触ることになる
- 推奨 #5（comments-reply の二段階コミット）は仕様変更を伴うため、設計レビューが必要
- 既存レポート上書き済み。差分は §10 に集約
