import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import {defineConfig} from "vite";

export default defineConfig({
  root: "site",
  base: "./",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../docs",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 8900,
  },
  preview: {
    host: "127.0.0.1",
    port: 8900,
  },
});
