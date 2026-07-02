---
name: suno
description: "Use when Suno UI に投入する音楽プロンプトを生成したいとき。SunoAI V5.5 向けの YAML 定義（インストは `tracks_per_collection` で曲数指定の独立 entry 並列、ボーカルは `/suno-lyric` で作成済みの歌詞を前提に pattern × tracks_per_pattern 設計）から suno-prompts.md / suno-prompts.json を作成する（次工程 `/suno-helper` でブラウザ自動生成 + playlist 一括追加、その後 `/masterup` で DL + マスター化）。プロンプト作成・Style 文など Suno 連続生成の前段で使用すること。Lyria チャンネルでは /lyria を使う"
---

## Overview

コレクション用の SunoAI V5.5 音楽プロンプトを YAML で定義し、スクリプトで最終プロンプトを生成する。**インストゥルメンタル / ボーカル（歌詞あり）両モード対応**。歌詞ありの場合、`/suno` は orchestration として pattern draft 保存 → `/suno-lyric` → Style / Lyrics の `suno-prompts.json` 結合までを進める。

- **インストモード**: 曲数 (`tracks_per_collection`) を指定し、ceil(N/2) 個の独立 entry をフラットに並べる（pattern 概念は廃止）。`/suno-helper` が各 entry を Suno に順次投入し、Suno 仕様で 1 Generate = 2 clip 生成されるため両 clip 採用で N clip となる
- **ボーカルモード**: 先に `/suno` で `suno-patterns.yaml` の pattern draft を保存し、続けて `/suno-lyric` で同じ entry name の歌詞を作成してから、再度 `/suno` で Style / 情景 / タイトルと `suno-lyrics.json` を `suno-prompts.json` へ結合する

## 設定読み込みゲート

前提条件チェックやモード判定に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/suno/config.default.yaml`
2. `config/skills/suno.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("suno")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。このスキルが別 skill の skill-config を直接参照する段階では、その skill の `config.default.yaml` と `config/skills/<skill>.yaml` も同じ手順で読む。

### モード判定

