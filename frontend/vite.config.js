import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend serves the production build from `frontend/dist`
// (see backend/app/api.py). In dev, `/api` is proxied to the running
// backend on :8000 so the frontend can call it without CORS friction.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
