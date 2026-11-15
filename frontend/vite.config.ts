import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// A static site: data lives in public/data (written by `python tasks.py data export`) and the
// scoring runs in the browser. `base: "./"` keeps every URL relative, so the same build works
// at a domain root and under a project path such as GitHub Pages' /field-shift/.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { port: 5180, strictPort: true },
  build: { chunkSizeWarningLimit: 1600 },
});
