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
    // Target older browsers so esbuild keeps classic `max-width` media queries
    // (not the `(width<=…)` range syntax, which needs Safari 16.4+). Many of our
    // users are on older iPhones (iOS 15) and budget Androids. Lowering the
    // target only makes output more compatible; it never breaks newer browsers.
    target: ["chrome87", "edge88", "firefox78", "safari14"],
    outDir: "../web/dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/app/api": "http://localhost:8000",
    },
  },
});
