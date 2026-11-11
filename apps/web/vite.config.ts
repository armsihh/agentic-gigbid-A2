import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the API runs on :8000; /api is proxied so cookies stay same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://localhost:8000", changeOrigin: false } },
  },
});
