import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy mirrors the nginx proxy used in the production
// container image, so `npm run dev` talks to the same backend paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/events": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/events/, ""),
      },
      "/api/ingest": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ingest/, ""),
      },
    },
  },
});
