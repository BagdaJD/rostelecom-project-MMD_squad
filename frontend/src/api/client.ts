/** Тонкий клиент API: единая обработка ошибок и токена.
 *
 * Access-токен живёт только в памяти (требование ТЗ 13: refresh — httpOnly-cookie,
 * токен не должен лежать в localStorage/sessionStorage). При старте приложение
 * пробует молча продлить сессию через /auth/refresh, иначе показывает вход.
 */

import type {
  Company,
  CompanyCard,
  DashboardSummary,
  DealEstimate,
  DealEstimateRequest,
  HeatCell,
  IndustryOption,
  InvestmentProject,
  Need,
  NotificationItem,
  PositionPrice,
  ProjectCard,
  RegionOption,
  TimelinePoint,
  WhiteSpace,
} from '@/types/api';

/**
 * Путь, а не абсолютный адрес: в dev его догоняет прокси из vite.config.ts, в проде —
 * location /api/ в nginx. Один origin отключает CORS и позволяет работать httpOnly-cookie.
 * Полный URL задаётся только если API живёт на другом домене (VITE_API_URL).
 */
const BASE_URL = import.meta.env.VITE_API_URL ?? '/api/v1';

/** Access-токен в памяти: не пишем его в storage (ТЗ 13 — refresh в httpOnly-cookie). */
let accessToken: string | null = null;

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
  return accessToken;
}

export function setToken(token: string | null): void {
  accessToken = token;
}

/** Подписка на «сессия истекла»: приложение само уходит на экран входа и показывает причину. */
type SessionExpiredListener = (reason: string) => void;

const sessionExpiredListeners = new Set<SessionExpiredListener>();

export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener);
  return () => {
    sessionExpiredListeners.delete(listener);
  };
}

function notifySessionExpired(reason: string): void {
  for (const listener of sessionExpiredListeners) listener(reason);
}

/** «Логин/2FA успешно завершены» — App должен перейти в Shell без перезагрузки. */
type AuthenticatedListener = () => void;
const authenticatedListeners = new Set<AuthenticatedListener>();

export function onAuthenticated(listener: AuthenticatedListener): () => void {
  authenticatedListeners.add(listener);
  return () => {
    authenticatedListeners.delete(listener);
  };
}

function notifyAuthenticated(): void {
  for (const listener of authenticatedListeners) listener();
}

const STATUS_TEXT: Record<number, string> = {
  400: 'Запрос содержит ошибку',
  403: 'Недостаточно прав для этого действия',
  404: 'Данные не найдены',
  409: 'Запись уже изменена, обновите страницу',
  422: 'Проверьте параметры запроса',
  429: 'Слишком много попыток, попробуйте позже',
  500: 'Сервер не справился с запросом',
  502: 'Сервер недоступен',
  503: 'Сервис временно недоступен',
};

const LOCATION_PREFIXES = new Set(['body', 'query', 'path', 'header', 'cookies']);

/** Нарушение валидации FastAPI: {"loc": ["body", "project_type"], "msg": "field required"}. */
function describeIssue(issue: unknown): string {
  if (typeof issue === 'string') return issue;
  if (!issue || typeof issue !== 'object') return '';
  const { loc, msg } = issue as { loc?: unknown; msg?: unknown };
  const parts = Array.isArray(loc) ? loc.map(String) : [];
  if (LOCATION_PREFIXES.has(parts[0] ?? '')) parts.shift();
  const field = parts.join('.');
  const text = typeof msg === 'string' ? msg : '';
  if (field && text) return `${field}: ${text}`;
  return field || text;
}

/**
 * FastAPI отвечает ошибкой телом JSON: detail строкой у HTTPException и массивом
 * нарушений у 422. Сырой JSON или HTML прокси в интерфейсе показывать нельзя:
 * оставляем одну читаемую строку, а если в теле ничего нет — подпись статуса.
 */
function readErrorMessage(status: number, body: string): string {
  const text = body.trim();
  if (!text) return STATUS_TEXT[status] ?? `Ошибка запроса (${status})`;

  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return text.startsWith('<') ? (STATUS_TEXT[status] ?? 'Сервис ответил некорректно') : text;
  }

  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const lines = detail.map(describeIssue).filter(Boolean);
    if (lines.length) return lines.join('; ');
  }
  return STATUS_TEXT[status] ?? `Ошибка запроса (${status})`;
}

/**
 * 401 на проверке учётных данных («неверный пароль») и 401 на защищённом маршруте
 * («сессия истекла») — разные случаи: второй гасит токен и уводит на экран входа.
 */
async function toApiError(response: Response, credentialCheck: boolean): Promise<ApiError> {
  const message = readErrorMessage(response.status, await response.text());
  if (response.status !== 401 || credentialCheck) return new ApiError(response.status, message);

  const reason = getToken()
    ? 'Срок сессии истёк: войдите заново'
    : 'Вход не выполнен: авторизуйтесь, чтобы продолжить';
  setToken(null);
  notifySessionExpired(reason);
  return new ApiError(401, reason);
}

