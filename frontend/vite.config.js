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
    // React and the router rarely change: keep them in their own file so an
    // app update doesn't make every phone download them again. Pages are
    // split by App.jsx (lib/lazyPage.js) — each downloads when first opened.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules[\/](react|react-dom|react-router|react-router-dom|scheduler)[\/]/.test(id)) {
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    proxy: {
      "/app/api": "http://localhost:8000",
    },
  },
});
