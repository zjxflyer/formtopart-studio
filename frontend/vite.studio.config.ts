import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', proxy: { '/api': process.env.VWC_API_TARGET || 'http://127.0.0.1:8766' } },
  build: {
    outDir: '../desktop-app/ui-dist',
    emptyOutDir: true,
    rollupOptions: { input: resolve(import.meta.dirname, 'studio.html') },
  },
});
