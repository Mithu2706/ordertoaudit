/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 50: "#F2F4F7", 100: "#E3E7ED", 200: "#C5CDD8", 400: "#5B6B82", 600: "#2C3E57", 700: "#22324A", 800: "#1B2A41", 900: "#131E2F" },
        terracotta: { 50: "#FBF1EC", 100: "#F5DDD1", 500: "#C2643A", 600: "#B4532A", 700: "#924222" },
        amber: { 50: "#FFF8EB", 100: "#FDECC8", 600: "#B7791F", 700: "#975A16" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(19,30,47,0.06), 0 1px 3px rgba(19,30,47,0.04)" },
    },
  },
  plugins: [],
};
