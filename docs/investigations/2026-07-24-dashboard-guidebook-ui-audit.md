# ダッシュボード情報設計監査

- 実施日: 2026-07-24
- 対象: `dashboard/`
- 関連 issue: #2546
- 一次資料: デジタル庁「[ダッシュボードデザインの実践ガイドブック](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf)」（2024-05-31）
- 公開ページ: [ダッシュボードデザインの実践ガイドブックとデザインテンプレート](https://www.digital.go.jp/resources/dashboard-guidebook)

## 結論

現行画面は必要な値を表示できていた一方、横断ストック表とチャンネル概要カードで情報が重複し、データの対象期間・鮮度・指標定義が一か所にまとまっていなかった。初期表示を「概況 → データの前提と指標定義 → チャンネル比較 → 選択したチャンネルの詳細」の順へ再構成し、比較行から詳細へ進める形にすると、ガイドブックの「全体から部分へ」の原則と利用者の判断順が一致する。

## ガイドブックから採用した原則

| ページ | 原則 | 今回の適用 |
| --- | --- | --- |
| p.4 | 数値を分かりやすく可視化し、共通認識、意思決定の質、より良い行動につなげる | 見た目の装飾ではなく、在庫・データ鮮度・要確認状態を最初に判断できる構成を優先 |
| p.20 | 情報の優先度と関係性を考慮して、大きさと順番を決める | 概況を先頭、比較を次、動画詳細を最後に配置 |
| p.21 | 最終像には指標定義、分類定義、更新頻度、閾値などの補足を記載する | 対象期間、最終更新時刻、主要指標の定義を初期表示へ追加 |
| p.22 | 全体から部分へ階層化し、適切な情報量、少ない操作、比較対象を提供する | 重複カードを廃止し、選択なしで全チャンネルを比較可能にしたうえで、比較行から1操作で詳細表示 |
| p.23 | 視線に沿い、左上で全体、右下で判断や行動に役立つ詳細を示す | 縦スクロールでも同じ認知順になるよう、上から概況・比較・詳細の順に固定 |
| p.24 | 全体感を表す指標から詳細情報へ流れるように設計し、更新日時を示す | 概況カードに登録数・公開予約・要確認数、隣接カードに対象期間・最終更新を表示 |
| p.25 | 多くの情報を一覧する場合は表を使い、更新日時を明示する | チャンネル比較を表として維持し、各行の収集時刻を表示 |

## 35ページ：カラーパレット

一次資料: [ガイドブック p.35「4.3 カラーパレット」](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=35)

### 一次資料から読み取れるルール

- グラフ色はデジタル庁デザインシステムのカラーパレットから、p.35 に示された組み合わせを使う。
- 1〜3色のグラフは、表中で太字になっている3明度を使う。4〜5色のグラフは、同じ色相に示された5明度すべてから選ぶ。
- 選択肢は次の10色相である。括弧内は「1〜3色の場合」の太字候補、その後は4〜5色時に追加できる中間明度。
  - Blue: `#D9E6FF` / `#4979F5` / `#0017C1`（追加: `#9DB7F9` / `#264AF4`）
  - Light Blue: `#C0E4FF` / `#008BF2` / `#00428C`（追加: `#57B8FF` / `#0066BE`）
  - Cyan: `#99F2FF` / `#00A3BF` / `#006173`（追加: `#2BC8E4` / `#008299`）
  - Green: `#C2E5D1` / `#259D63` / `#115A36`（追加: `#71C598` / `#197A4B`）
  - Lime: `#D0F5A2` / `#6FA104` / `#2C4100`（追加: `#8CC80C` / `#507500`）
  - Yellow: `#FFE380` / `#B78F00` / `#6E5600`（追加: `#EBB700` / `#927200`）
  - Orange: `#FFDFCA` / `#FB5B01` / `#8B3200`（追加: `#FFA66D` / `#C74700`）
  - Red: `#FFDADA` / `#FF5454` / `#A90000`（追加: `#FF9696` / `#EC0000`）
  - Magenta: `#FFD0FF` / `#F137F1` / `#8B008B`（追加: `#FF8EFF` / `#C000C0`）
  - Purple: `#ECDDFF` / `#A565F8` / `#5C10BE`（追加: `#CDA6FF` / `#8843E1`）
- パレット下の `3:1→` と `4.5:1→` は、白背景 `#FFF` を1としたコントラスト比の目安であり、右側の濃い明度ほどコントラストが強い。したがって、色を選んだだけで可読性が保証されるわけではなく、背景と用途を含む組み合わせで確認する必要がある。
- p.35 が示すコントラスト目安は白背景用である。現行ダッシュボードのダークモードについては、同じ色値を機械的に流用せず、実際の背景トークンとのコントラストを別途検証する。

### 現行UIとの差と適用可能な制約

| 優先度 | 現状・リスク | 具体的な制約／実装候補 |
| --- | --- | --- |
| P1 | `index.css` の `--chart-1`〜`--chart-5` は無彩色で、p.35 の指定セットと対応していない | 通常のチャートは Blue を既定色相とし、系列数1〜3では `Blue 100 / 500 / 900`、4〜5では `Blue 100 / 300 / 500 / 700 / 900` を順序付きチャートトークンとして定義する |
| P1 | ライト・ダークで同じチャート色を使っており、p.35 の白背景コントラスト目安をダーク背景へ外挿している | `--chart-*` を light/dark で分け、文字、線、塗り、背景の各組み合わせをコントラスト検査する。検査を通らない淡色はダーク背景用トークンへ置換する |
| P1 | ストック状態は Badge の色に意味がある | 色だけに依存せず、既存の「正常」「未収集」「更新失敗」等の文言を必須とする。アイコンや形状も補助にできるが、状態名を除去しない |
| P2 | 現在は単一系列のため、5色を常時用意しても利用目的が不明瞭 | 単一系列は1色、比較対象が増えたときだけ必要な系列数まで使う。装飾目的で色相を増やさず、同一意味の系列には画面間で同じトークンを割り当てる |
| P2 | warning / destructive の意味色とチャート系列色が衝突し得る | Red / Orange / Yellow は状態表示へ優先的に予約し、通常データ系列の既定には Blue を使う。意味色を系列に使う場合も状態Badgeとの混同がないラベルを併記する |
| P2 | p.35 の比率表示だけでは、小さい文字、太いグラフ線、面塗りなど用途別の合否を一律に決められない | 色トークン名に「accessible」を含めて合格を推測せず、コンポーネントごとに前景・背景・サイズを含めたテスト条件を固定する |

補足として、ガイドブックは「色のみで分類を識別しない」（[p.41](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=41)）、「色だけでなく数値を併記するなど代替手段を提供する」（[p.55](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=55)）とも明記している。p.35 のパレット採用と、色以外の情報経路の維持はセットで扱う。

### テスト観点

- light/dark の各テーマで、採用する全チャートトークンと実際の背景とのコントラストを自動検査する。
- 1〜3系列では各色相の太字3明度だけ、4〜5系列では指定された5明度だけが使われることをトークン単位で確認する。
- CSSを無効化した場合、または色覚シミュレーション下でも、状態名、数値、系列ラベルから同じ情報を取得できることを確認する。
- chart のアクセシビリティツリーまたは代替表で、色に依存せず系列名と値を読み取れることを確認する。
- visual QA はライトとダークの両方で実施し、淡色のバー、軸ラベル、tooltip、Badge の文字が背景へ埋没しないことを確認する。

## 36・37ページ：役割別配色とコントラスト

一次資料:

- [ガイドブック p.36「4.3 カラーパレット — 組み合わせ」](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)
- [ガイドブック p.37「4.3 カラーパレット — コントラスト比の考え方」](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)

### 36ページの具体的ルール

p.36 は、テキスト、背景、表、グラフの色を役割別に分け、Blue を基準とする次の組み合わせを提示している（[p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)）。

| 用途 | 役割と指定色 |
| --- | --- |
| テキスト | Body `#1A1A1A`、Description `#626264`、On Fill `#FFFFFF`、Link `#0017C1`、Positive Number `#0031D8`、Negative Number `#FA0000` |
| 背景 | Primary `#0031D8`、Secondary `#F8F8FB`、Positive `#E8F1FE`、Negative `#FDEEEE` |
| 境界 | Field `#1A1A1C`、Divider `#D8D8DB` |
| グラフ・表内データバー | Positive Bar `#0031D8`、Negative Bar `#FA0000`、Positive Data Bar `#C5D7FB`、Negative Data Bar `#FFBBBB` |

- 正負の値は、正数用の青／淡青背景と、負数用の赤／淡赤背景を組み合わせる。例では符号も `+1,000` / `-1,000` と明記され、表のデータバーにも数値が併記されている（[p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)）。
- Primary 背景では白文字、Secondary 背景では Body 色、Positive / Negative 背景では対応する Positive / Negative Number 色という「前景と背景の組」を適用例として示している（[p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)）。

### 37ページの具体的ルール

- アクセシビリティ対応では、背景色とグラフ色面のコントラスト比を `3:1` 以上にする（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 白背景で Blue パレットをキーカラーにする例では、グラフ色を Blue-500 `#4979F5` 以上の濃さにする（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 色面が `3:1` を満たせない場合は、色面のすぐ近くに数値を記載する。近接表示できない場合は、マウスオーバーまたはキーボードフォーカス時に数値を表示する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 代替として表示する数値の色は、その背景に対して `4.5:1` 以上を確保する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 多色グラフでは、色覚多様性を考慮し、推奨配色、色覚特性シミュレーション／チェッカーを使って識別しにくい組み合わせを調整し、色以外の識別方法も提供する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。

### 現行dashboardへの適用候補

| 優先度 | 現状 | 適用候補 | 根拠 |
| --- | --- | --- | --- |
| P1 | 白背景の `--chart-1` は淡い無彩色であり、棒の輪郭を背景から判別しにくい | 単一系列の棒は最低でも Blue-500 `#4979F5` 相当へ変更し、実背景との比率を `3:1` 以上にする | [p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37) |
| P1 | グラフ値は tooltip で確認できるが、ポインター操作に偏る可能性がある | Recharts の各棒をキーボードでフォーカス可能にし、hover と focus の両方でタイトル・再生数を表示する。可能なら棒の末尾へ値を常時表示する | [p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37) |
| P1 | 正常・warning・destructive は独自の色トークンで、数値の正負と状態の重大度が同じ色語へ混在し得る | `positive-number` / `negative-number`、`positive-surface` / `negative-surface`、`status-warning` / `status-destructive` を別トークンにし、意味を混同しない | [p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36) |
| P2 | 純増登録者は符号を表示するが、詳細サマリーでは正値の `+` がなく、画面間の表記が揃っていない | 増減を意味する指標だけは、正負色に加えて `+` / `-` とラベルを一貫して表示する | [p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36) |
| P2 | ライト／ダークで色の役割名は共通だが、実際の組み合わせの合否が固定されていない | p.36 のHEXはライトテーマの基準として扱い、ダークテーマは同じ意味役割を維持した別値を用意して、前景・背景の組ごとに再測定する | [p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)、[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37) |

### 避けるべき誤読

- p.35 の「1〜3色では太字の明度を使う」は、淡い Blue-100 を白背景のグラフ色に無条件で使ってよいという意味ではない。アクセシビリティ対応時は p.37 の `3:1` 制約が加わり、白背景の例は Blue-500 以上である（[p.35](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=35)、[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- `3:1` を満たさない色面に tooltip を付ければ常に十分、という意味ではない。p.37 はまず近接した数値を挙げ、難しい場合にもマウスだけでなくキーボードフォーカスで値を表示するよう求めている（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- `Positive` は業務上の「正常状態」、`Negative` は「システムエラー」と同義ではない。p.36 の例は増減値とデータバーの正負であり、更新失敗等の状態分類は別の意味設計が必要である（[p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)）。
- p.36 のHEX値をダークテーマへそのまま移植すれば適合する、とは書かれていない。適合対象は実際の背景と前景の組み合わせなので、テーマごとの測定が必要である（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 色覚多様性への配慮は「赤と緑を避ける」だけでは完了しない。p.37 はシミュレーション／チェッカーによる確認、組み合わせの調整、色以外の識別方法を併記している（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。

### テスト観点

- light/dark の各テーマで、グラフ色面と実背景のコントラストが `3:1` 以上であることを計算する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 値ラベル、tooltip、focus時の数値と背景のコントラストが `4.5:1` 以上であることを計算する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- マウスを使わず Tab / 矢印キーでグラフデータへ移動し、各動画名と再生数を取得できることをE2Eで確認する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。
- 正負の値について、色を除去しても符号、数値、ラベルから意味が分かり、Positive / Negative の前景・背景トークンが意図した組で使われることを確認する（[p.36](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=36)）。
- 代表的な色覚特性シミュレーションで系列と状態を確認し、識別困難な組み合わせがあれば線種、記号、ラベルを追加する（[p.37](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/1948e3cd-736a-4378-9e31-039b08d11106/a119bc3c/20240531_resources_dashboard-guidebook_guidebook_01.pdf#page=37)）。

## 実装前の主なギャップ

1. 「チャンネル横断ストック」と「チャンネル概要」に同じ指標が重複し、最初に見るべき場所が分散していた。
2. 対象期間と最終更新時刻がチャンネル行に分散し、画面全体のデータ前提が読み取りにくかった。
3. 「公開予約」「期間再生数」などの意味を画面内で確認できなかった。
4. 狭幅画面では横長の比較表を内部スクロールする必要があり、右側の指標や詳細導線を見落としやすかった。
5. snapshot がないチャンネルも「正常」と表示され、データ取得状態を誤認する余地があった。

## 実装との対応

- `DashboardOverview` を追加し、登録チャンネル数、公開予約合計、要確認数、未取得数を集約した。
- 対象期間は登録チャンネルの期間範囲、最終更新は最新の収集時刻として明示し、チャンネルごとの差異があり得ることを注記した。
- 「指標の見方」で公開予約、期間再生数、純増登録者、総再生時間を定義した。
- チャンネル概要カードを削除し、比較表へ詳細ボタンを統合した。
- 比較表は desktop では表、狭幅では同じ行を縦積みカードとして表示し、横方向の見切れをなくした。
- `missing_snapshot`、`invalid_snapshot`、`invalid_channel`、起動時更新失敗を別の状態名で表示し、概況の「要確認」に集約した。

## 検証観点

- unit: 概況、データ前提、指標定義、比較がこの順で表示されること。
- unit: チャンネル選択前から主要指標を比較でき、比較行から詳細へ進めること。
- unit: 未収集や更新失敗を正常と誤表示せず、要確認件数へ含めること。
- E2E: 760px 幅でページと比較表に横 overflow がなく keyboard で詳細へ進めること、および 768px の breakpoint 境界でも操作が見切れないこと。
- visual QA: 390px 幅で文言・カード・比較行が viewport 内に収まり、desktop と同じ判断順を維持すること。

## 残課題

- 現在の概況値は期間比較を持たないため、増減の判断には前回値・目標値の read model 追加が必要。
- チャンネルごとに対象期間が異なる場合、現状は全体範囲と注記を示す。厳密な横比較が必要なら共通期間への正規化が必要。
- 指標定義は常時表示のため、指標が増えた場合は情報量を再評価する。
