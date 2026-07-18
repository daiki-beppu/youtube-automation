import { Button } from "@youtube-automation/ui";

import {
  COMPLETION_SOUND_PRESETS,
  type CompletionSoundPresetId,
  type CompletionSoundSettings,
} from "../lib/completion-sound";
import { Checkbox } from "./ui/checkbox";

const PRESET_IDS = Object.keys(
  COMPLETION_SOUND_PRESETS
) as CompletionSoundPresetId[];

interface CompletionSoundControlsProps {
  settings: CompletionSoundSettings;
  disabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onPresetChange: (preset: CompletionSoundPresetId) => void;
  onPreview: () => Promise<void>;
}

export function CompletionSoundControls({
  settings,
  disabled,
  onEnabledChange,
  onPresetChange,
  onPreview,
}: CompletionSoundControlsProps) {
  return (
    <section className="flex flex-col gap-1 text-sm" aria-label="完了音設定">
      <span className="font-medium">完了音</span>
      <label className="flex items-center gap-2">
        <Checkbox
          checked={settings.enabled}
          disabled={disabled}
          data-suno-control="completion-sound-enabled"
          onCheckedChange={(checked) => onEnabledChange(checked === true)}
        />
        <span>完了・エラー時に鳴らす</span>
      </label>
      <div
        role="group"
        aria-label="完了音の種類"
        className="flex flex-wrap gap-1"
      >
        {PRESET_IDS.map((presetId) => (
          <Button
            key={presetId}
            type="button"
            aria-pressed={settings.preset === presetId}
            variant={settings.preset === presetId ? "default" : "outline"}
            size="sm"
            disabled={disabled}
            data-suno-control="completion-sound-preset"
            data-suno-preset={presetId}
            onClick={() => onPresetChange(presetId)}
          >
            {COMPLETION_SOUND_PRESETS[presetId].label}
          </Button>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          data-suno-control="completion-sound-preview"
          onClick={() => void onPreview()}
        >
          試聴
        </Button>
      </div>
    </section>
  );
}
