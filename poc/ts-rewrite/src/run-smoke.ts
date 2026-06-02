import { checkGoogleapis } from "./googleapis-check";
import { checkMcp } from "./mcp-check";
import { checkSharp } from "./sharp-check";
import type { CheckResult } from "./types";

async function main(): Promise<void> {
  const results: CheckResult[] = [
    await checkGoogleapis(),
    await checkSharp(),
    await checkMcp(),
  ];

  for (const result of results) {
    console.log(`${result.ok ? "PASS" : "FAIL"} ${result.name}: ${result.detail}`);
  }

  const allOk = results.every((result) => result.ok);
  console.log(`\nPoC verdict: ${allOk ? "GO (継続)" : "NO-GO (撤退検討)"}`);
  if (!allOk) {
    process.exit(1);
  }
}

await main();
