# MiniMax Music 3 の M4 / 16GB ローカル実行調査（Issue #4117）

## 結論

- **判定: No-Go。** 現在の MacBook Air M4 / 16GB では、安全条件を守ったローカル実測に到達できない。調査時の空き容量は issue 記載の 39GB ではなく **11.90GiB** であり、公式 checkpoint は **57.4GB**、ComfyUI の最小配布構成でも **約11.9GB** ある。取得後 10GB を残す停止条件に反するため、重みの download、runtime の導入、1曲生成は実施しなかった。
- 公式 MiniMax 経路は SGLang-Omni で、**2基の CUDA GPU が必須**と明記されている。この Mac では使えない。llama.cpp と MLX には MiniMax Music 3 の実装を確認できなかった。
- ComfyUI には native support が 2026-08-13 に merge され、ComfyUI 自体は Apple Silicon を対象に含む。ただし MiniMax Music 3 の公開実測は NVIDIA CUDA 機だけで、MPS の動作、速度、ピークメモリは確認されていない。したがって「Apple Silicon で合格ラインを満たす経路」とは判定しない。
- ライセンスは日本を除外しておらず、商用利用を禁止していない。ただし商用 UI への `MiniMax-Music3` 表示、年商2,000万米ドル超での事前許諾、生成物の AI 表示などの条件がある。ライセンス条件だけは合格し得るが、技術条件2件を確認できないため総合判定は No-Go とする。

> 調査日: 2026-08-16（Asia/Tokyo）。モデル、runtime、量子化、価格、ライセンス、空き容量は変わり得るため、再評価時に確認し直すこと。本書は技術・契約情報の整理であり、法的助言ではない。

## 1. 実機と安全停止

秘密情報を含む serial number / hardware UUID は記録せず、次の項目だけを読み取った。

| 項目 | 実測結果 |
|---|---|
| 機種 | MacBook Air（Mac16,12） |
| SoC | Apple M4、10 cores（4 Performance + 6 Efficiency） |
| unified memory | 16GB |
| `/` の空き容量 | 12,482,356KiB = **11.90GiB** |
| ローカル runtime | `llama-cli` / `mlx_lm` / `comfy` なし |
| Python package | `mlx` / `torch` / `comfy` なし |

確認には `system_profiler SPHardwareDataType`、`df -k /`、`command -v`、Python の `importlib.util.find_spec()` を使った。モデル、ComfyUI、PyTorch、MLX は取得・install していない。Hugging Face の license と tree metadata は認証なしの読み取りだけを行い、checkpoint blob は取得していない。

issue の停止条件は「取得後の空きが10GB未満なら中断」である。現在消費できる余裕は約1.90GiBしかなく、後述の最小構成約11.9GBを取得できないため、1曲生成より前に安全停止した。外付けストレージは本 issue のスコープ外である。

## 2. 重みの容量

### 2.1 公式 checkpoint

