import { z } from "zod";

export const ChannelInitInputSchema = z
  .object({
    context: z.string().default("TBD"),
    force: z.boolean().default(false),
    genre: z.string().default("TBD"),
    name: z.string(),
    short: z.string(),
    style: z.string().default("TBD"),
  })
  .strict();

const ActionKindSchema = z.union([
  z.literal("created"),
  z.literal("skipped"),
  z.literal("overwritten"),
]);

const FileActionSchema = z.object({
  kind: ActionKindSchema,
  rel: z.string(),
});

const DirectoryActionSchema = z.object({
  kind: ActionKindSchema,
  rel: z.string(),
});

export const ChannelInitOutputSchema = z.object({
  diff: z.string(),
  directories: z.array(DirectoryActionSchema),
  files: z.array(FileActionSchema),
  summary: z.string(),
});

export type ChannelInitInput = z.infer<typeof ChannelInitInputSchema>;
export type ChannelInitOutput = z.infer<typeof ChannelInitOutputSchema>;
