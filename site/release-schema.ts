import { z } from "zod";

export const releaseFrontmatter = {
  version: z.string().min(1),
  released_at: z.coerce.date(),
  kind: z.enum(["main", "extension"]),
  summary: z.string().min(1),
};
