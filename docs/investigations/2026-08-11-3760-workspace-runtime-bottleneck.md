# workspace 実行時間のボトルネック調査（#3760）

## 結論

現行の 6-channel workspace では、実行時間を支配するのは workspace hook やチャンネル解決ではなく、人間の承認・認証復旧、Suno のブラウザ処理、制作 subagent、ffmpeg の直列処理だった。実セッション 1 件で progress hook が 174 回起動しても反復値からの累積推計は 9.24 秒である。一方、同じセッションの認証復旧待ちは 9,043 秒、別セッションの承認待ちは最大 3,340 秒、Suno の生成・ダウンロード区間は 561--1,020 秒だった。

ローカルで独立して改善でき、既存の Suno 高速化 issue（#3301、#3302）とも重ならない先頭候補は、`masterup` で同じ 12 曲に対して直列実行されたラウドネス検査 88 秒と 67 秒の二重化である。この結果から [#3777](https://github.com/daiki-beppu/youtube-automation/issues/3777) を切り出した。

## 調査条件と再現方法

- 計測日: 2026-08-11（Asia/Tokyo）
- ホスト: macOS 26.6.1 (25G76)、Darwin 25.6.0 arm64、Apple M4、16 GiB RAM
- ツール: uv 0.11.26、Python 3.14.6、ffmpeg 8.1.2、Determinate Nix 3.17.0 / nix 2.33.3
- 対象: `/Users/mba/02-yt/youtube-channels-workspace`。`channels/` 以下の有効ディレクトリは `001ch-afro-deep-noir` から `006ch-harana-island-sounds` までの 6 件
- provider: 現行の制作実績は Suno、画像生成は Gemini/Vertex ADC、公開は YouTube OAuth。現行ログに Lyria CLI の完走記録はない
- 短いローカル処理は warmup 3 回後に 21 回（Nix は 7 回、代表 CLI は 11 回）を同一ホストで `perf_counter` 計測し、中央値と最小--最大を記録した
- 制作フローは Claude の実セッション JSONL、各 tool の開始・終了、subagent の `totalDurationMs`、成果物の mtime を突合した。外部サービス内部の時刻がない区間は、その境界間の実測幅として記録し、fixture の値に置換していない

再現コマンドの基本形は次のとおり。各コマンドを上記回数繰り返し、プロセス起動直前から終了直後までを測る。

```bash
cd /Users/mba/02-yt/youtube-channels-workspace
uv run yt-workspace-guard context
uv run yt-channel list
nix develop --command uv run yt-workspace-guard context

cd channels/002ch-deepfocus365
uv run python -c \
  'from youtube_automation.configuration import load_config; print(load_config().workflow.post_publish.configured)'
```

チャンネル解決の関数単位計測は workspace の `.venv` で 1 Python プロセスを起動し、同一関数を 101 回呼んだ。cold route は import 後に cache を毎回消して 31 回計測した。チャンネル数依存だけは実在 6 ディレクトリへの symlink を一時ディレクトリに 1 件ずつ配置した制御比較であり、架空の制作データは使っていない。

workspace の `.claude/settings.json` とリポジトリの `.claude/settings.template.json` で hook コマンドに差はない。workspace は Edit と Write の matcher を別 group に分け、SessionStart に `matcher: null` を明記しているだけで、実行内容は同じである。

## 領域 1: hook と CLI 起動

### 反復値

| 項目 | 中央値 | 最小--最大 | 読み取り |
| --- | ---: | ---: | --- |
| OS process (`true`) | 2.00 ms | 1.76--3.24 ms | process 下限 |
| `.venv` Python (`pass`) | 13.04 ms | 12.13--13.81 ms | interpreter |
| `uv run python` (`pass`) | 29.02 ms | 27.09--32.68 ms | uv の増分は約 16 ms |
| loader import（direct） | 50.68 ms | 49.05--59.39 ms | import が hook の固定費を支配 |
| loader import（uv） | 67.45 ms | 65.40--148.39 ms | uv + import |
| guard `context`、workspace root（uv） | 72.71 ms | 68.71--80.00 ms | hook 本体は数 ms |
| guard `context`、channel cwd（uv） | 72.30 ms | 68.32--106.66 ms | cwd による差は見えない |
| guard `check`（uv） | 72.53 ms | 69.84--88.80 ms | prefilter を含む |
| progress hook / Bash（uv） | 53.18 ms | 49.87--69.13 ms | JSON parse、非表示ケース |
| progress hook / Agent（uv） | 53.06 ms | 51.62--61.74 ms | 表示ケース |
| `nix develop --command true` | 874.90 ms | 839.52--989.69 ms | devShell 起動固定費 |
| Nix + guard `context` | 1,051.77 ms | 956.73--1,609.59 ms | hook ごとに Nix を挟まない根拠 |
| `yt-channel list`（uv） | 97.63 ms | 90.92--110.14 ms | 代表 CLI |
| `yt-collection-preflight`（uv） | 596.73 ms | 591.56--606.09 ms | 設定・collection 検査を含む |

