// Python `utils/exceptions.py` のドメイン例外を移植する受け皿。
// 本 issue (#735) では secret 解決が必要とする ConfigError のみを定義する。
// AutomationError 基底と他の派生 (YouTubeAPIError 等) は errors port (#734) で拡張する。

/** 設定不備・必須シークレット欠落など、構成解決の失敗を表すドメイン例外。 */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}
