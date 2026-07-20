import { Switch } from "@youtube-automation/ui";

import type { CompletionSoundSettings } from "../lib/completion-sound";

interface CompletionSoundControlsProps {
  settings: CompletionSoundSettings;
  disabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

export function CompletionSoundControls({
  settings,
  disabled,
  onEnabledChange,
}: CompletionSoundControlsProps) {
  return (
    <section className="flex flex-col gap-1 text-sm" aria-label="通知設定">
      <label className="flex items-center gap-2">
        <Switch
          checked={settings.enabled}
          disabled={disabled}
          data-suno-control="notification-enabled"
          onCheckedChange={(checked) => onEnabledChange(checked === true)}
        />
        <span className="font-medium">通知</span>
      </label>
      <p className="text-xs text-muted-foreground">
        完了・エラー時に OS 通知と固定音で知らせる
      </p>
    </section>
  );
}
