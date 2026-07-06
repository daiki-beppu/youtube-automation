import process from "node:process";

import type { Result, ServiceError } from "@youtube-automation/core";

// ADR-0004 §4: Result→exit-code の CLI 側終端を 1 箇所に集約する共通 helper。
// 各 command が独自に exit code を決めない。
//   - ok:  stdout へ整形出力 (--json は service output をそのまま JSON.stringify)
//   - err: stderr へ `[domain] message`、exit code は quota=75 (EX_TEMPFAIL) / その他 1

const exitCodeForServiceError = (error: ServiceError): number =>
  error.domain === "quota" ? 75 : 1;

interface EmitResultDeps {
  exit: (code: number) => never;
  writeStderr: (message: string) => unknown;
  writeStdout: (message: string) => unknown;
}

export const createEmitResult =
  ({ exit, writeStderr, writeStdout }: EmitResultDeps) =>
  <T>(
    result: Result<T, ServiceError>,
    options: { json: boolean; renderText: (value: T) => string }
  ): void => {
    if (!result.ok) {
      writeStderr(`[${result.error.domain}] ${result.error.message}\n`);
      return exit(exitCodeForServiceError(result.error));
    }

    const rendered = options.json
      ? JSON.stringify(result.value)
      : options.renderText(result.value);
    if (rendered.length === 0) {
      return;
    }
    writeStdout(`${rendered}\n`);
  };

export const emitResult = createEmitResult({
  exit: process.exit,
  writeStderr: (message: string) => process.stderr.write(message),
  writeStdout: (message: string) => process.stdout.write(message),
});
