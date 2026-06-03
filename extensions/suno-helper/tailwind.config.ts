import type { Config } from "tailwindcss";

export default {
  content: ["./entrypoints/**/*.{html,tsx,ts}", "./components/**/*.{tsx,ts}"],
  theme: {
    extend: {},
  },
  plugins: [],
} satisfies Config;
