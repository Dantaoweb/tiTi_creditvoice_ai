import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// vite-plugin-pwa disabled: workbox-build has a broken es-abstract dependency
// (Cannot find module 'es-abstract/2024/Call') that causes every build to fail.
// Re-enable once vite-plugin-pwa releases a fix.

export default defineConfig({
  plugins: [
    react(),
  ],
  base: "/app/",
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/app/api": "http://localhost:8000",
    },
  },
});
