import { defineConfig } from "vite";

// base "./" so the built site works from any static host path
export default defineConfig({
  base: "./",
  build: { target: "es2022", chunkSizeWarningLimit: 800 },
});
