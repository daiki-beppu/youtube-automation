// 責務別に分割されたチャンネル設定 API（Python `utils/config/__init__.py` の移植）。
//
// 公開 API:
//   loadConfig() -> ChannelConfig   シングルトン取得（初回に glob ロード）
//   channelDir() -> string          config/channel/ を含むプロジェクトルート解決
//   reset() -> void                 シングルトン state をリセット（テスト用）
//   ChannelConfig                   合成ルート型
//   + content / branding ヘルパー（Python dataclass メソッドの純関数移植）

export {
  activityForTheme,
  hashtagLine,
  renderOpening,
  sceneForTheme,
  tagsDefault,
  tagsForCollection,
} from "./content.ts";
export { channelDir, loadConfig, reset } from "./loader.ts";
export { brandingAsApiDict } from "./meta.ts";

export type { ChannelConfig } from "./config.ts";
