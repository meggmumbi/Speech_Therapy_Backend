import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the console talks to the backend through this proxy, so
// no CORS is involved and the same relative paths work in production when
// the backend serves the built console itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
