import type { LayerOverride, LoudnormConfig } from "./schema.ts";

interface LoudnormMeasurements {
  readonly input_i: string;
  readonly input_lra: string;
  readonly input_thresh: string;
  readonly input_tp: string;
  readonly target_offset: string;
}

export interface BuildFinalizeFilterOptions {
  readonly applyLoudnorm: boolean;
  readonly fadeinCurve: string;
  readonly fadeinS: number;
  readonly layerCount: number;
  readonly layerOverrides: readonly (LayerOverride | null)[];
  readonly loudnorm: Pick<LoudnormConfig, "I" | "LRA" | "TP">;
  readonly measured: LoudnormMeasurements | null;
  readonly mixDuration: "first" | "shortest" | "longest";
  readonly mixNormalize: 0 | 1;
  readonly volumeDb: number;
}

const formatNumber = (value: number): string => value.toString();

const layerValues = (
  defaults: Pick<
    BuildFinalizeFilterOptions,
    "fadeinCurve" | "fadeinS" | "volumeDb"
  >,
  override: LayerOverride | null
): { fadeinCurve: string; fadeinS: number; volumeDb: number } => ({
  fadeinCurve: override?.fadeinCurve ?? defaults.fadeinCurve,
  fadeinS: override?.fadeinS ?? defaults.fadeinS,
  volumeDb: override?.volumeDb ?? defaults.volumeDb,
});

const buildLayerStage = (
  index: number,
  values: { fadeinCurve: string; fadeinS: number; volumeDb: number }
): string =>
  `[${index + 1}:a]aloop=loop=-1:size=2147483647` +
  `,volume=${formatNumber(values.volumeDb)}dB` +
  `,afade=t=in:st=0:d=${formatNumber(values.fadeinS)}:curve=${
    values.fadeinCurve
  }[r${index}]`;

const buildRainInputStage = (
  layerCount: number,
  mixNormalize: 0 | 1
): { rainInput: string; stage: string | null } => {
  if (layerCount === 1) {
    return { rainInput: "[r0]", stage: null };
  }
  const labels = Array.from(
    { length: layerCount },
    (_, index) => `[r${index}]`
  );
  return {
    rainInput: "[rainmix]",
    stage: `${labels.join("")}amix=inputs=${layerCount}:normalize=${mixNormalize}[rainmix]`,
  };
};

const buildLoudnormStage = (
  loudnorm: Pick<LoudnormConfig, "I" | "LRA" | "TP">,
  measured: LoudnormMeasurements | null
): string => {
  const target =
    `[mixed]loudnorm=I=${formatNumber(loudnorm.I)}` +
    `:LRA=${formatNumber(loudnorm.LRA)}:TP=${formatNumber(loudnorm.TP)}`;
  if (measured === null) {
    return `${target}:print_format=json[aout]`;
  }
  return (
    `${target}:measured_I=${measured.input_i}` +
    `:measured_LRA=${measured.input_lra}` +
    `:measured_TP=${measured.input_tp}` +
    `:measured_thresh=${measured.input_thresh}` +
    `:offset=${measured.target_offset}` +
    ":linear=true:print_format=summary[aout]"
  );
};

export const buildFinalizeFilter = (
  options: BuildFinalizeFilterOptions
): string => {
  if (options.layerOverrides.length !== options.layerCount) {
    throw new Error(
      `validation: layerOverrides length ${options.layerOverrides.length} does not match layerCount ${options.layerCount}`
    );
  }

  const layerStages = Array.from({ length: options.layerCount }, (_, index) =>
    buildLayerStage(
      index,
      layerValues(
        {
          fadeinCurve: options.fadeinCurve,
          fadeinS: options.fadeinS,
          volumeDb: options.volumeDb,
        },
        options.layerOverrides[index] ?? null
      )
    )
  );

  const rain = buildRainInputStage(options.layerCount, options.mixNormalize);
  const mixOut = options.applyLoudnorm ? "[mixed]" : "[aout]";
  const mixStage = `[0:a]${rain.rainInput}amix=inputs=2:duration=${options.mixDuration}:normalize=${options.mixNormalize}${mixOut}`;
  const loudnormStages = options.applyLoudnorm
    ? [buildLoudnormStage(options.loudnorm, options.measured)]
    : [];

  return [
    ...layerStages,
    ...(rain.stage === null ? [] : [rain.stage]),
    mixStage,
    ...loudnormStages,
  ].join(";");
};

const loudnormJsonBounds = (stderr: string): { end: number; start: number } => {
  const objectEnd = stderr.lastIndexOf("}");
  if (objectEnd !== -1) {
    const start = stderr.lastIndexOf("{", objectEnd);
    if (start === -1) {
      throw new Error(
        "validation: ffmpeg pass1 stderr is missing loudnorm JSON start"
      );
    }
    return { end: objectEnd, start };
  }

  const arrayEnd = stderr.lastIndexOf("]");
  if (arrayEnd === -1) {
    throw new Error("validation: ffmpeg pass1 stderr is missing loudnorm JSON");
  }

  const start = stderr.lastIndexOf("[", arrayEnd);
  if (start === -1) {
    throw new Error(
      "validation: ffmpeg pass1 stderr is missing loudnorm JSON start"
    );
  }
  return { end: arrayEnd, start };
};

export const parseLoudnormJson = (stderr: string): Record<string, string> => {
  const { end, start } = loudnormJsonBounds(stderr);
  let data: unknown;
  try {
    data = JSON.parse(stderr.slice(start, end + 1));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`validation: loudnorm JSON parse failed: ${message}`, {
      cause: error,
    });
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error("validation: loudnorm JSON payload must be an object");
  }
  return Object.fromEntries(
    Object.entries(data).map(([key, value]) => [key, String(value)])
  );
};
