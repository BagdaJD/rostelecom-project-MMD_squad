/** API калькулятора (/calculator/*): свой тонкий клиент, общий src/api/client.ts не меняется.
 *
 * Токен и класс ошибки — общие (getToken, ApiError). В мок-режиме приложения (?mock=1,
 * см. src/api/mocks.ts) ответы берутся из ./fixtures — настоящих ответов API, снятых с
 * бэкенда, — чтобы экран калькулятора проверялся без поднятого сервера.
 */

import { ApiError, getToken, setToken } from '@/api/client';

import catalogFixture from './fixtures/catalog.json';
import draftFixture from './fixtures/draft.json';
import estimateFixture from './fixtures/estimate.json';
import type { DealCatalog, DealDraft, DealEstimate, DealEstimateRequest } from './types';

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api/v1';
const MOCK_KEY = 'rtk.mock';

function mockScenario(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(MOCK_KEY) ?? null;
  } catch {
    return null;
  }
}

/** Ответ мока: те же задержка и ошибка, что у общего мок-слоя. */
async function mock<T>(value: T): Promise<T> {
  if (mockScenario() === 'error') {
    throw new ApiError(500, 'Сервер недоступен в демонстрационном режиме');
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
  return structuredClone(value);
}

async function errorFrom(response: Response): Promise<ApiError> {
  let message = response.statusText || `Ошибка запроса (${response.status})`;
  try {
    const detail = (JSON.parse(await response.text()) as { detail?: unknown }).detail;
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail)) message = 'Проверьте параметры расчёта';
  } catch {
    // тело не JSON — оставляем статус
  }
  if (response.status === 401) {
    // Сессия истекла: как и общий клиент — токен гасим, приложение вернёт на экран входа.
    setToken(null);
    globalThis.location?.reload();
  }
  return new ApiError(response.status, message);
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${BASE_URL}/calculator${path}`, { ...init, headers });
  if (!response.ok) throw await errorFrom(response);
  return response;
}

const json = async <T>(path: string, init?: RequestInit): Promise<T> =>
  (await (await call(path, init)).json()) as T;

export type ExportKind = 'kp' | 'kp-internal' | 'csv' | 'crm' | 'analogs';

export const calculatorApi = {
  catalog: (): Promise<DealCatalog> =>
    mockScenario() ? mock(catalogFixture as unknown as DealCatalog) : json('/catalog'),

  estimate: (payload: DealEstimateRequest): Promise<DealEstimate> =>
    mockScenario()
      ? mock(estimateFixture as unknown as DealEstimate)
      : json('/estimate', { method: 'POST', body: JSON.stringify(payload) }),

  /** Черновик из инвестпроекта навигатора: /calculator?project=ID. */
  draft: (projectId: number): Promise<DealDraft> =>
    mockScenario()
      ? mock({
          ...(draftFixture as unknown as DealDraft),
          request: { ...(draftFixture as unknown as DealDraft).request, investment_project_id: projectId },
        })
      : json(`/draft/${projectId}`),

  approve: (estimateId: number, price: number) =>
    mockScenario()
      ? mock({ estimate_id: estimateId, approved_price: String(price), approved_at: new Date().toISOString() })
      : json<{ estimate_id: number; approved_price: string; approved_at: string }>(
          `/estimates/${estimateId}/approve`,
          { method: 'POST', body: JSON.stringify({ price }) },
        ),

  /** Файл выгрузки: КП в Word или CSV. */
  download: async (estimateId: number, kind: ExportKind): Promise<{ blob: Blob; filename: string }> => {
    const isKp = kind === 'kp' || kind === 'kp-internal';
    const csvKind = kind === 'analogs' ? 'comparables' : kind === 'crm' ? 'crm' : 'deals';
    const filename = isKp
      ? `KP-${estimateId}${kind === 'kp-internal' ? '-internal' : ''}.docx`
      : `calculator-${csvKind}-${estimateId}.csv`;
    if (mockScenario()) {
      const body = isKp ? 'PK\u0003\u0004demo-docx' : '﻿Демо-режим;без сервера\r\n';
      return mock({ blob: new Blob([body]), filename });
    }
    const path = isKp
      ? `/estimates/${estimateId}/proposal?variant=${kind === 'kp' ? 'client' : 'internal'}`
      : `/estimates/${estimateId}/csv?kind=${csvKind}`;
    return { blob: await (await call(path)).blob(), filename };
  },
};

/** Сохранить файл: «двоичный» тип — браузер скачивает, а не открывает CSV вместо страницы. */
export function saveFile(blob: Blob, filename: string): void {
  const file = new Blob([blob], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
