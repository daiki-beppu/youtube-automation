// CLI 高レベル OAuth ヘルパ（ADR-0003 §6）。MCP が実行してはならない orchestration
// （browser / local-server interactive flow）と、純粋な小片（SCOPES 定数 / token 期限
// 判定 / token.json パス）を所有する。
//
// getYouTubeClient() は env → secrets → token read →（refresh / interactive）→ token
// write 0o600 → buildYouTubeClient のフル dance。refresh / interactive の失敗は
// ServiceError を throw して呼び出し側（command 層）に委ねる。

import { join } from "node:path";

import { channelDir } from "@tayk/core/config";
import {
  buildYouTubeAnalyticsClient,
  buildYouTubeClient,
} from "@tayk/core/oauth/client";
import type {
  YouTubeAnalyticsClient,
  YouTubeClient,
} from "@tayk/core/oauth/client";
import { interactiveAuthService } from "@tayk/core/oauth/interactive";
import { refreshTokenService } from "@tayk/core/oauth/refresh";

import { resolveClientSecretsJson } from "./secrets.ts";
import { readTokenJson, writeTokenJson } from "./token.ts";

// YouTube Full Access + Analytics + Reporting スコープ（Python oauth_handler.py:69-74 と
// 一致）。yt-analytics-monetary.readonly は Reporting API v1 で thumbnail impressions /
// CTR を取得するため必須。
export const SCOPES: readonly string[] = [
  "https://www.googleapis.com/auth/youtube",
  "https://www.googleapis.com/auth/youtube.force-ssl",
  "https://www.googleapis.com/auth/yt-analytics.readonly",
  "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
];

/** token.json の絶対パス（<channelDir>/auth/token.json）。client_secrets.json と対称。 */
export const tokenJsonPath = (): string =>
  join(channelDir(), "auth", "token.json");

/** token.json の access token が期限切れか判定する（expiry_date なし or 過去なら expired）。 */
export const isExpired = (tokenJson: string): boolean => {
  const parsed = JSON.parse(tokenJson) as { expiry_date?: number };
  if (typeof parsed.expiry_date !== "number") {
    return true;
  }
  return parsed.expiry_date <= Date.now();
};

// getYouTubeClient が呼ぶ OAuth service の注入 seam。省略時は実 service を使う
// （refresh.ts の deps パターンと同形）。production は default を使い、テストだけが
// network を踏まない fake を差し込んで refresh / interactive の glue 分岐を網羅する。
export interface GetYouTubeClientDeps {
  interactive: typeof interactiveAuthService;
  refresh: typeof refreshTokenService;
}

const defaultDeps: GetYouTubeClientDeps = {
  interactive: interactiveAuthService,
  refresh: refreshTokenService,
};

// token が無ければ interactive 認証で取得して 0o600 で保存し、token.json 文字列を返す。
const obtainToken = async (
  path: string,
  clientSecretsJson: string,
  interactive: GetYouTubeClientDeps["interactive"]
): Promise<string> => {
  const stored = readTokenJson(path);
  if (stored !== null) {
    return stored;
  }
  const r = await interactive({ clientSecretsJson, scopes: [...SCOPES] });
  if (!r.ok) {
    throw r.error;
  }
  const { tokenJson } = r.value;
  writeTokenJson(path, tokenJson);
  return tokenJson;
};

// 期限切れなら refresh して 0o600 で書き戻す。有効ならそのまま返す。
const ensureFresh = async (
  path: string,
  clientSecretsJson: string,
  tokenJson: string,
  refresh: GetYouTubeClientDeps["refresh"]
): Promise<string> => {
  if (!isExpired(tokenJson)) {
    return tokenJson;
  }
  const r = await refresh({ clientSecretsJson, tokenJson });
  if (!r.ok) {
    throw r.error;
  }
  const { tokenJson: refreshed } = r.value;
  writeTokenJson(path, refreshed);
  return refreshed;
};

/**
 * 有効な token.json 文字列を解決して返す（OAuth dance 本体）。
 *
 * env → secrets で client_secrets を解決し、token.json を読む。token が無ければ
 * interactive 認証、期限切れなら refresh し、いずれも 0o600 で書き戻す。service の失敗は
 * `r.error`（ServiceError）を throw する。Data / Analytics 両クライアントはこの 1 回の
 * dance が返す同一 token から構築され、認証往復は 1 度に閉じる（#993）。
 */
export const resolveTokenJson = async (
  deps: GetYouTubeClientDeps = defaultDeps
): Promise<string> => {
  const clientSecretsJson = await resolveClientSecretsJson();
  const path = tokenJsonPath();
  const stored = await obtainToken(path, clientSecretsJson, deps.interactive);
  return ensureFresh(path, clientSecretsJson, stored, deps.refresh);
};

/** 構築済み YouTube Data API v3 クライアントを返す（token dance → client build）。 */
export const getYouTubeClient = async (
  deps: GetYouTubeClientDeps = defaultDeps
): Promise<YouTubeClient> => buildYouTubeClient(await resolveTokenJson(deps));

/** 構築済み YouTube Analytics API v2 クライアントを返す（Data 版と同一 dance を共有）。 */
export const getYouTubeAnalyticsClient = async (
  deps: GetYouTubeClientDeps = defaultDeps
): Promise<YouTubeAnalyticsClient> =>
  buildYouTubeAnalyticsClient(await resolveTokenJson(deps));
