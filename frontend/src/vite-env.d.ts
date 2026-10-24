/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Полный адрес API; без него берётся относительный /api/v1 (dev-прокси или nginx). */
  readonly VITE_API_URL?: string;
  /** Куда dev-прокси гоняет /api; по умолчанию http://localhost:8000 (vite.config.ts). */
  readonly VITE_API_PROXY_TARGET?: string;
  /** '1' — отдать запросы на моки вместо бэкенда (только dev). */
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_MAP_STYLE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
