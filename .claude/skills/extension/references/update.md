# Update

最新 release と対象の解決は `references/install.md` と同じ契約を使う。`--update` は manifest の比較結果にかかわらず指定対象だけを更新し、省略時は 3 拡張全件を対象とする。

asset を取得して一時ディレクトリへ展開し、manifest の name / version を検証する。検証後、既存 `~/chrome-extensions/<name>/` を timestamp 付き backup へ移し、一時ディレクトリを正規位置へ移す。失敗時は backup を戻せる状態を維持し、中途半端な正規 directory を完了扱いにしない。

更新後の manifest version が release version と一致することを確認し、user に `chrome://extensions` の対象拡張で reload を行うよう案内する。popup / overlay の動作確認後、不要になった backup の削除は対象を提示して別途承認を得る。
