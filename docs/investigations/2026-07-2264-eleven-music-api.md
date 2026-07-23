# Eleven Music API 採用調査（Issue #2264）

## 結論

- **判定: 条件付き Go（有料 PoC まで）。本番採用は保留。** `music_v2` は 3〜600 秒、instrumental 指定、composition plan、同期・streaming API を備え、既存の「複数セグメント生成 → WAV 化 → master 結合」に接続しやすい。
- 収益化 YouTube は Starter 以上の Media Rights の範囲に見える。DistroKid を介した Spotify 等への配信は規約上の `Streaming` に該当し、**Creator 以上**が必要である。
- ただし、ElevenAPI Pricing の含有分数と Model-Specific Terms の月間生成上限は別の数値である。料金枠と利用権上限を別々に満たす必要があり、後述の試算はこの保守的な読み方を採る。
- 実装は公式 SDK ではなく既存 `requests` による薄い REST client を推奨する。依存追加を避け、response header・音声 bytes・HTTP status をリポジトリ固有の resume / cost log 契約へ直接写像しやすいためである。
- 有料 PoC 前に、(1) API/PAYG 生成にも Music Commercial Rights 表の月間生成・download 上限がそのまま適用されるか、(2) 失敗した生成の課金・返金条件、(3) DistroKid への配信が `Streaming Rights` だけで足りるかを ElevenLabs と DistroKid に確認する。

> 調査日: 2026-07-22（Asia/Tokyo）。価格・規約・preview/GA 状態は変わり得るため、購入・本番投入時に再確認すること。本書は公式資料の技術・契約情報を整理したもので、法的助言ではない。

## 1. 料金とプラン条件

### 1.1 ElevenAPI の料金枠

