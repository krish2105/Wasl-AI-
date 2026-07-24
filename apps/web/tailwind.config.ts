import type { Config } from "tailwindcss";

// Phase 1 config only. The palette, type pairing and layout concept come out of
// the Phase 7 direction pass — deciding them here would be guessing before the
// design work happens.
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
