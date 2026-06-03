import type { Config } from "tailwindcss";

export default {
  content: ["./entrypoints/**/*.{html,tsx}", "./components/**/*.tsx"],
  theme: { extend: {} },
  plugins: [],
} satisfies Config;
