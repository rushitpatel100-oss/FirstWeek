import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base "./" so the built site works from any folder, such as a GitHub Pages project page.
export default defineConfig({ base: "./", plugins: [react()] });
