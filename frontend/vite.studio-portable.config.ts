import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    outDir: '../desktop-app/portable-dist', emptyOutDir: true,
    lib: {entry:'src/spatial/portable.ts',name:'VWCReadOnlyViewer',formats:['iife'],fileName:()=> 'portable.js'},
    minify: true, sourcemap: false,
  },
});
