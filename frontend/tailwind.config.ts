import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#07080d",
        panel: "#0f1119",
        violet: "#8b5cf6",
      },
      boxShadow: {
        glow: "0 0 80px rgba(139, 92, 246, 0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
