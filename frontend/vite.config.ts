import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Local-first dev: forward same-origin /api calls to the backend so the
    // frontend never hardcodes a host or port.
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Provides afterEach globally so Testing Library auto-cleans renders
    // between tests. Test files still import describe/it/expect explicitly.
    globals: true,
  },
});
