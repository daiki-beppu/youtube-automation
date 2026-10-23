import { Switch } from "@youtube-automation/ui";

interface PlaylistControlsProps {
  enabled: boolean;
  disabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

export function PlaylistControls({
  enabled,
  disabled,
  onEnabledChange,
}: PlaylistControlsProps) {
  return (
    <section
      className="flex flex-col gap-1 text-sm"
      aria-label="プレイリスト設定"
    >
      <label className="flex items-center gap-2">
        <Switch
          checked={enabled}
          disabled={disabled}
          data-suno-control="playlist-enabled"
          onCheckedChange={(checked) => onEnabledChange(checked === true)}
        />
        <span className="font-medium">プレイリストに追加する</span>
      </label>
      <p className="text-xs text-muted-foreground">
        OFF は生成完了で終了し、ダウンロードも行いません
      </p>
    </section>
  );
}
