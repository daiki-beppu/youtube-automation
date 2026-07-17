import { Alert, AlertDescription } from "@/components/ui/alert";
import type { Phase } from "@/lib/messaging";
import { PHASES } from "@/lib/messaging";

export interface StatusBannerProps {
  phase: Phase | null;
  message: string;
}

// フェーズごとの Tailwind 配色。状態の正規化のため PHASES を SSOT に分岐する。
const PHASE_STYLE: Record<Phase, string> = {
  [PHASES.INJECTING]: "bg-blue-50 text-blue-800 border-blue-200",
  [PHASES.DONE]: "bg-green-50 text-green-800 border-green-200",
  [PHASES.ERROR]: "bg-red-50 text-red-800 border-red-200",
  [PHASES.STOPPED]: "bg-yellow-50 text-yellow-800 border-yellow-200",
};

// content からの進捗 / エラーを表示するバナー。
export function StatusBanner({ phase, message }: StatusBannerProps) {
  if (phase === null) {
    return null;
  }
  return (
    <Alert
      variant={phase === PHASES.ERROR ? "destructive" : "default"}
      role={phase === PHASES.ERROR ? "alert" : "status"}
      className={`px-3 py-2 ${PHASE_STYLE[phase]}`}
    >
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