`config/skills/suno.yaml` の `genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。

| モード | YAML 構造 | 歌詞 | Suno 設定 |
|---|---|---|---|
| インストゥルメンタル | `tracks_per_collection` 由来の `ceil(N/2)` 個の独立 entry | 不要 | Custom Mode + **Instrumental ON** |
| ボーカル | `pattern_strategy` × `tracks_per_pattern` のパターン設計 | `/suno-lyric` で事前作成 | Custom Mode + **Instrumental OFF** + Lyrics 投入 |

### 歌詞ありの前工程

歌詞あり（ボーカルモード）と判定した場合、最初に `/suno` で `20-documentation/suno-patterns.yaml` の pattern draft を保存する。その後 `/suno-lyric` を実行して `20-documentation/suno-lyrics.json` を作り、最後に `/suno` を再実行して Style と Lyrics を `suno-prompts.json` にマージする。

`/suno-lyric` の実行は Suno クレジットを消費しない前工程なので、現実のお金のコストが発生しない限りユーザー確認は不要。`/suno-lyric` が失敗した場合は `/suno` の merge を止め、歌詞成果物を作れる状態にしてから再開する。

### スタイルバリアント（A/B テスト対応）

`config/skills/suno.yaml` に `style_variants` が定義されている場合、各 entry / パターンに `style` キーで variant を指定できる。`style_strategy: mixed` なら 1 コレクション内で複数 variant を混合、`single` なら全 entry 同一 variant で統一。

### Style 自動バリエーション（entry ごとの微差付与）

同一コレクション内の全 entry が同じ `genre_line`（+ `mood_descriptors`）を共有すると、Suno V5.5 は Style 第 1 行の影響が支配的なため似た曲が量産される。`yt-generate-suno` は `style_variation` 設定（既定で有効）に基づき、entry ごとに texture / rhythm feel の descriptor を Style 第 1 行の末尾へ自動付与して同質化を防ぐ。

設計ルール:

- **コアジャンル維持の原則**: `genre_line` 自体は全 entry で共通のまま変えない。付与は mood / texture / rhythm feel レベルの形容詞句に限定し、ジャンルの置換は行わない
- **決定的ローテーション**: 乱数ではなく entry の通し番号（YAML 上の scene 順、0-based）で pool から割り当てる。同じ YAML から再生成しても常に同じ結果になる
- **先頭 entry は base のまま**: 通し番号 0 の entry には descriptor を付けず、コレクションの基準スタイルとして保存する（単一 entry の既存コレクションは出力不変 = 後方互換）
- **明示 override 優先**: pattern に `style: <variant-key>` がある entry は `style_variants` の genre_line をそのまま使い、自動バリエーションは付与しない（通し番号は消費する）
- **プール定義**: `config.default.yaml::style_variation.pools` に axis 名（`texture` / `rhythm` 等）→ descriptor 配列で定義する。axis 名の辞書順で round-robin に interleave した列を循環割り当てる。チャンネル側 `config/skills/suno.yaml` では axis 単位で丸ごと置換（deep-merge のリスト置換）・axis 追加・空リスト上書きによる axis 無効化ができる
- **語彙の制約**: descriptor に禁止形容詞（`references/suno-examples.md`）・雨音／環境音 NG ワード・楽器名の裸置き・アーティスト名を入れない。120 文字上限は descriptor 込みの Style 文で検証される
- **重複検証**: 生成時に全 entry の Style 文（第 1 行 + 情景行）が完全一致する組があれば `yt-generate-suno` が警告する
- **無効化**: チャンネル側で `style_variation.enabled: false` を設定すると従来動作（全 entry 同一の Style 第 1 行）に戻る

## Instructions

### 前提条件チェック（hard gate）

**AI は `genre_line` を手書きしてはならない。** 方向性は必ずスクリプト（`yt-video-analyze` の `suno_preset` 出力）由来とする。`/suno` 実行に入る最初のステップとして以下を機械的に判定し、不足データがあれば原則自動で収集する:

1. `config/skills/suno.yaml` の `genre_line` を読む
2. `config/channel/analytics.json` の `benchmark.channels[].slug` を列挙
3. 各 slug について `data/video_analysis/<slug>/*.json` の存在を確認

`benchmark.channels[].slug` は自動実行と出力パスに使うため、列挙直後に `^[A-Za-z0-9][A-Za-z0-9_-]*$` で検証する。不一致の slug が 1 件でもあれば自動準備を停止し、該当 slug を修正してから再実行する。slug を shell 文字列へ直埋めしてはいけない。実行する場合は `["uv", "run", "yt-video-analyze", "--source", "benchmark", "--channel", slug, "--top", "5"]` のような argv 配列で渡す。shell 経由が避けられない環境では `shlex.quote(slug)` 相当で quote する。

| 状態 | 判定 | アクション |
|---|---|---|
| `genre_line` 非空 | OK | パターン設計に進む（既存 `suno_preset` fallback は引き続き有効） |
| `genre_line` 空 + 少なくとも 1 slug で `data/video_analysis/<slug>/*.json` 存在 | OK | `suno_preset.genre_line` を fallback として採用しパターン設計に進む |
| `genre_line` 空 + 全 slug で `data/video_analysis/<slug>/*.json` 不在 | **自動準備** | benchmark / video-analyze を自動実行して `suno_preset` を生成してから続行する |

自動準備の手順:

1. `data/benchmark_*.json` が無ければ `/benchmark` 相当の収集を先行実行
2. `data/benchmark_*.json` 取得済みなら、上記 validation 済み slug だけを対象に `uv run yt-video-analyze --source benchmark --channel <slug> --top 5` 相当を argv 配列で全 benchmark slug に実行
3. 生成された `data/video_analysis/<slug>/*.json` の `suno_preset` を fallback として採用
4. そのまま `/suno` のパターン設計へ進む

ユーザー確認が必要なのは、現実のお金のコストが発生する操作だけ。例: 有料API/有料生成の実行、Suno クレジット消費、Veo / 画像生成 / 音楽生成の新規実行、課金設定変更、外部サービスへの購入・決済。YouTube API / Analytics / ローカル解析 / 既存ファイル読み取り / benchmark 収集 / video-analyze のような準備処理は、追加課金が発生しない前提なら確認せず自動実行する。

それでも `suno_preset` が取得できない場合のみ、パターン設計に進まず停止する。`genre_line` 候補を本文中で口頭提案するのは禁止（手書き相当のため）。どうしても手書きで続行する場合は、ユーザーが明示的に `config/skills/suno.yaml::genre_line` を埋めてから再実行する。

### ベンチマーク BGM 構造の参照

設計に入る前に `data/video_analysis/<slug>/*.json` の `bgm_arc` を読み込み、slug ごとに intro 秒・peak 秒・outro 開始秒の平均と代表的な `energy_curve` パターンを抽出する。インストモードでは entry 間のバリエーション素材として、ボーカルモードでは起伏配置の参考にする。`scene_timeline[].summary` も情景フレーズ設計の素材として活用する。ベンチマーク構造を参考にするが**完全模倣しない** -- 差別化方針と矛盾する場合は意図的に外す。

### Suno プリセット推奨（suno_preset fallback）

`data/video_analysis/<slug>/*.json` の `suno_preset.genre_line` / `suno_preset.exclude_styles` を `yt-generate-suno` が fallback として参照する。`config/skills/suno.yaml` の対応キーが空のとき、全 slug 横断で集約した推奨値を採用する。ユーザーが `config/skills/suno.yaml` に override を書いた瞬間にそちらが優先される（後方互換）。

> **方向性は必ずスクリプト由来とする（AI 手書き禁止）**: `genre_line` 空 + `suno_preset` fallback も取れない状態で本 skill が AI 推定の `genre_line` を書き起こすことは禁止する。

### 対象テーマ

```
$ARGUMENTS
```

## Quality Rules (suno-bgm)

### Style Text 5-Element Order

Style テキストは以下の順序で構成する。順序を守ることで Suno の解釈精度が安定する:

1. **ジャンル名** (e.g. lo-fi hip hop, jazz)
2. **音響特性** (e.g. warm, airy, muffled)
3. **キー楽器** (e.g. felt-damped upright piano, fingerpicked acoustic guitar)
4. **リズム/ベース** (e.g. laid-back boom-bap drums, deep fretless bass)
5. **テンポ** (e.g. slow, moderate)

### 120 Character Limit

Style フィールドは **120 文字以下** でなければならない。`yt-generate-suno` がビルド時に超過を警告する。5-Element Order に従って要素を絞り込み、収まらない修飾語は削る。

### Artist Name Prohibition

**Style テキストにアーティスト名を含めてはならない。** Suno ポリシーにより生成がブロックされるか品質が低下する。禁止リストは `config/skills/suno.yaml::banned_artists` に定義されており、`yt-generate-suno` が検出するとエラーで停止する。

### Instrument Adjective Requirements

楽器名には必ず音響的な形容詞（音色・奏法・素材・時代）を付けること。裸の楽器名は Suno が汎用音色を選択し意図した音像から外れる。具体的な Bad/Good ペアは `references/suno-examples.md` の "Instrument Adjective Pairs" を参照。

### Vocal Lyrics Boundary

ボーカル曲の歌詞本文は `/suno-lyric` が生成する。`/suno` は `suno-lyrics.json` と `suno-patterns.yaml` の entry name を照合し、Style / 情景 / タイトルとマージするだけに限定する。

### Lyrics Structure Auto-Reinforcement

`auto_lyrics_structure: true`（デフォルト）のとき、`yt-generate-suno` が歌詞構造タグを自動補完する:

- **インストモード**: 歌詞先頭に `[Instrumental]`、末尾に `[Extended Outro]` を自動付加
- **ボーカルモード**: 最終セクションが `[Outro]` または `[Extended Outro]` であることを保証

### Mixing/Instrument Notes in Lyrics Header

インストモードでは、歌詞フィールドの先頭（`[Instrumental]` の前）に Mixing Notes と Instrument Notes を記述して Suno のミキシングを誘導できる:

```
Mixing Notes: warm analog warmth, slight tape saturation
Instrument Notes: lead with felt piano, background with soft pad
[Instrumental]
[Extended Outro]
```

## Track Title Generation (#899)

各 entry には **`name_en`**（2-4 word の英語シーン/ムードタイトル）と **`name_jp`**（5-15 文字の日本語訳）を付ける。Suno UI の Song Title 欄に `{name_jp} — {name_en}` として注入され、Library / playlist / `/masterup` のリネームで識別子となる。

### 命名ルール

- pattern scene + persona vocabulary をベースに、情景・質感・場所を凝縮した自然なフレーズにする
- Amber Music Playlist TTP スタイルの例:
  - "Midnight Funk Groove" / "深夜のファンクグルーヴ"
  - "Velvet Vinyl Spin" / "ベルベットレコード"
  - "Smoky Jazz Lane" / "スモーキージャズ通り"

### バリデーション

- **全タイトルユニーク**: コレクション内で `name_en` / `name_jp` の重複は `yt-generate-suno` が fail-loud で停止
- **自然なフレーズ**: AI っぽい抽象語の羅列（word salad）は禁止。具体的な情景が浮かぶタイトルにする
- **他コレクションとの差別化**: 他コレクションのタイトルと 3 単語以上の連続一致がないこと

## 構成戦略（TTP / 作業用BGM / アルバム）

`patterns:` の順序は単なる生成順ではなく、完成動画で聴かれる **tracklist** として設計する。**推奨は TTP 準拠**。競合の勝ち筋が「ずっと同じような曲が続く作業用BGM」なら無理にアルバム構成へ寄せない。

まず YAML を書く前に、内部メモとして entry ごとの `role / energy / tempo feel / key center / progression / texture / title` を並べる。これは設計用メモであり、最終 YAML には既存スキーマの `name_jp` / `name_en` / `tempo` / `style` / `scenes` だけを書く。

通常は設定不要。未指定なら推奨の TTP 準拠で設計する。TTP から意図的に外したい場合だけ、チャンネル側の `config/skills/suno.yaml::tracklist_strategy` でカスタマイズできる:

| 値 | 用途 | 使い方 |
|---|---|---|
| `ttp` | 推奨・既定。ベンチマークの `bgm_arc` / `energy_curve` / `scene_timeline` に準拠 | TTP が低起伏なら `work_bgm`、明確な山場型なら `album_setlist` と同じ設計に寄せる |
| `work_bgm` | ずっと同じような曲が続く作業用BGM特化 | entry 間の差分は小さくし、集中を切る山場・急な転換を避ける |
| `album_setlist` | アルバムやライブのセットリスト型 | 曲ごとの役割、流れ、山場、終盤の解決を明確に作る |

`tracklist_strategy` はカスタマイズ用の任意キー。未指定時は、推奨値の `ttp` とみなす。明示指定がある場合でも、TTP と大きく乖離する構成は避ける。

### TTP strategy

`ttp` では、設計前にベンチマークから以下を読み取って構成を決める:

- `bgm_arc.energy_curve` が平坦、peak が弱い、scene 変化が小さい場合: `work_bgm` 型に寄せる
- intro / peak / outro が明確、scene 変化や楽器交代が大きい場合: `album_setlist` 型に寄せる
- TTP 間で割れている場合: チャンネルの視聴シーンを優先する。study / focus / sleep / cafe は `work_bgm` 優先、drive / workout / live / party は `album_setlist` 優先

### Work BGM arc

作業用BGM特化では、聴き手が曲の変化に注意を奪われないことを優先する。全 entry を同じファミリーに置き、差分は「気づくと少し変わっている」程度に抑える。

- **Stable opening**: 1-2 entry で音像とテンポ感を固定する。強いイントロや派手な hook は作らない
- **Long plateau**: 中盤の大半は `low / medium-low` energy を維持する。lead instrument、コード進行、ドラム密度のどれか 1 つだけを少し変える
- **Micro variation**: 似た曲を続けるが、完全なコピーにはしない。key center、register、rhythm density、bass movement を小さくずらす
- **Soft reset**: 3-4 entry ごとに sparse / dry / low-register な entry を置き、耳を休ませる
- **Loopable ending**: 終盤も大きく締めすぎない。最後の entry は冒頭へ戻っても違和感が少ない密度にする

作業用BGMでは避けるもの: 急な転調、強いブレイク、派手なソロ、明確すぎる climax、曲ごとのテンポ感の大幅変更。

### Tracklist arc

`album_setlist` では、各 entry を単発の良曲ではなく、全体の流れの中で役割を持たせる。テーマが「live」「club set」「concert」「festival」など明確にライブ体験を示す場合は setlist 差分も入れる。

- **Album opening**: 1-3 entry でテーマ・音像・主要楽器を提示する。1 曲目は強い入口、2-3 曲目は世界観の確認。最初の数曲で「このコレクションを聴き続ける理由」を作る
- **Album side / block**: 中盤は 2-4 entry 単位の小さなまとまりを作る。似たテンポ / 音色 / グルーヴを少し続けてから、breather で密度を落とす
- **Album deep cut**: 中盤後半に少しだけ個性の強い entry を置く。BGM なので奇抜さではなく、key center / progression / lead instrument の変化で印象を作る
- **Album peak**: 全体の 60-75% 付近に最も印象的な entry を置く。急激な転調・過剰なドラム・派手すぎるソロは避け、グルーヴの確信度とメロディの輪郭で山場にする
- **Album resolution**: 終盤はテンポ感・音数・明度を落とし、余韻を残して自然に締める。最後の entry は「終わった感」よりも「次の再生に戻れる余白」を優先する

ライブ / セットリスト型のテーマでは、以下の差分を入れる:

- **Opener**: 入口は短い助走で始まり、30 秒以内に主要グルーヴが見える entry にする
- **Run**: 2-3 entry の高めの run で勢いを作り、その後に mid / low の breather を入れる
- **Mid-set reset**: 中盤で key / meter / lead instrument を明確に変え、耳をリセットする
- **Closer**: 終盤 2-3 entry は再び energy を上げる。ただし YouTube BGM の場合、ラストは完全燃焼ではなくループ再生に戻れる密度で止める

### Adjacent-track design

隣り合う entry は、個別の良さよりも「前曲の終わりから次曲の入りが自然か」を優先する。以下を各 entry の設計メモとして確認する:

- **Energy**: `low / medium / high` の流れが平坦になっていないか。単純な high-low 交互ではなく、数曲の run と breather を作る
- **Tempo feel**: BPM 数字より体感テンポを変える。似たテンポ感が 3 entry 以上続く場合は、リズム密度か楽器を変える
- **Key / harmony**: 同じ key center / chord type を連続させすぎない。近い調・relative major/minor は自然な接続、遠い調は山場や場面転換に使う
- **Texture**: lead instrument、drum density、bass movement、空間系の量を隣接曲で少しずつ変える
- **Reset space**: 似た曲が続く場合は、次 entry の冒頭を sparse / dry / low-register などにして耳をリセットする。`rain`, `white noise`, `ambient noise` のような環境音リセットは禁止

各 entry の `scenes` には、必要に応じてベースとなるコード進行やハーモニー感も短く入れる。Suno に細かいコード譜を渡すのではなく、和声のキャラクターを英語で短く足す:

- 安定: `warm I-vi-IV-V soul loop`, `minor 7th groove`, `soft two-chord vamp`
- 滑らかな接続: `ii-V-I jazz turnaround`, `relative minor lift`, `circle-of-fifths motion`
- 緊張: `suspended gospel chords`, `modal interchange color`, `chromatic passing bass`
- 山場: `rising dominant motion`, `bright major release`, `call-and-response chord stabs`
- 終盤: `descending bass movement`, `open tonic pedal`, `slow plagal cadence`

アルバム全体では同じ進行タイプを連続させすぎない。序盤は安定、中盤は少し緊張、山場は強い解放、終盤は余韻のある進行に寄せる。

## 曲数ベース設計（インストモード）

**pattern 概念を廃止し、`tracks_per_collection` から `ceil(N/2)` 個の独立 entry をフラットに並べる**。各 entry = 1 Generate = 2 clip 両採用。

| キー | 役割 | 既定 |
|---|---|---|
| `tracks_per_collection` | 最終 clip 数 | `20` |
| `tracks` (yaml) | コレクション単位の上書き | 省略 |
| `style_strategy` | `mixed` / `single` | `single` |

### 1 pattern = 1 scene 原則（必須）

**各 pattern の `scenes` は必ず 1 行のみとする。** 1 pattern に複数 scenes を入れると、コードが `(Variation 1)` `(Variation 2)` ... の機械的接尾辞でタイトルを生成し、曲ごとの固有性が失われる。
代わりに `ceil(N/2)` 個の pattern をフラットに並べ、それぞれに固有の `name_jp` / `name_en` と 1 行の scene を持たせること。

**NG（複数 scenes → Variation N で機械的ユニーク化）:**
```yaml
patterns:
  - name_jp: 不屈の持久
    name_en: Unbreakable Endurance
    scenes:
      - scene A text...
      - scene B text...
      - scene C text...
```

**OK（1 pattern = 1 scene、各曲が固有タイトル）:**
```yaml
patterns:
  - name_jp: 鋼の意志
    name_en: Iron Will
    scenes:
      - scene A text...
  - name_jp: 揺るがぬ決意
    name_en: Unwavering Resolve
    scenes:
      - scene B text...
  - name_jp: 不屈の持久
    name_en: Unbreakable Endurance
    scenes:
      - scene C text...
```

### 手順

1. ベンチマーク `bgm_arc` と `scene_timeline[].summary` から多様な情景素材を集める
2. 構成方針は未指定なら推奨の TTP 準拠で決める。チャンネル側に任意の `tracklist_strategy` がある場合だけ、そのカスタマイズを考慮する
3. `config/skills/suno.yaml::tracks_per_collection` を読み曲数を確定（上書き時は yaml の `tracks:` キー）
4. `ceil(tracks / 2)` 個の entry を順序付き tracklist として設計。**各 entry は固有の `name_jp` / `name_en` を持ち、`scenes` は 1 行のみ**
5. style variant を割り当て（`single` なら全 entry 同一、`mixed` なら entry ごとに切替）
6. `yt-generate-suno` 実行で検証（entry 数不一致・name 重複は fail-loud）

## パターンベース設計（ボーカルモード）

**ボーカルモードは pattern draft を先に保存する。** 本スキル内で歌詞を直接作らない。`suno-lyrics.json` が未生成なら、まず `suno-patterns.yaml` を保存してから `/suno-lyric` を実行し、その後 `/suno` に戻って Style / 情景 / タイトルと Lyrics をマージする。

ボーカルモードのみ、パターン × 再生成回数で設計する（歌唱の発音・ピッチ精度のためベスト曲選曲運用を維持）。

| キー | 役割 | 既定 |
|---|---|---|
| `pattern_strategy` | `mixed` / `single` | `mixed` |
| `tracks_per_pattern` | パターンあたりの再生成回数 | `3` |

- `single`: 1 つの統合情景フレーズにまとめ、同一プロンプトを `tracks_per_pattern` 回生成
- `mixed`: 感情の起伏を N 個のパターンに分割（典型 4: 静寂 → 開放 → 親密 → 動き）

### 曲の長さ（V5.5）

Suno V5.5 では Styles 経由で実楽曲長を制御できない。望む長さに満たない場合は **Suno UI の Extend** で延長する。

## 情景フレーズ設計ルール

1. **命令文なし**: `Create a...` で始めない。情景を描写する
2. **簡潔な修飾**: 形容詞は 1-2 個。繰り返し禁止
3. **五感に訴える**: 視覚・触覚・嗅覚など具体的な描写。メロディ・ベース・リズムは書かない
4. **楽器ロール指定**: `Solo Cello` や `Ethereal Choir` でフィーチャー楽器を強調可能（任意）
5. **ベンチマーク活用**: `scene_timeline[].summary` を素材にするが**そのままコピペしない**

### 禁止形容詞

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving 等

### 雨音・環境音の制御

**雨音や環境音は楽曲に含めない。** NG ワード: rain, dripping, drops, puddles, splashing, pouring 等。OK ワード: misty, melancholic, nocturnal, bittersweet, foggy 等。全プロンプトに `no rain sound effects, no white noise, no ambient noise` を追加。`exclude_styles` にも `rain sounds, vinyl crackle, white noise, ambient noise` を含める。

#### genre_line と exclude_styles の整合性

`exclude_styles` で除外したワードを `genre_line` 側に残すと相殺される。たとえば `exclude_styles` に `vinyl crackle` を含めつつ `genre_line` に `vinyl crackle warmth` を入れると除外が無効化される。`exclude_styles` を更新するときは `genre_line` 側にも同じワードや派生表現が混ざっていないかをセットで確認する。

### テンポ設計

自然言語テンポ: `very slow` / `slow` / `gentle` / `moderate` / `lively`

| テーマ | テンポ | 情景フレーズ例 |
|--------|--------|--------------|
| Study / Reading | slow | fingers turning pages slowly |
| Sleep / Dream | very slow | embers fading in a stone hearth |
| Forest / Nature | gentle / moderate | morning mist between ancient oaks |
| Festival / Dance | lively | fiddles rising in a torchlit hall |

## 出力

### Step 1: 定義を YAML で保存

`20-documentation/suno-patterns.yaml` に保存。インストモードは `ceil(N/2)` 個の独立 entry を `patterns:` 配列に並べる。ボーカルモードは `/suno-lyric` の `suno-lyrics.json` と `name` が一致する pattern / scene / title を記述する。

```yaml
title: Collection Title Here
mode: instrumental  # 省略時は genre_line から自動判定
tracks: 10  # 省略時は config の tracks_per_collection
patterns:
  # 1 pattern = 1 scene = 固有タイトル。ceil(10/2) = 5 個の entry
  - name_jp: 屋上の静寂
    name_en: Rooftop Silence
    tempo: slow
    scenes:
      - a heavy door propped open with a brick, cool night air rising through a dim stairwell
  - name_jp: 煙突の向こう
    name_en: Beyond the Chimney
    tempo: slow
    scenes:
      - grey smoke trailing upward from a rooftop chimney, the skyline a blurred edge of warm windows
  - name_jp: 路地裏の灯り
    name_en: Alley Lantern Glow
    tempo: gentle
    scenes:
      - a single paper lantern swaying above a narrow alley, puddles catching the soft amber light
  - name_jp: 港の霧笛
    name_en: Harbor Foghorn
    tempo: slow
    scenes:
      - a distant foghorn rolling across a still harbor, ships resting dark against a grey dawn
  - name_jp: 窓辺の雨だれ
    name_en: Windowsill Drip
    tempo: gentle
    scenes:
      - condensation tracing slow lines down a warm kitchen window, a kettle just finished steaming
```

### Step 2: スクリプトで suno-prompts.md を生成

```bash
uv run yt-generate-suno <collection-path>
```

`config/skills/suno.yaml` の `genre_line` + `exclude_styles` + `style_influence` をパターンに自動付加して `suno-prompts.md` と `suno-prompts.json` を生成する。ボーカルモードでは同階層の `suno-lyrics.json` を優先して読み、entry `name` が一致する lyrics を Style とマージする。保存後、`workflow-state.json` の `music.generated = true` に更新する。

### Step 3: `/suno-helper` で自動投入（推奨）

`suno-prompts.json` を Chrome 拡張（`extensions/suno-helper/`）が読み取り、連続実行する。

1. **拡張をビルドしてロード**（初回のみ）: `pnpm install && pnpm build` → Chrome で `chrome://extensions` → `.output/chrome-mv3/` を選択
2. **サーバー起動**: `uv run yt-collection-serve collections/planning/<theme>` → `http://localhost:7873/suno/prompts.json` で配信
3. **Suno を開く**: Chrome で Custom Mode 画面（ボーカルは **Instrumental OFF**）
4. **取得 → 連続実行**: 拡張ポップアップでデータ取得 → 全パターンを連続実行。スキップされた entry は再実行ボタンで再投入可能

UI 変更で注入先セレクタが外れた場合は `extensions/shared/dom.ts` の `SELECTORS` を保守する。

### Step 3 の fallback: 拡張が使えない／壊れたときの手コピペ

拡張をロードできない場合は `suno-prompts.md` を見ながら手コピペに切り替える: Suno の Custom Mode に入り、パターンごとに Style 欄と Lyrics 欄を貼り付けて Generate。自動・手動どちらでも投入内容は同一。

### Step 4: workflow-state.json の planning.music を更新

`/alignment-check` が音楽 mood × サムネ × タイトルの整合を判定できるよう、`workflow-state.json` の `planning.music` を populate する。

```json
{
  "planning": {
    "music": {
      "engine": "suno",
      "mood": ["mellow", "introspective"],
      "atmosphere": "rainy harbor at night, mellow jazz by the docks",
      "tempo": "slow",
      "instruments": ["soft piano", "saxophone", "upright bass"],
      "exclude": ["electric guitar", "heavy drums"]
    }
  }
}
```

## Next Step

### インストゥルメンタル
→ `/suno-helper` で SunoAI Custom Mode（**Instrumental ON**）に自動投入して連続生成 + playlist 一括追加
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成

### ボーカル（歌詞あり）
→ `/suno` で `suno-patterns.yaml` の pattern draft を保存
→ `/suno-lyric` で同じ entry name の歌詞を生成・レビュー
→ `/suno` を再実行して Style + Lyrics の `suno-prompts.json` を生成
→ `/suno-helper` で SunoAI Custom Mode（**Instrumental OFF**）に Style + Lyrics を自動投入して連続生成 + playlist 一括追加
→ 歌唱の発音・ピッチが破綻していないか必ず試聴チェック
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成

## Cross References

- 前工程（テーマ確定 + 制作開始）: `/wf-new`
- 歌詞生成（ボーカルのみ）: `/suno-lyric`
- 次工程（ブラウザ自動生成 + playlist 一括追加）: `/suno-helper`
- 後工程（DL + マスター化）: `/masterup`
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `src/youtube_automation/scripts/collection_serve.py`