type RequestOptions = RequestInit & {
  /** true для /auth/login и /auth/2fa/verify: их 401 — это неверные данные, а не протухшая сессия. */
  credentialCheck?: boolean;
  /** Внутренний флаг: один повтор после успешного /auth/refresh (ТЗ 13). */
  retried?: boolean;
};

/**
 * Молчаливое продление сессии: 401/нет сессии не должно показывать «сессия истекла»
 * на старте приложения (httpOnly-cookie читается автоматически).
 */
async function refreshSession(): Promise<boolean> {
  try {
    const response = await fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return false;
    const payload = (await response.json()) as { access_token?: string | null };
    if (!payload.access_token) return false;
    setToken(payload.access_token);
    return true;
  } catch {
    return false;
  }
}

/** Один одновременный refresh на несколько параллельных 401 (ТЗ 13). */
let refreshPromise: Promise<boolean> | null = null;

function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshSession().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { credentialCheck = false, retried = false, ...fetchInit } = init;
  const headers = new Headers(fetchInit.headers);
  headers.set('Accept', 'application/json');
  if (fetchInit.body) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${BASE_URL}${path}`, { ...fetchInit, headers });

  if (!response.ok) {
    // 401 на защищённом маршруте: пробуем продлить сессию и повторить запрос один раз.
    if (response.status === 401 && !credentialCheck && !retried && (await tryRefresh())) {
      return request<T>(path, { ...init, retried: true });
    }
    throw await toApiError(response, credentialCheck);
  }
  if (response.status === 204) return undefined as T;

  // Прокси или каптив-портал может вернуть 200 с HTML: JSON.parse упал бы SyntaxError в UI.
  const text = await response.text();
  if (!text.trim()) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, 'Сервер вернул ответ неверного формата');
  }
}

/** Тот же разбор ошибок, но ответ — файл (CSV, DOCX), а не JSON. */
async function requestBlob(path: string, init: RequestOptions = {}): Promise<Blob> {
  const { credentialCheck = false, retried = false, ...fetchInit } = init;
  const headers = new Headers(fetchInit.headers);
  if (fetchInit.body) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${BASE_URL}${path}`, { ...fetchInit, headers });
  if (!response.ok) {
    if (response.status === 401 && !credentialCheck && !retried && (await tryRefresh())) {
      return requestBlob(path, { ...init, retried: true });
    }
    throw await toApiError(response, credentialCheck);
  }
  return response.blob();
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
      { method: 'POST', body: JSON.stringify({ login, password }), credentialCheck: true },
    ).then((result) => {
      if (result.access_token) {
        setToken(result.access_token);
        notifyAuthenticated();
      }
      return result;
    }),

  verify2fa: (partial_token: string, code: string) =>
    request<{ access_token: string; refresh_token: string }>('/auth/2fa/verify', {
      method: 'POST',
      body: JSON.stringify({ partial_token, code }),
      credentialCheck: true,
    }).then((tokens) => {
      setToken(tokens.access_token);
      notifyAuthenticated();
      return tokens;
    }),

  me: () => request<{ id: number; login: string; role: string; mfa_enabled: boolean }>('/auth/me'),

  /** Продление сессии: access из тела, refresh читает httpOnly-cookie (ТЗ 13). */
  refresh: async () => {
    const ok = await tryRefresh();
    // Тихий вызов: без токена возвращаем null (App решит, показывать ли вход).
    if (!ok) return { access_token: null, refresh_token: null };
    return { access_token: getToken(), refresh_token: null };
  },

  /** Выход с отзывом refresh-сессии на сервере; локальный токен чистит App. */
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST', credentialCheck: true }),

  dashboard: () => request<DashboardSummary>('/dashboard/summary'),

  companies: (filters: {
    region_id?: number | null;
    industry_id?: number | null;
    client_status?: string | null;
    min_revenue?: number | null;
    limit?: number;
  }) => request<Company[]>(`/companies${query({ ...filters })}`),

  companyCard: (id: number) => request<CompanyCard>(`/companies/${id}`),

  projectCard: (id: number) => request<ProjectCard>(`/investments/${id}`),

  positions: () => request<PositionPrice[]>('/positions/prices'),

  regions: () => request<RegionOption[]>('/regions'),

  industries: () => request<IndustryOption[]>('/industries'),

  notifications: () => request<NotificationItem[]>('/notifications'),

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
  exportCsv: (module: string, filters: Record<string, unknown>, mode: 'general' | 'crm') =>
    requestBlob('/exports/csv', {
      method: 'POST',
      body: JSON.stringify({ module, filters, mode }),
    }),

  /** DOCX КП: сначала создаём документ, затем скачиваем его как файл. */
  exportProposal: async (estimateId: number) => {
    // estimate_id — query-параметр (так его читает FastAPI-хэндлер без тела запроса).
    await request<{ file_ref: string; status: string }>(`/exports/proposal?estimate_id=${estimateId}`, {
      method: 'POST',
    });
    return requestBlob(`/exports/proposal/${estimateId}/download`);
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
