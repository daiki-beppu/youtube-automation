// googleapis クライアントの pure factory（ADR-0003 §7）。
//
// token.json 文字列を受け取り、I/O・ネットワーク往復なしで構築済みの googleapis
// クライアントを返す。purity が要件: 仮の credentials でも構築自体は成功する（認証
// は構築時に走らない）。token.json は Node google-auth-library の Credentials シェイプ
// （access_token / refresh_token / expiry_date）で永続化される前提。JSON.parse は不正
// 文字列で throw し、空 credentials のクライアントを黙って作らない（fail fast）。各
// domain service はここで構築したクライアントを deps で受け取る。

import type { Credentials } from "google-auth-library";
import { google } from "googleapis";
import type { youtube_v3, youtubeAnalytics_v2 } from "googleapis";

/** YouTube Data API v3 クライアントの型（cli / mcp が googleapis を直 import せず参照する別名）。 */
export type YouTubeClient = youtube_v3.Youtube;
/** YouTube Analytics API v2 クライアントの型。 */
export type YouTubeAnalyticsClient = youtubeAnalytics_v2.Youtubeanalytics;

type GoogleApisOAuth2Client = InstanceType<typeof google.auth.OAuth2>;

const authFromTokenJson = (tokenJson: string): GoogleApisOAuth2Client => {
  const credentials = JSON.parse(tokenJson) as Credentials;
  const auth = new google.auth.OAuth2();
  auth.setCredentials(credentials);
  return auth;
};

/** token.json から YouTube Data API v3 クライアントを構築する（呼び出しごとに新規）。 */
export const buildYouTubeClient = (tokenJson: string): YouTubeClient =>
  google.youtube({ auth: authFromTokenJson(tokenJson), version: "v3" });

/** token.json から YouTube Analytics API v2 クライアントを構築する（呼び出しごとに新規）。 */
export const buildYouTubeAnalyticsClient = (
  tokenJson: string
): YouTubeAnalyticsClient =>
  google.youtubeAnalytics({
    auth: authFromTokenJson(tokenJson),
    version: "v2",
  });
