# Persona × Quote Affinity（ペルソナ別偉人マッピング）

`/suno-lyric` がコレクションの各曲に偉人を割り当てるための参照表。
このファイルは **参考資料** であり、実際の重み付けは `config/skills/suno-lyric.yaml::affinity_weights`（無ければ `config.default.yaml`）で行う。

## フォールバックペルソナ例

チャンネル固有の `docs/audience-persona.md` がある場合はそちらを優先する。この節は persona 未定義チャンネル向けの例。

### Primary: Carla (45-65歳)

- 70年代 Funk/Soul/R&B 体験世代。EW&F / Parliament / Stevie Wonder が原体験
- **本物志向**: AI 音楽への警戒心が強く、「人が書いた」質感への感度が高い
- **懐古層**: 過ぎた時間・取り戻せない瞬間・誇り高い記憶への共鳴
- **シーン**: 静かな夜・休日の朝・ドライブの途中・思い出話の合間
- **響くキーワード**:
  - `time` / `memory` / `pride` / `quiet` / `golden`
  - `longing` / `stay` / `remember` / `slow` / `breath`
  - `father` / `mother` / `younger` / `years` / `then`

### Secondary: Marcus (28-38歳)

- リモートワーカー・ナレッジワーカー（コーダー・ライター・デザイナー）
- **集中BGM需要**: 深夜コーディング・長時間の集中作業
- **響くキーワード**:
  - `focus` / `flow` / `craft` / `discipline` / `quiet`
  - `code` / `keyboard` / `screen` / `late` / `again`

### Tertiary: Kenji / Lena (25-45歳・非英語圏)

- 雰囲気・ムード維持重視。歌詞の細部より全体の質感
- **響くキーワード**: シンプルで普遍的な英語（高校英語レベル）
- 文化固有表現は避ける

---

## テーマ別偉人マッピング

各 mood tag に対して、**Carla 層に最も刺さる順** に並べた偉人候補。
配信されている `iyashitour.com` 掲載偉人から、ジャンルとトーンが合致する人物のみを採用。

### nostalgia / longing（郷愁・憧憬）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Maya Angelou | `maya-angelou` | 失われた愛・赦し・記憶 | 「感じさせた感情こそが残る」型の名言、女性詩人の温度感 |
| F. Scott Fitzgerald | `f-scott-fitzgerald` | 過ぎた青春・夢の残り香 | "Great Gatsby" 的ノスタルジア、Carla 世代に直撃 |
| Hemingway | `hemingway` | 失われた場所・後悔のない孤独 | 削ぎ落とした文体は歌詞化しやすい |
| Hermann Hesse | `hermann-hesse` | 時の流れの受容・道の途上 | 内省的、知的 Carla 層に届く |
| Ray Bradbury | `ray-bradbury` | 子供時代の夏・記憶の温度 | 詩的描写、視覚化しやすい |

### confidence / pride（静かな自信・誇り）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Martin Luther King Jr. | `martin-luther-king` | 不屈・夢・尊厳 | Soul/Funk 文化の中心人物、Carla 層に正統 |
| Nelson Mandela | `nelson-mandela` | 忍耐・赦し・誇り | 長期視点、年齢を重ねた強さ |
| Muhammad Ali | `muhammad-ali` | 自己肯定・恐れない | カリスマ性、リズム感のある言葉遣い |
| Maya Angelou | `maya-angelou` | "Still I Rise" 系の不屈 | 女性 Carla 層への直撃 |
| Winston Churchill | `churchill` | 諦めない・続ける | シンプルな決意の言葉が多い |

⚠️ MLK / Mandela は強い政治的文脈を伴う名言は除外（`forbidden_topics: politics` に該当）。
人間の尊厳・忍耐・夢に関する普遍的部分のみ採用。

### romance / tenderness（愛・親密さ）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Shakespeare | `shakespeare` | 愛の永続性・時を超える絆 | ソネット由来の言葉は歌詞と相性最高 |
| Victor Hugo | `victor-hugo` | 大いなる愛・献身 | 重さと甘さの両立 |
| Goethe | `goethe` | 知的な愛・憧れ | 大人の恋愛感覚 |
| Saint-Exupéry | `saint-exupery` | 「大切なものは目に見えない」 | 普遍的・誰にでも届く |
| Pablo Neruda | `pablo-neruda` | 官能と詩 | sensual 路線（Amber 系統と整合） |

