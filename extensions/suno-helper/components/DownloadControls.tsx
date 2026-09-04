import { Switch } from "@youtube-automation/ui";

interface DownloadControlsProps {
  enabled: boolean;
  disabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

export function DownloadControls({
  enabled,
  disabled,
  onEnabledChange,
}: DownloadControlsProps) {
  return (
    <section
      className="flex flex-col gap-1 text-sm"
      aria-label="ダウンロード設定"
    >
      <label className="flex items-center gap-2">
        <Switch
          checked={enabled}
          disabled={disabled}
          data-suno-control="download-enabled"
          onCheckedChange={(checked) => onEnabledChange(checked === true)}
        />
        <span className="font-medium">ダウンロードまで実行する</span>
      </label>
      <p className="text-xs text-muted-foreground">Suno Studio・Premier 必須</p>
    </section>
  );
}
