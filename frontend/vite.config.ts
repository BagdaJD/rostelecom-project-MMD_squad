/// <reference types="vitest" />
import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  // В dev API догоняется прокси, поэтому адрес бэкенда живёт здесь, а не в коде клиента.
  const apiTarget = env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000';

  return {
    plugins: [react()],
    resolve: {
      // Алиас @/ должен совпадать с paths в tsconfig, иначе сборка падает на импортах.
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: 5173,
      host: true,
      // Фронт и API на одном origin: CORS не нужен, а httpOnly-cookie из ТЗ 13 начнёт
      // доходить до клиента (через CORS куки не работают). В проде то же самое делает
      // location /api/ в infra/nginx/default.conf.
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.{ts,tsx}'],
      setupFiles: ['./src/test/setup.ts'],
      // Нагрузка на CPU: параллельные форки экономичнее воркеров для строковых замен.
      pool: 'forks',
    },
    build: { outDir: 'dist', sourcemap: false },
  };
});
