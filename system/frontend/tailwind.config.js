/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        studio: {
          // Nesto Design System
          bg: "#FAF8F3", // Warm Ivory
          panel: "#FFFFFF", // Soft White surface
          panel2: "#F5F1E8", // Warm surface / timeline bed
          thinking: "#F3F7F7", // AI Thinking card
          border: "#E8E1D5",
          muted: "#667085",
          text: "#162B49", // Midnight Navy
          primary: "#162B49",
          accent: "#C8A96E", // Champagne Gold (CTA)
          accentHover: "#B99555",
          accent2: "#3A9D9A", // Aqua Teal (flow / success)
          process: "#3B7EA8", // Ocean Blue (AI running)
          hero: "#162B49",
          support: "#3B7EA8",
          transition: "#A89F8E",
          danger: "#C47A4A", // Soft amber warning
          video: "#111827",
        },
      },
      fontFamily: {
        sans: ["var(--font-manrope)", "Manrope", "system-ui", "sans-serif"],
        display: ["var(--font-fraunces)", "Fraunces", "Georgia", "serif"],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(22,43,73,0.04), 0 10px 28px rgba(22,43,73,0.06)",
      },
    },
  },
  plugins: [],
};
