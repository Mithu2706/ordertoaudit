import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; /api is proxied so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: {
    rollupOptions: {
      output: {
        // Vendor libraries in long-cached chunks. Recharts is left out on purpose: it is pulled
        // into the lazy dashboard/production chunks only, so other roles never download it.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
          ui: ["framer-motion", "lucide-react"],
        },
      },
    },
  },
});
