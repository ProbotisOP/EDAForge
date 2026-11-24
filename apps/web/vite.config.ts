import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Python server (python -m edaforge.server) serves the built app and the API on one port.
// During development, Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ["echarts"],
          xyflow: ["@xyflow/react"],
          motion: ["motion", "cmdk", "@radix-ui/react-dialog", "@radix-ui/react-tooltip"],
        },
      },
    },
  },
});
