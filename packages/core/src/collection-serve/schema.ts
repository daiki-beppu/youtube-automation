import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

const DEFAULT_COLLECTION_SERVE_PORT = 7873;

const CollectionServeSnakeInputSchema = z
  .object({
    allow_origin: z.string().optional(),
    distrokid_source: z.string().optional(),
    distrokid_state_root: z.string().optional(),
    path: z.string(),
    playlist_capture_prefix: z.string().optional(),
    playlist_capture_root: z.string().optional(),
    port: z.number().int().positive().prefault(DEFAULT_COLLECTION_SERVE_PORT),
  })
  .strict();

const CollectionServeCamelInputSchema = z
  .object({
    allowOrigin: z.string().optional(),
    distrokidSource: z.string().optional(),
    distrokidStateRoot: z.string().optional(),
    path: z.string(),
    playlistCapturePrefix: z.string().optional(),
    playlistCaptureRoot: z.string().optional(),
    port: z.number().int().positive().prefault(DEFAULT_COLLECTION_SERVE_PORT),
  })
  .strict();

type CollectionServeCamelInput = z.output<
  typeof CollectionServeCamelInputSchema
>;

const validatePlaylistCapturePair = (
  input: CollectionServeCamelInput,
  context: z.RefinementCtx
): void => {
  const hasRoot = input.playlistCaptureRoot !== undefined;
  const hasPrefix = input.playlistCapturePrefix !== undefined;
  if (hasRoot !== hasPrefix) {
    context.addIssue({
      code: "custom",
      message:
        "playlist_capture_root and playlist_capture_prefix must be provided together",
      path: ["playlistCaptureRoot"],
    });
  }
};

export const CollectionServeInputSchema = z
  .union([CollectionServeSnakeInputSchema, CollectionServeCamelInputSchema])
  .transform(
    (input): CollectionServeCamelInput =>
      CollectionServeCamelInputSchema.parse(snakeToCamel(input))
  )
  .superRefine(validatePlaylistCapturePair);

export const CollectionServeOutputSchema = z
  .object({
    distrokidEnabled: z.boolean(),
    mode: z.enum(["dir", "single"]),
    playlistCaptureEnabled: z.boolean(),
    routes: z.array(z.string()),
    url: z.string(),
  })
  .strict();

export type CollectionServeInput = z.infer<typeof CollectionServeInputSchema>;
export type CollectionServeOutput = z.infer<typeof CollectionServeOutputSchema>;
