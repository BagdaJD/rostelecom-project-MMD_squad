import { defineConfig, devices } from '@playwright/test';

/**
 * E2E демо-пути: dev-сервер с мок-слоем (VITE_USE_MOCKS=1) и одним origin.
 * Порт 5174 не пересекается с привычным 5173, где может работать ручной preview.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    // Установленный в окружении Chromium (rev 1148): обход недоступного headless-shell-1248.
    launchOptions: {
      executablePath: '/opt/doaid/ms-playwright/chromium-1148/chrome-linux/chrome',
      args: ['--no-sandbox'],
    },
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'npm run dev -- --port 5174 --strictPort',
    url: 'http://127.0.0.1:5174',
    reuseExistingServer: false,
    timeout: 60_000,
    env: { VITE_USE_MOCKS: '1' },
  },
});