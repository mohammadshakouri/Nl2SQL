import { defineConfig } from "vite";

export default defineConfig({
    // plugins: [viteSingleFile()],
    root: "src",
    base: "",
    publicDir: "public",

    build: {
        // outDir: "../dist",
        outDir: "../../../../vanilla/vanilla-is/ECity/AIAssistant/assets",
        target: "esnext",
        rollupOptions: {
            output: {
                // entryFileNames: "assets/[name].js",
                // chunkFileNames: "assets/[name].js",
                entryFileNames: "chatbot.js",
                chunkFileNames: "chatbot.js",
                assetFileNames: "chatbot.[ext]",
            },
        },
    },
});
