import { Alert, Button } from "@youtube-automation/ui";

import { EXTENSION_RELOAD_REQUIRED_MESSAGE } from "./runner-errors";

export function ReloadRequiredNotice() {
  return (
    <Alert
      variant="warning"
      className="fixed left-4 top-4 z-[2147483647] flex max-w-xs flex-col gap-2 border-warning-border bg-warning-background text-xs text-warning-foreground shadow-xl"
      data-suno-control="reload-required"
    >
      <p>{EXTENSION_RELOAD_REQUIRED_MESSAGE}</p>
      <Button
        type="button"
        onClick={() => window.location.reload()}
        variant="outline"
        size="sm"
        data-suno-control="reload-tab"
        className="self-start border-warning-border bg-warning-background text-warning-foreground hover:bg-warning-background/80 hover:text-warning-foreground"
      >
        タブを再読み込み
      </Button>
    </Alert>
  );
}
