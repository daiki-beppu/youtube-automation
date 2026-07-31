# 再配置の follow-up 候補

今回の再配置では、canonical owner への移動と production import の更新を完了した。
下流互換性のための façade は削除せず、内容分割候補も変更せずに別タスクとして残す。

| 対象 | 根拠 | 影響範囲 | 推奨対応 | 必要な検証 |
|------|------|----------|----------|------------|
| `src/youtube_automation/infrastructure/legacy_utils/` compatibility façade | 下流 import と installed wheel が旧公開面を参照する | 下流 package、skill、利用者 | 利用状況を棚卸しし、deprecation 方針と削除時期を決定する | source / installed wheel の旧 import、sdist、全体テスト |
| `commands/system/doctor.py`（3611行） | system 診断責務が単一ファイルに集中している | doctor CLI、診断テスト | readiness、workspace、asset 診断へ分割を検討する | CLI 終了コード、診断出力、全 doctor テスト |
| `commands/collections/collection_serve.py`（1913行） | collection serve の HTTP、registry、監視責務が集中している | collection serve CLI、loopback protocol | server lifecycle、registry、request handling へ分割を検討する | protocol、heartbeat、競合、停止処理 |
| `commands/analytics/benchmark_collector.py`（1355行） | 収集、API 呼出し、解析、保存責務が集中している | benchmark CLI、analytics data | orchestration と provider adapter の分割を検討する | API 失敗、解析失敗、atomic 保存、CLI 契約 |
| `configuration/loader.py`（1254行） | 設定 section 構築と cross-validation が集中している | `load_config()`、下流設定 schema | section builder と validation registry の分割を検討する | 全 section、必須キー、旧設定拒否、下流 fixture |

内容分割・facade 削除はいずれも今回の再配置範囲外であり、実施時は公開契約と配布物を先に固定する。
