// Build: 2026-06-27
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      scope: "/app/",
      base: "/app/",
      includeAssets: ["favicon.svg", "icons.svg"],
      manifest: {
        name: "CreditVoice — Business Desk",
        short_name: "CreditVoice",
        description: "Simple credit and inventory management for Nigerian businesses via WhatsApp and web",
        theme_color: "#863bff",
        background_color: "#0c1f4a",
        display: "standalone",
        scope: "/app/",
        start_url: "/app/home",
        orientation: "portrait",
        categories: ["business", "finance", "productivity"],
        lang: "en",
        icons: [
          {
            src: "favicon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any",
          },
          {
            src: "icons.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "maskable",
          },
          {
            src: "icons/pwa-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "icons/pwa-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
        shortcuts: [
          {
            name: "Record a Sale",
            short_name: "Record",
            description: "Quickly record a sale or payment",
            url: "/app/capture",
            icons: [{ src: "favicon.svg", sizes: "any" }],
          },
          {
            name: "POS Checkout",
            short_name: "POS",
            description: "Open the point-of-sale screen",
            url: "/app/pos",
            icons: [{ src: "favicon.svg", sizes: "any" }],
          },
          {
            name: "My Inventory",
            short_name: "Stock",
            description: "Check and manage your stock",
            url: "/app/inventory",
            icons: [{ src: "favicon.svg", sizes: "any" }],
          },
          {
            name: "Customers",
            short_name: "Customers",
            description: "View customer balances",
            url: "/app/customers",
            icons: [{ src: "favicon.svg", sizes: "any" }],
          },
        ],
      },
      workbox: {
        navigateFallback: "/app/index.html",
        navigateFallbackDenylist: [/^\/app\/api\//],
        globPatterns: ["**/*.{js,css,html,ico,png,svg,webp,woff2}"],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/app/api/"),
            handler: "NetworkFirst",
            options: {
              cacheName: "cv-api-cache",
              networkTimeoutSeconds: 5,
              expiration: {
                maxEntries: 150,
                maxAgeSeconds: 24 * 60 * 60,
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
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
