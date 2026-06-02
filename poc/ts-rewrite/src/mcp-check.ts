import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import type { CheckResult } from "./types";

const CHECK_NAME = "mcp-sdk";

/**
 * MCP SDK の Server オブジェクトを生成できることを確認する。
 * import が解決し、コンストラクタが通れば bun で SDK が動く証拠になる。
 * 構築失敗時は例外を握りつぶさず ok:false として返し、run-smoke の撤退判定サマリを欠落させない。
 */
export async function checkMcp(): Promise<CheckResult> {
  try {
    new Server(
      { name: "ts-rewrite-poc", version: "0.0.0" },
      { capabilities: {} },
    );
    return {
      name: CHECK_NAME,
      ok: true,
      detail: "Server インスタンス生成: 成功",
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      name: CHECK_NAME,
      ok: false,
      detail: `Server インスタンス生成に失敗: ${message}`,
    };
  }
}
