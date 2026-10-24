/// <reference types="vitest" />
import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Алиас @/ должен совпадать с paths в tsconfig, иначе сборка падает на импортах.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
  server: { port: 5173, host: true },
  build: { outDir: 'dist', sourcemap: false },
});
