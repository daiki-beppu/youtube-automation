# 国別 CPM 参考値の出典

`utils/localization_strategy.py::COUNTRY_CPM_USD` は以下の公開ソースから抽出した参考値で、実 AdSense 値ではない。半年ごとに数値の妥当性を再評価すること。

## 出典 (2026 Q1)

| 出典 | アクセス日 | 範囲 |
|---|---|---|
| [upgrowth.in - YouTube CPM by Country 2026](https://upgrowth.in/youtube-cpm-by-country-global-comparison-2026/) | 2026-02-21 | 22 ヶ国 (AU/US/CA/NZ/GB/CH/DE/NO/IE/SG/DK/HK/SE/FI/ES/IL/PT 等) |
| [lenostube.com - YouTube CPM & RPM Rates 2026](https://www.lenostube.com/en/youtube-cpm-rpm-rates/) | 2026-04-02 | JP / AT / SG / IN / MX 等補完 |
| [fluxnote.io - Highest Paying YouTube Countries 2026](https://fluxnote.io/guides/highest-paying-youtube-countries-2026) | 2026-03-06 | FR / KR (レンジ提示) |
| [ytface.com - YouTube CPM Rates 2026](https://www.ytface.com/cpm-rates-by-country) | 2026-05-21 | Top 10 構成照合 |
| [creaticalc.com - YouTube CPM Rates 2026](https://creaticalc.com/blog/youtube-cpm-rates-by-country) | 2026-05-21 | NO / CH 順位の照合 |
| [mediacube.io - Average YouTube CPM 2026](https://mediacube.io/en-US/blog/youtube-cpm) | 2026-05-21 | Top 10 構成照合 |

## Top 10 CPM 国 (MANDATORY_LANGUAGES の根拠)

| Rank | Country | ISO | CPM (USD) | Primary Language |
|---|---|---|---|---|
| 1 | Australia | AU | 36.21 | en |
| 2 | United States | US | 32.75 | en |
| 3 | Canada | CA | 29.15 | en |
| 4 | New Zealand | NZ | 28.15 | en |
| 5 | United Kingdom | GB | 24.00 | en |
| 6 | Switzerland | CH | 23.13 | de |
| 7 | Germany | DE | 22.00 | de |
| 8 | Norway | NO | 20.17 | no |
| 9 | Ireland | IE | 19.50 | en |
| 10 | Singapore | SG | 18.28 | en |

導出される `MANDATORY_LANGUAGES = {"en", "de", "no"}`。半年ごとの再評価時に Top 10
構成が入れ替わったら `TOP_CPM_COUNTRIES` を更新するだけで `MANDATORY_LANGUAGES` も自動追従する。

## 採用ルール

- 複数出典で値が異なる場合は **upgrowth を優先**（更新頻度・カバー範囲が広い）
- レンジ提示の国 (FR / KR = $2-5 など) は **中央値** を採用 (FR/KR = 3.50)
- 未登録国は `DEFAULT_CPM_FALLBACK_USD = 5.0`（lenostube 公開の world median）

## 見直し基準

- **半年ごと** に上記出典を再取得し、数値の最新化を行う
- 出典側の更新日が古いまま停滞している場合は新規ソースを探す
- リポジトリの実 AdSense レポートと顕著に乖離する国があれば個別に補正値メモを残す

## 制約

- YouTube Analytics API では `country × cpm` クロス集計は取得不可 (API 仕様の制約)
- AdSense Management API 統合は将来 issue として検討（本 skill のスコープ外）
- 同言語国でも CPM 差が大きい (ES vs MX、PT vs BR、CH vs CN-寄せ国など)。
  CPM ベースで言語選定するときは `top_countries` での国別内訳確認を必須とする

## 多言語国の主要言語寄せ方針

`COUNTRY_TO_PRIMARY_LANGUAGE` は約 90 ヶ国を網羅する。多言語国を扱うとき、視聴シェア集計の
精度を確保するため **広告言語として優勢な単一言語に寄せる**。判断分かれる主なケース:

| 国 | 寄せ言語 | 理由 |
|---|---|---|
| BE (ベルギー) | fr | nl/fr 混在だが YouTube 広告では fr のリーチが広い |
| LU (ルクセンブルク) | fr | fr/de/lb 混在、広告言語として fr が優勢 |
| CH (スイス) | de | de/fr/it 混在、視聴シェア最大は de |
| CA (カナダ) | en | en/fr 混在、視聴シェア最大は en |
| SG (シンガポール) | zh-CN | en/zh/ms 混在、コンテンツ消費は zh が大きい |
| PH (フィリピン) | tl | en/tl 公用語、シェア集計上は tl を採用 |
| MA (モロッコ) | ar | ar/fr 混在、ar 寄せ |
| KZ (カザフスタン) | ru | kk が公用語だが ru が広告言語として優勢 |
| BY (ベラルーシ) | ru | be が公用語だが ru が優勢 |
| IN (インド) | hi | en/hi 多言語国、最大シェアは hi |

**この寄せ方針は推奨ロジックにも影響する** — `country_cpm × views` の単純積算で言語別収益を
出す仕組みのため、寄せ先言語が違うと推奨が systematically にずれる。半年ごとの見直し時に
寄せ方針も併せて再評価すること。