[MiniMaxAI/MiniMax-Music3 の tree](https://huggingface.co/MiniMaxAI/MiniMax-Music3/tree/main) は repository 全体を **57.4GB** と表示する。主な内訳は次のとおりである。

| component | 配布サイズ |
|---|---:|
| `language_model/` | 17.2GB |
| `qwen_7B/` | 18.5GB |
| `transformer/` | 9.73GB |
| `rvq_depth_decoder/` | 1.29GB |
| `condition_encoder/` | 101MB |
| `vocoder/` | 217MB |
| root の `flowmatching_vae.pth` | 9.83GB |
| root の `dav.pth` | 492MB |

公式 README の `hf download MiniMaxAI/MiniMax-Music3` は repository 全体を取得する手順である。現在の空き容量にも16GB memoryにも収まらない。

### 2.2 ComfyUI repack

[Comfy-Org/MiniMax-Music-3](https://huggingface.co/Comfy-Org/MiniMax-Music-3/tree/main) は複数精度を含めて61.8GBである。必要な3 componentだけを選ぶ場合の最小候補は次の構成になる。

| component | 最小候補 | サイズ |
|---|---|---:|
| text encoder | `minimax_music3_text_encoder_pruned_int8_convrot.safetensors` | 9.2GB |
| DiT | `minimax_music3_dit_int8_convrot.safetensors` | 2.5GB |
| DAV | `minimax_music3_dav.safetensors` | 217MB |
| **合計** |  | **約11.9GB** |

BF16/FP16系の小さい組み合わせでも、pruned BF16 text encoder 16.7GB + FP16 DiT 4.91GB + DAV 217MB = **約21.8GB** である。INT8構成は配布容量だけで現在の安全余裕を約10GB超過し、runtime、cache、生成物の容量も別途必要になる。したがって量子化重みも取得しなかった。

## 3. Apple Silicon 推論経路

確認対象と、2026-08-16時点の結果を示す。検索結果がないことだけで将来の非対応を断定せず、今回確認した公式 repository / documentation の状態として記録する。

| 経路 | 確認結果 | 判定 |
|---|---|---|
| 公式 SGLang-Omni | [公式 README](https://github.com/MiniMax-AI/MiniMax-Music3#serve-with-sglang-omni) は GPU 0でQwen3+RVQ、GPU 1でFlow Matching+DAVを動かし、limitationsにも「2 CUDA GPUs required」と明記 | Apple Silicon不可 |
| llama.cpp | [llama.cpp](https://github.com/ggml-org/llama.cpp) の repository / docsを `MiniMax-Music3` と `MiniMax Music 3` で確認したが、Music 3固有のarchitecture、audio decoder、実行例を確認できず。手元にも`llama-cli`なし | 対応経路を確認できず |
| MLX | [MLX examples](https://github.com/ml-explore/mlx-examples) を同じ語で確認したが、Music 3のGlobal/Local LLM + Flow Matching + DAVを通す実装を確認できず。手元にもMLXなし | 対応経路を確認できず |
| ComfyUI | [PR #15570](https://github.com/Comfy-Org/ComfyUI/pull/15570) がnative supportをmerge。非CUDA device向けstop checkも含む一方、公開benchmarkはRTX 5090/3060/5060だけで、MPS結果なし。高速化の中心はCUDA Graphs | **理論上の候補だが、このMacでの対応・性能は未検証** |

[ComfyUI system requirements](https://docs.comfy.org/installation/system_requirements) は一般論として Apple Silicon M1〜M4 と Metal acceleration を対応対象にする。しかし、これは MiniMax Music 3 の全operator、INT8 ConvRot、offload、必要memoryをMPSで保証する資料ではない。MiniMax公式が案内する経路も現在はSGLang-Omniだけである。

ComfyUI PR の120秒生成benchmarkでは、CUDA Graphs有効時でも RTX 5060 / system RAM 48GB が1096.2秒、RTX 3060 / 48GBが538.8秒である。CUDA機の値をM4へ外挿する根拠はないため、Apple Siliconの所要時間としては使わない。

## 4. 合格ラインとの照合

| # | 条件 | 観測結果 | 判定 |
|---|---|---|---|
| 1 | 8曲 × 約3分を8時間以内 | 対応が確認できた公式経路は2基CUDA。ComfyUI MPSの実測経路は確立できず、disk停止条件により1曲生成も未実施。CUDA benchmarkはM4へ外挿しない | **不合格（確認不能）** |
| 2 | peak memory 12GB以内 | 生成未実施のためpeak未測定。最小INT8配布だけで約11.9GBあり、16GB unified memoryでruntime/activation/OS込み12GB以下とする公式根拠もない | **不合格（確認不能）** |
| 3 | 日本でのlocal実行と収益化YouTube | licenseに地域除外なし。商用利用は条件付きで許容される | **条件付き合格** |

1と2は「未測定だから保留」ではない。現実機の容量とissueの安全停止条件では、その測定を開始できず、採用条件を証明できないため不合格として閉じる。

## 5. ライセンス

[MiniMax-Music3 COMMUNITY LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE) を確認した。

- 使用、複製、変更、配布等を許諾し、地域を列挙した除外条項はない。日本は除外されていない。
- 商用利用そのものは禁止されていないが、商用product/serviceのUIへ `MiniMax-Music3` を目立つ形で表示する必要がある。
- 当該product/service群の年商が2,000万米ドルを超える場合、MiniMaxへの事前の書面許諾が必要である。
- Acceptable Use Policyは、公開環境に生成物を出す場合にAI生成であることの明確な表示を求め、第三者の知的財産権侵害を禁止する。
- YouTube収益化を一律禁止する条項はないため、上記表示義務、AI生成表示、権利確認、収益閾値を満たす限り許諾範囲に入り得る。実運用前にはチャンネル上で「UI表示」をどこに置けば足りるかを法務確認する。

## 6. 再評価条件

次の全てを満たした時点で、別issueとして実測をやり直す。

1. 内蔵diskで、選択したcheckpoint、runtime、cacheを取得後も10GB以上残せる。現在のINT8構成なら、少なくとも追加で約12GBを空けるだけでなく、install/cache/一時生成物用の余裕も確保する。
2. ComfyUIがMiniMax Music 3のMPS実行を公式に検証するか、MLX等にApple Silicon向け実装と再現手順が公開される。
3. 3分の1曲を生成し、wall time、`powermetrics`等で取得可能なmemory指標、出力尺、32kHz/16-bit/stereo WAVを記録できる。
4. 同一設定を8曲へ外挿し、8時間以内とpeak 12GB以内の両方を満たす。
5. 実運用時点のlicenseを再読し、commercial UI表示とAI生成表示の方法を確定する。

本調査では `music_engine="minimax"`、設定schema、skill、生成codeを変更しない。既存のSuno / Lyria経路を維持する。

## 参照した一次資料

- [MiniMax-AI/MiniMax-Music3 README](https://github.com/MiniMax-AI/MiniMax-Music3)
- [MiniMaxAI/MiniMax-Music3 weights](https://huggingface.co/MiniMaxAI/MiniMax-Music3/tree/main)
- [MiniMax-Music3 COMMUNITY LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE)
- [ComfyUI MiniMax Music 3 support PR #15570](https://github.com/Comfy-Org/ComfyUI/pull/15570)
- [Comfy-Org repacked weights](https://huggingface.co/Comfy-Org/MiniMax-Music-3/tree/main)
- [ComfyUI system requirements](https://docs.comfy.org/installation/system_requirements)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [MLX examples](https://github.com/ml-explore/mlx-examples)
