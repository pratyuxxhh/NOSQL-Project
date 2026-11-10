import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // listen on 0.0.0.0 so the dev server is reachable from outside Docker
    port: 5173,
  },
  build: {
    chunkSizeWarningLimit: 1500, // cytoscape + recharts; fine for an internal dashboard
  },
  test: {
    environment: "jsdom",
    globals: true, // lets Testing Library clean up the DOM after each test
    setupFiles: ["./src/test/setup.ts"],
  },
});
