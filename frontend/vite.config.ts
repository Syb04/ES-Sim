import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 開発時は固定ポートを要求する (src-tauri/tauri.conf.json の devUrl と一致させる)
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
});
