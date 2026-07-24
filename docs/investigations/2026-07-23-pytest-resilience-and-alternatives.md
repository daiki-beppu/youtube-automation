# pytest の耐障害化と代替ランナー調査

調査日: 2026-07-23

## 結論

本リポジトリでは pytest を継続し、テスト単位とプロセス全体の二層で
タイムアウトを設けるのが妥当である。`unittest` への全面移行は、CPython の
終了時 GC、子プロセスの孤児化、外部 watchdog 不在を解決しない。

今回の事象では、Python 3.14.6 / pytest 9.1.1 の古いテストプロセスが
インタプリタ終了時 GC に滞留し、14.1 GB と 23.7 GB の physical footprint を
保持した。一方、原因となった SRT 境界失敗の修正後は関連 27 tests が
6.35 秒で完走した。

## 推奨する恒久対策

1. pytest 9 の `faulthandler_timeout` と
   `faulthandler_exit_on_timeout = true` を設定する。これは fixture の
   setup/teardown を含むテスト単位の時間超過でスタックを出力し、プロセスを
   終了できる。ただし pytest セッション終了後の CPython finalization は
   対象外なので、外側 watchdog も必要である。
   [pytest reference](https://docs.pytest.org/en/stable/reference/reference.html#confval-faulthandler_exit_on_timeout)
2. GitHub Actions の test job に `timeout-minutes` を設定する。GitHub Actions
   は job 単位の最大実行時間を公式に提供している。
   [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes)
3. Takt/Codex の pytest コマンドにも wall-clock timeout を設け、超過時は
   pytest だけでなく同じ process group を回収する。pytest 内部の仕組みだけでは、
   interpreter finalization や孤児化した子プロセスを保証して回収できない。
4. CI の `pytest -n auto` は worker 数を明示的に制限する。xdist の `auto` は
   物理 CPU コア数を利用するため、各 worker が重いモジュールを import する
   suite ではメモリ使用量が増幅する。
   [pytest-xdist distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
5. domain 一括 import、サーバー起動、subprocess を扱うテストを専用 lane に分離する。
   pytest 公式も、グローバル状態や cleanup 不備が並列実行時の不安定性を招くと
   説明している。
   [pytest flaky tests](https://docs.pytest.org/en/stable/explanation/flaky.html)

## 代替候補

| 候補 | 評価 |
|---|---|
| `unittest` | 標準ライブラリで最有力の代替。ただし fixture、`monkeypatch`、`tmp_path`、parametrize、markers、xdist の置換コストが大きく、同じ CPython プロセス上で動くため今回の GC 問題は直接解決しない。[Python unittest](https://docs.python.org/3/library/unittest.html) |
| nose2 | unittest ベースで並列実行やプラグインを持つが、pytest から移るメリットが小さい。[nose2 plugins](https://docs.nose2.io/en/latest/plugins.html) |
| Robot Framework | acceptance testing / ATDD / BDD / RPA 向け。Python unit test 274ファイルの代替には不向き。[Robot Framework User Guide](https://robotframework.org/robotframework/latest/RobotFrameworkUserGuide) |
| Hypothesis | property-based testingの補助ライブラリであり、ランナーの代替ではない。[Hypothesis docs](https://hypothesis.readthedocs.io/en/latest/) |
| doctest | ドキュメント例の検証には使えるが、fixtureや統合テストの全面代替にはならない。[Python doctest](https://docs.python.org/3/library/doctest.html) |

pytest は unittest 形式のテストも収集できるため、将来 portability を高めたい箇所だけ
`unittest.TestCase` へ段階移行し、当面は pytest で両方を実行できる。
[pytest unittest support](https://docs.pytest.org/en/stable/how-to/unittest.html)

## リポジトリ固有の移行コスト

- test files: 274
- pytest を直接 import するファイル: 198
- `@pytest.fixture`: 108 箇所
- `@pytest.mark.parametrize`: 260 箇所
- `pytest.raises`: 788 箇所

したがって全面移行より、pytest の耐障害化と重いテストのプロセス境界分離を先に行う。
