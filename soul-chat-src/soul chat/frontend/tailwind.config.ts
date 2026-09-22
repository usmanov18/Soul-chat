import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070b16",
          900: "#0b1220",
          800: "#111a2e",
          700: "#1a2740",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        glass: "0 8px 32px rgba(2, 6, 23, 0.45)",
      },
      backgroundImage: {
        aurora:
          "radial-gradient(1200px 600px at 10% -10%, rgba(99,102,241,.35), transparent 60%)," +
          "radial-gradient(900px 500px at 100% 0%, rgba(236,72,153,.25), transparent 55%)," +
          "linear-gradient(160deg,#070b16,#0b1220 55%,#0a1020)",
      },
    },
  },
  plugins: [],
};

export default config;