`/wf-next` の実セッション `38fd0c2b-8247-4057-9f17-68891d42798c` では Bash 82 回、Agent 5 回が `Bash|Task|Agent|Workflow` matcher に一致した。Pre/Post の 2 回で 174 launch となり、53.1 ms の中央値を掛けた累積推計は 9.24 秒（反復幅では 8.67--12.13 秒）である。SessionStart guard は 1 回約 72.7 ms だった。これは実際の matcher 回数と単体反復値の併用であり、JSONL に hook 自身の終了時刻がないため累積値は推計である。

### 起動と本体の分離

progress hook の direct 34.8 ms に対し uv 経由は 53.1 ms、guard の direct 53--59 ms に対し uv 経由は約 72.5 ms だった。uv の約 18 ms、Python/import の 35--51 msが大半で、JSON parse、matcher 分類、workspace 解決という本体差は小さい。`nix develop` を都度使うと約 1 秒になるが、現行 settings の hook はこれを行っていない。

## 領域 2: チャンネル解決

### 関数単位と入口別 cold route

| 項目 | 中央値 | 最小--最大 |
| --- | ---: | ---: |
| `find_workspace_root(root)` | 0.0711 ms | 0.0686--0.0833 ms |
| `find_workspace_root(channel)` | 0.0895 ms | 0.0788--0.1624 ms |
| `workspace_channels()`（実在 6 件） | 0.0636 ms | 0.0580--0.0801 ms |
| `_resolve_slug()`（実在 6 件） | 0.0705 ms | 0.0581--0.0967 ms |
| `load_config_from_path()` | 0.3923 ms | 0.3367--0.4352 ms |
| channel cwd | 0.5012 ms | 0.4658--0.6272 ms |
| root + `--channel` | 0.5341 ms | 0.5255--1.4651 ms |
| root + `CHANNEL` | 0.5250 ms | 0.5139--0.5841 ms |
| root、selector なしの fail-fast | 0.1843 ms | 0.1794--0.1988 ms |

単一チャンネル形式との比較には、実在チャンネルの `config` symlink を一時 root 直下へ置いた制御投影を用いた。cold cwd は 0.4321 ms（0.4174--0.4600 ms）で、workspace の増分は 0.0691 ms だった。過去 repo が現存しないため、これは実 repo の履歴値ではない。

実在ディレクトリを 1--6 件へ増やした `workspace_channels()` は、中央値が順に 0.0310、0.0430、0.0504、0.0617、0.0699、0.0867 ms だった。約 0.011 ms/channel で、6 件でも 0.1 ms 未満である。`.DS_Store` は有効チャンネルから除外された。loader の同一プロセス singleton cache 後はさらに小さいため、設定解決を主要因とは分類できない。

## 領域 3: canonical 制作フロー

### `/wf-new` と Suno-helper

DeepFocus の実セッション `0a961bb7-c9ce-4fc0-9eea-28cf43bb9a67e63d` で、planning 274.5 秒、preview 287.0 秒、scene phrases 60.0 秒、thumbnail 452.2 秒、textless 348.9 秒、Suno prompt 620.3 秒だった。別の実セッションでは planning 560.4 秒、thumbnail 774.7 秒、承認待ち 39、1,685、3,340 秒を記録した。Suno prompt の別実績は 326.8 秒であり、実測幅は 326.8--620.3 秒である。

Vertex 画像 CLI は成功時 14--19 秒、429 を含む再試行区間は最大 65 秒だった。Suno server ready からユーザーが ZIP 完了を報告するまでの browser automation、外部生成、polling、playlist、download の合計は、2 実セッションで 561--1,020 秒だった。extension 内部の段階別 timestamp がないため、これ以上は分割していない。12 ファイルの展開 mtime は 1 秒幅で、ローカル展開は支配項目ではない。

現行 6 チャンネルの制作 provider は Suno であり、同条件の Lyria CLI 実セッションは発見できなかった。したがって issue が指定する `lyria / suno-helper` の選択肢は、現行 canonical path で実行された Suno-helper を実測対象とした。履歴 artifact を Lyria の実行時間には読み替えていない。

### `masterup` と `/wf-next-local`

同じ `38fd...` セッションで `masterup` subagent は 400.6 秒だった。内訳は選曲 6 秒、cleanup plan 4 秒、12 曲の audio cleanup 140 秒、ラウドネス検査 88 秒、master 生成 67 秒、検証 2 秒である。親 orchestration が続けて同じ collection のラウドネスを 67 秒かけて再検査した。12 個の cleanup 成果物の mtime 幅 131 秒も tool の 140 秒と整合する。

