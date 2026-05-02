import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const runs = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/runs" }),
  schema: z.object({
    title: z.string(),
    date: z.string(),
    garmin_id: z.string().optional(),
    distance_km: z.number(),
    duration_seconds: z.number(),
    pace_per_km: z.string(),
    avg_hr: z.number().optional(),
    city: z.string().optional(),
    country: z.string().optional(),
    has_route: z.boolean().default(false),
    auto_generated: z.boolean().default(false),
    tags: z.array(z.string()).optional(),
  }),
});

const posts = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/posts" }),
  schema: z.object({
    title: z.string(),
    date: z.string(),
    description: z.string().optional(),
    tags: z.array(z.string()).optional(),
  }),
});

export const collections = { runs, posts };