### groove / freedom（解放・グルーヴ）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Bob Marley | `bob-marley` | One Love・自由 | ジャンル直結、リズム感あり |
| John Lennon | `john-lennon` | Imagine 的理想 | Carla 世代の核 |
| Miles Davis | `miles-davis` | クール・即興・沈黙 | Jazz 圏 Carla への直撃 |
| Louis Armstrong | `louis-armstrong` | "What a Wonderful World" | ポジティブ Soul |
| Duke Ellington | `duke-ellington` | スイング哲学 | "It don't mean a thing..." |

### reflection / wisdom（内省・知恵）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Gandhi | `gandhi` | 内省・非暴力（個人内面） | 政治的部分は除外、内面の知恵のみ |
| Lincoln | `lincoln` | 静かな決意 | 短くて重い言葉が多い |
| Albert Camus | `albert-camus` | 不条理との向き合い | Carla 哲学派へ |
| Dostoevsky | `dostoevsky` | 人間の闇と光 | 重厚、内省的 |
| Tolstoy | `tolstoy` | 単純さの中の深み | 「すべての幸せな家族は…」 |

### dream / future（夢・未来）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Walt Disney | `walt-disney` | 夢を信じる | ポジティブで普遍的 |
| JFK | `jfk` | 大きな決意・希望 | Carla 世代の集合記憶 |
| Picasso | `picasso` | 創造の自由 | 芸術家の魂 |
| Van Gogh | `van-gogh` | 情熱と孤独 | 切実な憧れ |
| Steve Jobs | `steve-jobs` | クラフトマンシップ | Marcus 層にも刺さる |

### good-times（楽しさ・陽気さ）

| 偉人 | スラグ | 響くテーマ | Carla 適合理由 |
|---|---|---|---|
| Mark Twain | `mark-twain` | ユーモア・人生の軽さ | 言葉の切れ味 |
| Oscar Wilde | `oscar-wilde` | 機知・洒落 | 余裕のある成熟層 |
| Frank Sinatra | `frank-sinatra` | My Way 的人生肯定 | Carla 直撃 |
| Elvis Presley | `elvis-presley` | 楽しむ態度 | Funk/Soul 隣接ジャンル |
| Bob Marley | `bob-marley` | Don't Worry Be Happy 的 | 二重登録（groove と兼用） |

### focus（集中・職人気質・Marcus 向け）

| 偉人 | スラグ | 響くテーマ | Marcus 適合理由 |
|---|---|---|---|
| Leonardo da Vinci | `leonardo-da-vinci` | 観察・継続・好奇心 | 万能職人のロールモデル |
| Steve Jobs | `steve-jobs` | フォーカス・削ぎ落とし | "Focus is saying no" |
| Albert Einstein | `albert-einstein` | 想像力・問い続ける | 知的層に直撃 |
| Picasso | `picasso` | 練習と発想 | 二重登録 |
| Miles Davis | `miles-davis` | 余白の哲学 | クラフト視点 |

---

## 選定時のガードレール

### 必ず避ける

- **政治的論争を含む発言**（戦争・特定政党・特定宗教）
- **死を直接扱う発言**（曲のムードによっては可、但し慎重に）
- **特定の人物名を歌詞に出す**（偉人本人の名前 / 同時代の他者の名前）
- **時代固有の固有名詞**（地名・出来事名・書物名）

### 慎重に扱う

- 宗教的背景のある言葉 → 普遍的人間性に開かれた部分のみ抽出
- 戦争体験に基づく言葉 → 「平和への祈り」「日常の尊さ」など普遍化された部分のみ

### 推奨する選定パターン

- **同じ偉人を 1 コレクション内で 2 回使わない**（`max_uses_per_great_person: 2` を 1 にすると完全分散）
- **gender split** 戦略時は male / female 偉人をバランスよく分散（コレクション全体の人称統一は別軸）
- **テーマの広がり**: 全曲が `nostalgia` など同一 mood だと単調になるので、`affinity_weights` のテーマ分布を `suno-patterns.yaml::patterns[].mood` の構成と一致させる

---

## 拡張・更新方針

- 新しい偉人を追加するときは、`config/skills/suno-lyric.yaml::affinity_weights` に追記
- `iyashitour.com` 側で URL 構造が変わった場合は、`config.source.index_path` を上書きするか、本マッピングのスラグを更新
- A/B テストとして「偉人カテゴリ縛り」の曲を作って `/analytics-analyze` のテーマ別パフォーマンスで効果検証
