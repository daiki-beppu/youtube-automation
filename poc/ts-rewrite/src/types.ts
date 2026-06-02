export interface CheckResult {
  /** 依存ライブラリ名。サマリ表示・テスト識別に使う。 */
  name: string;
  /** 期待どおり動作したか。撤退判定ゲートの go/no-go の根拠。 */
  ok: boolean;
  /** 判定の根拠となった観測値（エラーコード・出力サイズ等）。 */
  detail: string;
}
