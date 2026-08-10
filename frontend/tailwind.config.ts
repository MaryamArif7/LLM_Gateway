import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: "#12151C",
        panelraised: "#171B24",
        border: "#262B36",
        ink: "#E8E9ED",
        muted: "#8A90A2",
        route: "#FF8A3D",
        cache: "#4DD8C0",
        openai: "#74AA9C",
        anthropic: "#D97757",
        gemini: "#5B8DEF",
        danger: "#E5484D",
      },
      fontFamily: {
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
        sans: ["'Inter'", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
