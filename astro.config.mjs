// @ts-check
import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://therunstreak.run",
  base: "/therunstreak",
  integrations: [mdx(), sitemap()],
  output: "static",
});
