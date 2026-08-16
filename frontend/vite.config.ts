import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        // Server-rendered pages outside the SPA — never fall back to index.html.
        // The /ordering-platform entry is a prefix match, so it also covers
        // /ordering-platform/pack (Order Pack). Don't tighten it to an exact match.
        navigateFallbackDenylist: [/^\/ordering-platform/, /^\/autobot/, /^\/sterling/, /^\/api\//, /^\/docs/],
      },
      manifest: {
        name: "Carter Kitchen and Bath",
        short_name: "Carter K&B",
        description: "Kitchen & Bath job management — Carter Lumber",
        theme_color: "#125952",
        background_color: "#ffffff",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      // Frontend calls same-origin /api/*; Vite forwards to FastAPI.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