[ElevenAPI Pricing](https://elevenlabs.io/pricing/api) は Music を **$0.15 / 生成分**、API usage を USD 建てとし、税・賦課金・関税を除外している。Music は生成単位で計測される。新規 self-serve の超過は postpaid ではなく、[PAYG Top Up](https://elevenlabs.io/docs/overview/administration/pay-as-you-go) の前払い残高を使う。残高 $0 で呼び出しは停止し、Top Up は返金不可・購入から12か月で失効する。既存 usage-based billing 契約と Enterprise は別扱いである。

| API plan | 月額（monthly） | Music 含有分数 | 含有分の $0.15 換算 | Music concurrency（規約表） |
|---|---:|---:|---:|---:|
| Free / PAYG | $0 + Top Up | 3分 | $0.45 | 0（PAYG FAQ は Starter 相当3と記載。資料差あり） |
| Starter | $6 | 40分 | $6.00 | 2 |
| Creator | $22（初月 $11） | 147分 | $22.05（丸め差） | 2 |
| Pro | $99 | 660分 | $99.00 | 2 |
| Scale | $299 | 1,993分 | $298.95（丸め差） | 5 |
| Business | $990 | 6,600分 | $990.00 | 5 |
| Enterprise | 要見積 | custom | custom | 5 または 10+（契約種別による） |

注: Pricing ページの画面上の列順は Free/PAYG, Starter, Creator, Pro, Scale, Business であり、上表もその順に対応させた。価格は税別表示。一方、Model-Specific Terms は「適用される VAT / sales tax 込み」とするため、実請求額は地域・購入画面・契約形態を正とする。

### 1.2 Music 固有の利用権上限

[Eleven Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms)（2026-05-26 更新）は料金表とは別に次の上限を置く。

| plan | 対象 | 月間生成上限 | 月間 download 上限 | Streaming | Media | 帰属 | 高品質 download | API access | concurrency |
|---|---|---:|---:|---|---|---|---|---|---:|
| Free | 個人のみ | 11分 | 不可 | 不可 | 商用可。ただし film/TV/radio/Studio Games 除外 | Eleven Music 表示必須 | No | No | 0 |
| Starter | 個人のみ | 17分 | 30分 | 不可 | 同上 | 不要 | No | Yes | 2 |
| Creator | 個人のみ | 62分 | 250分 | 可 | 同上 | 不要 | No | Yes | 2 |
| Pro | 個人のみ | 304分 | 500分 | 可 | 同上 | 不要 | Yes | Yes | 2 |
| Scale | 10人未満 | 1,100分 | 1,500分 | 可 | 同上 | 不要 | Yes | Yes | 5 |
| Business | 50人未満 | 4,800分 | 4,000分 | 可 | 同上 | 不要 | Yes | Yes | 5 |
| Enterprise Music Lite | 制限なし | custom | custom | 可 | film/TV/radio/Studio Games 除外 | 不要 | Yes | Yes | 5 |
| Enterprise Music | 制限なし | custom | custom | 可 | 全 online/offline commercial use | 不要 | Yes | Yes | 10+ |

### 1.3 資料差の扱い

- Pricing の「含有分数」は API の金銭的 quota、Model-Specific Terms の「月間生成/download 上限」は Music の利用権上限と解釈する。例: Creator は API 147分相当を含むが、Music 規約上の生成上限は62分である。
- この差を説明する公式記述は確認できなかった。PAYG が plan restriction を解除しない旨は公式 FAQ にあるため、**Top Up で権利上限まで自動的に拡張できるとはみなさない**。
- PAYG FAQ の Free concurrency=Starter相当3と、Music Terms の Free=0 / Starter=2 も一致しない。Music 固有表を優先し、実アカウントの response と dashboard で確認する。
- API Pricing は「5 minute duration limit」、API Reference は 600,000 ms（10分）を示す。API の request validation を実装上の上限（10分）、商品説明の5分を運用上の安全値として PoC で確認する。

## 2. 30・60・180分の費用試算

### 前提

- API 従量価値は `生成分数 × $0.15`。採用/不採用にかかわらず生成した retry も課金される前提。
- retry ケースは **20% の再生成**（目標尺 × 1.2）とする。公式資料は失敗生成の返金条件を明示していないため、最悪ケースとして retry 全量を課金対象に含める。
- 収益化 YouTube と Streaming 配信の両方を可能にするため Creator 以上を選ぶ。
- 必要 plan は Model-Specific Terms の月間生成上限を超えない最小 tier。料金総額は月額に、Pricing の含有分を超えた場合だけ $0.15/分の Top Up を加える。税別概算。

| 目標尺 | ケース | 実生成 | API 従量価値 | 最小 plan | 月額 + Top Up 概算 | 上限リスク |
|---:|---|---:|---:|---|---:|---|
| 30分 | 通常 | 30分 | $4.50 | Creator | $22.00 | 62分上限内、download 250分内 |
| 30分 | retry 20% | 36分 | $5.40 | Creator | $22.00 | 同上 |
| 60分 | 通常 | 60分 | $9.00 | Creator | $22.00 | 62分上限まで残り2分。retry余地ほぼなし |
| 60分 | retry 20% | 72分 | $10.80 | Pro | $99.00 | Creator 62分を超過するため Pro |
| 180分 | 通常 | 180分 | $27.00 | Pro | $99 + 33×$0.15 = **$103.95** | Pro 304分 / download 500分内 |
| 180分 | retry 20% | 216分 | $32.40 | Pro | $99 + 69×$0.15 = **$109.35** | Pro 上限内、残り88分 |

30分だけを収益化 YouTube に使い Streaming 配信しない場合でも、Starter の規約上の月間生成上限17分を超えるため Creator が必要になる。API quota だけで選ぶと誤る点に注意する。

### 2.1 実チャンネルでの試算

#### データの取り方

試算の正規入力は動画尺ではなく、各collectionの `20-documentation/suno-patterns.yaml::tracks` とする。これは実際に生成する曲数であり、欠損する過去collectionでは `workflow-state.json::track_count`、さらに欠損する場合は `config/skills/suno.yaml::tracks_per_collection`（未設定時はskill default 20）へfallbackした。公開本数は最新 `data/analytics_data_*.json` の30日スナップショットからライブ配信を除いて数えた。

Eleven MusicはSunoの「1 Generate = 2 clips」と異なり、1 API requestで指定尺の1曲を返す。したがって移行後は `tracks` を「採用する最終曲数」と解釈し、`tracks × 1曲のrequest尺` が課金生成分になる。直近collectionの手元音源を `ffprobe` すると1曲平均は約2.6〜4.3分だったため、標準試算は **4分/曲**、感度分析は3分/曲と5分/曲で行う。

#### チャンネル別（4分/曲）

| チャンネル | analytics snapshot | 30日公開本数 | 設定曲数の合計 | 根拠 | 生成分 | 20%再生成込み | 最小plan |
|---|---|---:|---:|---|---:|---:|---|
| AFRO DEEP NOIR | 2026-07-14 | 2本 | 30曲 | 直近2件の `tracks=15` | 120分 | 144分 | Pro $99 |
| DeepFocus365 | 2026-07-13 | 2本 | 20曲 | 当時 `track_count=10`×2。現行channel設定は12曲 | 80分 | 96分 | Pro $99 |
| Soulful Grooves | 2026-07-22 | 4本 | 112曲 | `tracks=28`×4 | 448分 | 537.6分 | Scale $299 |
| Veluvia | 2026-07-22 | 8本 | 120曲 | `tracks=15`×8 | 480分 | 576分 | Scale $299 |
| ABYSS MI | 2026-07-13 | 9本 | 167曲 | local 5件は16〜19曲、未対応4件は現行設定19曲で補完 | 668分 | 801.6分 | Scale $299 |
| Harana Island Sounds | 2026-07-22 | 6本 | 112曲 | collection設定12〜22曲の実合計 | 448分 | 537.6分 | Scale $299 |
| **合計** | — | **31本** | **561曲** | — | **2,244分** | **2,692.8分** | **Business $990** |

plan判定はAPI料金枠だけでなく、Music Model-Specific Termsの月間生成上限（Creator 62分、Pro 304分、Scale 1,100分、Business 4,800分）も満たす最小tierで行った。たとえばDeepFocus365は20曲×4分=80分の生成で、金額価値は$12にすぎないが、Creatorの62分上限を超えるためProになる。

#### 1collectionの具体例

- AFRO DEEP NOIR: 15曲×4分=60分、20%再生成込み72分。通常はCreator上限内だが、再生成を見込むとPro。
- DeepFocus365（現行設定）: 12曲×4分=48分、retry込み57.6分。1collectionだけならCreator $22に収まる。
- Soulful Grooves: 28曲×4分=112分、retry込み134.4分。1collectionならPro、月4本ではScale。
- Veluvia: 15曲×4分=60分、retry込み72分。月8本ではScale。
- ABYSS MI（現行設定）: 19曲×4分=76分、retry込み91.2分。1collectionからPro。
- Harana Island Sounds: 現行12曲なら48分、過去22曲構成なら88分。前者はCreator、後者はPro。

#### 曲尺による感度分析（6チャンネル合計561曲/月）

| 1曲のrequest尺 | 月間生成 | 20%再生成込み | API従量価値（通常 / retry） | 共有契約の最小plan |
|---:|---:|---:|---:|---|
| 3分 | 1,683分 | 2,019.6分 | $252.45 / $302.94 | Business $990 |
| **4分** | **2,244分** | **2,692.8分** | **$336.60 / $403.92** | **Business $990** |
| 5分 | 2,805分 | 3,366分 | $420.75 / $504.90 | Business $990 |

同一事業者・teamとして6チャンネルを1契約にまとめられることを確認できれば、標準4分ケースはBusinessの生成上限4,800分とAPI含有6,600分以内なので **$990/月 + 税**である。チャンネル別契約なら標準・retryとも `Pro×2 + Scale×4 = $1,394/月`。権利上限回避のためにaccountを分割せず、契約主体と複数channel利用をElevenLabsへ確認する。

動画尺をそのまま合計した上限比較では同じ30日で2,771.8分（retry込み3,326.2分）だった。曲数設定ベースの標準2,244分との差527.8分は、masterのloop、crossfade、動画側の尺延長等に相当するため、新規音楽の課金量へ含めない。

#### 実装上の設定契約

Eleven Music adapterは `audio.target_duration_min` から曲数を逆算せず、collectionの確定 `track_count` とprovider固有の `track_duration_ms` を受け取る。実行前に「曲数、1曲尺、合計生成分、retry予算、必要plan」をpreviewし、月間上限を超えるrequestは送らない。Sunoのinstrumental/vocal別の2 clips・winner選択ロジックは持ち込まず、Eleven Musicでは1 track = 1 request = 1 outputを契約にする。

## 3. 利用条件

### 収益化 YouTube

- Self-Serve plan の Media Rights は online/offline commercial use を許可し、film, TV, radio, Studio Games を除外する。収益化 YouTube は通常この online media に含まれると読める。
- Pricing は commercial license を Starter+ と明記する。Free は一般の Help Center と帰属条件に食い違いが見えるため、商用用途では使わない。
- Starter 以上は Music 固有表上の attribution 不要。ただし API client が reseller や Pure-play Music AI Creation Company に該当する場合は [Music API Terms](https://elevenlabs.io/music-api-terms) の co-branding 条件が別途あり得る。本リポジトリで自社チャンネル用に生成するだけなら通常該当しない。

### DistroKid / Spotify 等

- Terms は `Streaming` を「Output を third-party music streaming platforms で利用可能にすること」と定義する。DistroKid 経由の Spotify / Apple Music 等への配信はこれに該当する。
- Free / Starter は Streaming prohibited、Creator 以上は Yes。したがって **Creator が最低 tier**。
- 全 self-serve plan で Music Libraries & Repositories と Reseller Rights は禁止される。生成曲を第三者向け素材ライブラリとして販売・再許諾する運用には転用しない。
- 配信代行側の AI music・権利表明・Content ID 条件は ElevenLabs の許諾とは別である。DistroKid 側の最新条件確認を PoC gate にする。

### 入力と安全制限

[Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music) は、band / musician 名や copyrighted lyrics を含む prompt を拒否し、`bad_prompt` または `bad_composition_plan` を返すと明記する。有害内容では代替案を返さない。さらに [Prohibited Use Policy](https://elevenlabs.io/use-policy) と Music/API Terms が適用される。

実装では artist/band/song title、第三者歌詞、権利未確認の入力を禁止し、公式の suggestion を人間が確認してから再送する。自動的に suggestion を課金再実行しない。

### 解約・downgrade

- Model-Specific Terms は、解約・downgrade 後も Output は生成時 plan の条件で利用できるとする。既存 Output の利用権は残るが、service 上で新規生成・既存 Output の編集はできなくなる場合がある。
- 一般 Help Center も paid subscription 中に生成した content の commercial license は期限なく継続すると説明する。
- hosted content が永久保存される保証はない。生成時に audio、request/song ID、plan、規約確認日をローカルへ保存する。

## 4. API / SDK 仕様

| 観点 | 公式仕様 | 実装判断 |
|---|---|---|
| endpoint | `POST /v1/music`、`POST /v1/music/stream`、composition-plan endpoint | 通常 compose を使い、stream は初期版では不要 |
| model | `music_v1`（default）、`music_v2` | `music_v2` を明示。既定値へ依存しない |
| 長さ | prompt 時 `music_length_ms=3000..600000` | 1 segment ≤ 600秒。運用はまず300秒以下で検証 |
| prompt | 最大4,100文字。composition plan と排他 | mode を明示する request model を作る |
| plan | 最大30 chunks、各3,000..120,000ms、positive/negative style 各50 | 再現性と章構成が必要な経路だけ利用 |
| instrumental | `force_instrumental=true`（prompt のみ） | BGM の既定値にする |
| seed | 0..2,147,483,647。prompt と併用不可。完全再現保証なし | plan 経路でのみ記録。resume key には使わない |
| duration enforcement | v1 は `respect_sections_durations`、v2 は常に section duration を強制 | v2 では flag を送らない |
| output | `output_format=auto` は v1=`mp3_44100_128`、v2=`mp3_48000_192`。API は26 enumを公開 | 初期版は `auto`、受信後 WAV PCM 48kHzへ正規化 |
| response | audio bytes、`song-id` response header | audio を原子的保存し、song/request ID を cost log へ記録 |
| detailed | SDK の `compose_detailed` は audio、filename、composition plan、song metadata | REST の詳細 endpoint は PoC で schema fixture を採取 |
| sync/stream | full response と streamed response の両方 | resume 優先で sync。受信中断時の部分 stream は破棄 |
| auth | `xi-api-key` / 公式 SDK の `ELEVENLABS_API_KEY` | env → 1Password の既存 secret resolver |
| errors | standard HTTP。400/401/402/403/404/409/422/429/500/503。429 は rate/concurrency を code で区別 | 429/5xx のみ bounded backoff。4xx は retry しない |
| rate/concurrency | Music terms: Starter/Creator/Pro=2、Scale/Business=5 | worker pool を plan limit 以下に固定。初期値1 |

課金済み失敗の公式な一般保証・refund 条件は確認できなかった。したがって timeout 後の盲目的 retry は二重課金リスクがある。response 未受信時は request ID を残して `manual-intervention` とし、同一 request を自動再送しない設計が安全である。

## 5. リポジトリへの影響

### 推奨構成

| 責務 | 変更候補 | 内容 |
|---|---|---|
| client | `src/youtube_automation/utils/eleven_music_client.py`（新規） | REST request、typed error、header抽出、timeout。`lyria_client.py` は変更しない |
| CLI | `src/youtube_automation/scripts/generate_eleven_music_master.py`（新規） | segment生成、原子的保存、resume、WAV変換、master結合 |
| entry point | `pyproject.toml` | `yt-generate-eleven-music-master` を追加 |
| secret | `src/youtube_automation/utils/secrets.py` | `ELEVENLABS_API_KEY` の env → `op read` mapping |
| config | `src/youtube_automation/configuration/audio.py` と loader/examples | provider 固有設定を責務別 config へ追加する場合だけ変更 |
| state/schema | `.claude/skills/wf-new/references/schema.md` と契約テスト | `planning.music.engine` に `eleven_music` を追加。Suno固有 URL を必須にしない |
| routing | `.claude/skills/wf-next/SKILL.md`, `src/youtube_automation/scripts/wf_batch.py` | `suno_playlist_url` guard を engine 別に分岐。音声実在を共通完了条件にする |
| skill | `.claude/skills/eleven-music/`（新規） | 認証は人間、コマンド実行・resume・保存は AI/script の責務にする |
| cost | `src/youtube_automation/utils/cost_tracker.py` | category=`audio`、quantity=生成秒/分、model、song-id、request-id、attempt、output を記録 |
| tests | `tests/test_eleven_music_client.py` 等 | HTTP fixture、error分類、原子的保存、resume、課金retry gate、schema routing |

生成物は既存契約へ合わせて `02-Individual-music/{NN}_{name}.wav`、最終成果物を `01-master/master.mp3` とする。raw MP3 は受信後の中断救済用に `tmp/eleven-music-recovered/<song-id-or-sha1>.mp3` へ原子的に保存する。

### REST と公式 SDK

| 選択肢 | 長所 | 短所 | 判定 |
|---|---|---|---|
| `requests` REST | 既存依存のみ、header/song-id と raw bytes を直接扱える、Lyria client と運用統一、SDK更新待ちなし | request/response model と error mapping を自前管理 | **採用推奨** |
| `elevenlabs` SDK | typed `ApiError`、compose/plan/detailed の高水準 API、公式サンプルと一致 | 新規依存、SDK breaking change追従、stream iterator と raw header の救済処理を包む必要 | PoC fixture 取得・仕様照合には有用 |

`requests>=2,<3` は既に依存済みである。新 provider のためだけに SDK を runtime dependency に加える便益は現時点で小さい。

## 6. Go / No-Go と後続 issue

### 採用条件

1. ElevenLabs から API/PAYG と Music rights 上限の関係を文面で確認できる。
2. Creator/Pro の Streaming Rights が DistroKid の配信・収益化要件と両立する。
3. 30秒×3程度の PoC が音質、prompt追従、instrumental保証、latency、retry課金の基準を満たす。
4. API key は人間が dashboard / 1Password で認証・登録し、AI/script は secret 値を表示せずコマンド実行だけを担う。
5. 月間 spend cap、plan 上限、1並列、再送承認 gate を実装する。

いずれかの権利確認が否定・不明のままなら本番は No-Go とし、既存 Lyria / Suno を維持する。

### 概算実装規模

- PoC: 0.5〜1日（手動認証、REST schema fixture、3生成、費用/品質記録）
- provider client + CLI + tests: 2〜3日
- workflow/schema/skill 貫通: 2〜3日
- 下流 channel migration / docs: 1日
- 合計: おおむね 5.5〜8日（契約確認待ちは除外）

### 後続 issue 分割案

1. **Eleven Music 有料 PoC**: 人間による認証・予算承認後、`music_v2` instrumental を 30秒×3、composition plan 1件で評価。上限 $1。API response/header と課金画面を secret 除外で記録。
2. **Eleven Music REST client**: secret resolver、request model、typed error、bounded retry、atomic recovery、cost metadata を TDD で実装。
3. **master CLI**: segment planning、resume、WAV 48kHz 正規化、既存 `generate_master()` 接続、spend cap を実装。
4. **workflow/schema 貫通**: `planning.music.engine`、`wf-next`、`wf_batch.py`、example config、contract tests を provider-aware にする。
5. **Eleven Music skill**: 人間認証と AI/script 実行の境界、課金確認、DistroKid gate、トラブルシュートを定義。
6. **tayk provider 設計への移管評価**: Python maintenance mode を踏まえ、新規 provider の本実装先を tayk 側に限定するか ADR で決める。

## 参照した公式資料

- [ElevenAPI Pricing](https://elevenlabs.io/pricing/api)
- [Pay As You Go](https://elevenlabs.io/docs/overview/administration/pay-as-you-go)
- [Compose music API](https://elevenlabs.io/docs/api-reference/music/compose)
- [Stream music API](https://elevenlabs.io/docs/api-reference/music/stream)
- [Create composition plan API](https://elevenlabs.io/docs/api-reference/music/create-composition-plan)
- [Composition plans guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/music/composition-plans)
- [Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music)
- [API errors](https://elevenlabs.io/docs/eleven-api/resources/errors)
- [Eleven Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms)
- [Music API Terms](https://elevenlabs.io/music-api-terms)
- [Prohibited Use Policy](https://elevenlabs.io/use-policy)
- [Subscription終了後のcontent](https://help.elevenlabs.io/hc/en-us/articles/15993008593297-What-happens-to-my-content-after-my-subscription-ends)
