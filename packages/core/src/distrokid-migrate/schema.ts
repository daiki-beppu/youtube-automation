import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const CONFIG_DIRNAME = "config";
export const CHANNEL_DIRNAME = "channel";
export const DISTROKID_FILENAME = "distrokid.json";
export const DISTROKID_BACKUP_FILENAME = "distrokid.json.bak";

const DistrokidMigrateSnakeInputSchema = z
  .object({
    apply: z.boolean(),
    backup: z.boolean(),
    target: z.string().optional(),
  })
  .strict();

const DistrokidMigrateCamelInputSchema = z
  .object({
    apply: z.boolean(),
    backup: z.boolean(),
    target: z.string().optional(),
  })
  .strict();

export const DistrokidMigrateInputSchema = z
  .union([DistrokidMigrateSnakeInputSchema, DistrokidMigrateCamelInputSchema])
  .transform((input): { apply: boolean; backup: boolean; target?: string } =>
    snakeToCamel(input)
  );

export const DistrokidMigrateOutputSchema = z
  .object({
    applied: z.boolean(),
    backupPath: z.string().nullable(),
    path: z.string(),
    target: z.string(),
  })
  .strict();

export type DistrokidMigrateInput = z.infer<typeof DistrokidMigrateInputSchema>;
export type DistrokidMigrateOutput = z.infer<
  typeof DistrokidMigrateOutputSchema
>;
