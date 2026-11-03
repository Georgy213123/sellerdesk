/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8101";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5101,
    strictPort: true,
    proxy: { "/api": apiTarget },
  },
  preview: { port: 5101, strictPort: true, proxy: { "/api": apiTarget } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