次のローカル工程では video subagent 133.6 秒（うち ffmpeg 82 秒）、description subagent 281.2 秒だった。両者は並列起動され、単純合計約 414 秒に対して wall-clock 区間は約 321 秒だった。この比較は「長い処理はすべて直列」という仮説を反証し、既に並列化された箇所より、masterup 内の重複直列検査を優先すべき根拠になる。

### `/wf-next` upload と publish

upload preflight subagent は 137.8--188.0 秒、実 upload API 呼び出しは失敗を含め 7--15 秒、YouTube 確認は 2--5 秒だった。一方、OAuth token の削除・再発行を伴う実セッションの中断は 9,043 秒、別セッションの upload 承認待ちは 1,231 秒だった。前者は異常時の人間/認証待ちで、通常 upload latency とは合算しない。

現行 6 チャンネルはすべて `workflow.post_publish.configured == false` で、canonical `/publish` は子処理開始前に停止する。設定判定を含む cold process は direct 73.61 ms（69.08--83.86 ms）、uv 経由 87.35 ms（85.16--95.26 ms）だった。`community-post`、`pinned-comment`、`metadata-audit` の完走セッションは現行ログにない。006 の履歴には community 完了と翌日の pin 予定があるが runtime はないため、外部 API や人間待ちを推測値で補っていない。

### skill/reference 読み込みと plan 再評価

親セッションで skill 起動から最初の tool までの入口区間は `/wf-new` 約 26 秒、`/wf-next` 約 10 秒、Suno-helper 約 8 秒だった。これにはモデルによる SKILL/reference 解釈が含まれるため、純ファイル I/O とはみなさない。対象となった 3 本の canonical セッションには TaskUpdate / TaskCreate / TodoWrite がなく、明示的 plan 再評価は 0 回だった。ブラウザ障害の復旧セッションでは TaskUpdate 14 回、TaskCreate 8 回があり、これは正常系の固定費ではなく障害対応として分離した。

## 3 領域横断ランキング

実観測を時間降順に並べた。幅がある項目は最大実測を順位に使い、同一親子区間を二重加算していない。

| 順位 | 項目 | 実測 | 原因分類 |
| ---: | --- | ---: | --- |
| 1 | OAuth 復旧中断 | 9,043 s | 人間待ち / 外部 auth |
| 2 | `/wf-new` 承認待ち | 3,340 s | 人間待ち |
| 3 | `/wf-new` 承認待ち | 1,685 s | 人間待ち |
| 4 | upload 承認待ち | 1,231 s | 人間待ち |
| 5 | Suno browser 区間 | 561--1,020 s | 外部 API / polling / browser 直列 |
| 6 | thumbnail subagent | 452.2--774.7 s | AI / ローカル orchestration |
| 7 | Suno prompt subagent | 326.8--620.3 s | AI / 直列 review |
| 8 | planning subagent | 274.5--560.4 s | AI / ローカル orchestration |
| 9 | `masterup` subagent | 400.6 s | ローカル計算 / 直列実行 |
| 10 | description subagent | 281.2 s | AI / ファイル I/O |
| 11 | audio cleanup | 140 s | ローカル ffmpeg / 直列実行 |
| 12 | upload preflight | 137.8--188.0 s | ローカル検証 / OAuth |
| 13 | ラウドネス検査 1 回目 | 88 s | ローカル計算 / 直列実行 |
| 14 | video ffmpeg | 82 s | ローカル計算 |
| 15 | ラウドネス検査 2 回目 | 67 s | ローカル計算 / 重複直列 |
| 16 | progress hook 174 回の累積推計 | 9.24 s | 固定 overhead |
| 17 | preflight CLI | 0.597 s | 固定 overhead / ローカル検証 |
| 18 | cold config route | 0.00050--0.00053 s | 固定 overhead |

固定 overhead を削るだけでは上位の待ち時間に届かない。反証比較として、当初疑われた progress hook は 174 launch でも 9.24 秒で、Suno browser 区間の 1% 前後、最大の認証中断の約 0.1%だった。また video と description の実並列化は約 93 秒を隠蔽しており、直列実行の分類は工程ごとに確認する必要がある。

## 後続課題と計測上の制約

- 後続: [#3777 masterup のラウドネス検査を receipt 化し、同一 collection の二重走査をなくす](https://github.com/daiki-beppu/youtube-automation/issues/3777)
- #3301（review 粒度）と #3302（Suno context 肥大）は既に close 済みのため、同じ改善を再起票しなかった
- 外部 extension は内部 stage timestamp を残さないため、Suno は実セッションの境界幅である
- publish は現行設定で無効、Lyria は現行 provider でない。実行されなかった外部処理を fixture や推定で Done 扱いしていない
- 調査用 instrumentation、temporary script、flake 変更はリポジトリへ追加していない
