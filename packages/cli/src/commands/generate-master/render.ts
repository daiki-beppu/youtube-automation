import type { GenerateMasterOutput } from "@youtube-automation/core/generate-master";

const formatDuration = (seconds: number): string => {
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const rest = rounded % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
};

export const renderGenerateMasterText = (
  output: GenerateMasterOutput
): string => {
  const lines = [
    `Output: ${output.outputPath}`,
    `Input files: ${output.inputCount}`,
    `Segments: ${output.segmentCount}`,
    `Loop count: ${output.loopCount}`,
    `Crossfade: ${output.crossfadeDuration}`,
    `Bitrate: ${output.bitrate}`,
  ];
  const preview =
    output.durationPreview === undefined
      ? []
      : [
          "Duration preview",
          `  Track total : ${formatDuration(output.durationPreview.trackTotalSeconds)}`,
          `  Target      : ${
            output.durationPreview.targetSeconds === undefined
              ? "disabled"
              : formatDuration(output.durationPreview.targetSeconds)
          }`,
          `  Estimated   : ${formatDuration(output.durationPreview.estimatedSeconds)}`,
        ];
  return [...output.messages, ...preview, ...lines].join("\n");
};

export const renderGenerateMasterQuietText = (
  output: GenerateMasterOutput
): string => output.messages.join("\n");
