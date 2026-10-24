/** Тонкий клиент API: единая обработка ошибок и токена.
 *
 * Токен хранится в памяти + sessionStorage; refresh-поток и 2FA — в features/auth.
 */

import type {
  Company,
  DashboardSummary,
  DealEstimate,
  DealEstimateRequest,
  HeatCell,
  InvestmentProject,
  Need,
  TimelinePoint,
  WhiteSpace,
} from '@/types/api';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';
const TOKEN_KEY = 'rtk.access';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (response.status === 401) {
    setToken(null);
    throw new ApiError(401, 'Требуется повторный вход');
  }
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text || response.statusText);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    search.set(key, String(value));
  }
  const result = search.toString();
  return result ? `?${result}` : '';
}

export const api = {
  login: (login: string, password: string) =>
    request<{ mfa_required: boolean; partial_token: string | null; access_token: string | null }>(
      '/auth/login',
      { method: 'POST', body: JSON.stringify({ login, password }) },
    ),

  verify2fa: (partial_token: string, code: string) =>
    request<{ access_token: string; refresh_token: string }>('/auth/2fa/verify', {
      method: 'POST',
      body: JSON.stringify({ partial_token, code }),
    }),

  me: () => request<{ id: number; login: string; role: string; mfa_enabled: boolean }>('/auth/me'),

  dashboard: () => request<DashboardSummary>('/dashboard/summary'),

  companies: (filters: {
    region_id?: number | null;
    industry_id?: number | null;
    client_status?: string | null;
    min_revenue?: number | null;
    limit?: number;
  }) => request<Company[]>(`/companies${query({ ...filters })}`),

  heatmap: (filters: { region_id?: number | null; industry_group?: string | null }) =>
    request<HeatCell[]>(`/radar/heatmap${query({ ...filters })}`),

  whiteSpaces: (filters: { region_id?: number | null; industry_group?: string | null }) =>
    request<WhiteSpace[]>(`/radar/white-spaces${query({ ...filters })}`),

  projects: (filters: { stage?: string | null; region_id?: number | null; industry_id?: number | null }) =>
    request<InvestmentProject[]>(`/investments${query({ ...filters })}`),

  timeline: (filters: { region_id?: number | null; period?: string }) =>
    request<TimelinePoint[]>(`/investments/timeline${query({ ...filters })}`),

  needs: (projectId: number) => request<Need[]>(`/investments/${projectId}/needs`),

  estimateDeal: (payload: DealEstimateRequest) =>
    request<DealEstimate>('/deals/estimate', { method: 'POST', body: JSON.stringify(payload) }),

  subscriptions: () =>
    request<{ id: number; module: string; filters: Record<string, unknown>; is_active: boolean }[]>(
      '/subscriptions',
    ),

  createSubscription: (module: string, filters: Record<string, unknown>) =>
    request<{ id: number }>('/subscriptions', {
      method: 'POST',
      body: JSON.stringify({ module, filters, notify_frequency: 'daily' }),
    }),

  /** CSV отдаётся файлом: возвращаем Blob и сохраняем через ссылку. */
  exportCsv: async (module: string, filters: Record<string, unknown>, mode: 'general' | 'crm') => {
    const token = getToken();
    const response = await fetch(`${BASE_URL}/exports/csv`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ module, filters, mode }),
    });
    if (!response.ok) throw new ApiError(response.status, await response.text());
    return response.blob();
  },
  /** DOCX КП: сначала создаём документ, затем скачиваем его как файл. */
  exportProposal: async (estimateId: number) => {
    // estimate_id — query-параметр (так его читает FastAPI-хэндлер без тела запроса).
    await request<{ file_ref: string; status: string }>(`/exports/proposal?estimate_id=${estimateId}`, {
      method: 'POST',
    });
    const token = getToken();
    const response = await fetch(`${BASE_URL}/exports/proposal/${estimateId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new ApiError(response.status, await response.text());
    return response.blob();
  },
};

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
