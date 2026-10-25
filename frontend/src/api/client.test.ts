/** Клиент API: ошибки FastAPI должны приходить в UI читаемыми, а 401 — различаться по смыслу.
 *
 * Среда тестов — node: fetch подменяется здесь, новых зависимостей нет.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api, getToken, onSessionExpired, setToken } from '@/api/client';
import type { DealEstimateRequest } from '@/types/api';

type Stub = { status: number; body?: string; contentType?: string };

const estimate: DealEstimateRequest = {
  project_type: 'connectivity',
  scale: 'medium',
  works: [],
  equipment: [],
  software: [],
  urgency: 'normal',
  has_unique_solution: false,
};

/**
 * Подмена fetch: один вариант ответа или очередь по порядковому номеру вызова —
 * так проверяются методы, которые делают два запроса подряд (создание и скачивание DOCX).
 */
function stubFetch(stub: Stub | Stub[]): string[] {
  const queue = Array.isArray(stub) ? stub : null;
  const single: Stub = Array.isArray(stub) ? (stub[0] as Stub) : stub;
  const calls: string[] = [];
  let index = 0;

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    const { status, body = '', contentType = 'application/json' } = queue
      ? (queue[index] ?? (queue[queue.length - 1] as Stub))
      : single;
    index += 1;
    // У 204 по стандарту не может быть тела — Response на это жалуется сам.
    return new Response(status === 204 ? null : body, {
      status,
      headers: contentType ? { 'Content-Type': contentType } : {},
    });
  }) as unknown as typeof fetch;
  return calls;
}

function expectApiError(rejection: unknown, status: number, message: string): void {
  expect(rejection).toBeInstanceOf(ApiError);
  expect((rejection as ApiError).status).toBe(status);
  expect((rejection as ApiError).message).toBe(message);
}

async function rejectionFrom(promise: Promise<unknown>): Promise<unknown> {
  return promise.then(
    () => null,
    (exc: unknown) => exc,
  );
}

/** Токен теперь в памяти: между тестами не должен «протухать» через storage. */
beforeEach(() => {
  setToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('разбор ошибок FastAPI', () => {
  it('достаёт текст из detail вместо сырого JSON', async () => {
    stubFetch({ status: 404, body: JSON.stringify({ detail: 'Проект не найден' }) });
    expectApiError(await rejectionFrom(api.needs(999)), 404, 'Проект не найден');
  });

  it('разбирает 422 с массивом нарушений и убирает префикс body', async () => {
    stubFetch({
      status: 422,
      body: JSON.stringify({
        detail: [{ loc: ['body', 'project_type'], msg: 'field required', type: 'missing' }],
      }),
    });
    expectApiError(
      await rejectionFrom(api.estimateDeal({ ...estimate, project_type: '' })),
      422,
      'project_type: field required',
    );
  });

  it('склеивает несколько нарушений в одну строку', async () => {
    stubFetch({
      status: 422,
      body: JSON.stringify({
        detail: [
          { loc: ['body', 'project_type'], msg: 'field required' },
          { loc: ['body', 'scale'], msg: 'field required' },
        ],
      }),
    });
    expectApiError(
      await rejectionFrom(api.estimateDeal({ ...estimate, project_type: '', scale: '' })),
      422,
      'project_type: field required; scale: field required',
    );
  });

  it('не показывает HTML прокси: отдаёт подпись статуса', async () => {
    stubFetch({
      status: 502,
      body: '<html><body>502 Bad Gateway</body></html>',
      contentType: 'text/html',
    });
    expectApiError(await rejectionFrom(api.dashboard()), 502, 'Сервер недоступен');
  });

  it('на пустом теле отдаёт подпись статуса, а не пустую строку', async () => {
    stubFetch({ status: 500, body: '' });
    expectApiError(await rejectionFrom(api.dashboard()), 500, 'Сервер не справился с запросом');
  });

  it('для неизвестного статуса без тела показывает код ошибки', async () => {
    stubFetch({ status: 418, body: '' });
    expectApiError(await rejectionFrom(api.dashboard()), 418, 'Ошибка запроса (418)');
  });

  it('сохраняет текст ошибки, если тело не JSON и не HTML', async () => {
    stubFetch({ status: 400, body: 'region_id должен быть числом', contentType: 'text/plain' });
    expectApiError(
      await rejectionFrom(api.companies({ region_id: 1 })),
      400,
      'region_id должен быть числом',
    );
  });

  it('успешный ответ 204 не пытается читать JSON', async () => {
    stubFetch({ status: 204, contentType: undefined });
    await expect(api.dashboard()).resolves.toBeUndefined();
  });

  it('не роняет интерфейс не-JSON телом с кодом 200', async () => {
    stubFetch({ status: 200, body: '<html>cache gateway</html>', contentType: 'text/html' });
    expectApiError(
      await rejectionFrom(api.dashboard()),
      200,
      'Сервер вернул ответ неверного формата',
    );
  });
});

describe('401: проверочный запрос против защищённого маршрута', () => {
  it('на входе в систему оставляет пользователя на форме с текстом сервера', async () => {
    const notified = vi.fn();
    const unsubscribe = onSessionExpired(notified);
    stubFetch({ status: 401, body: JSON.stringify({ detail: 'Неверный логин или пароль' }) });

    expectApiError(
      await rejectionFrom(api.login('analyst', 'wrongpassword')),
      401,
      'Неверный логин или пароль',
    );
    expect(notified).not.toHaveBeenCalled();
    unsubscribe();
  });

  it('на защищённом маршруте гасит токен и сообщает причину', async () => {
    setToken('expired-token');
    const notified = vi.fn();
    const unsubscribe = onSessionExpired(notified);
    stubFetch({ status: 401, body: JSON.stringify({ detail: 'Could not validate credentials' }) });

    expectApiError(await rejectionFrom(api.dashboard()), 401, 'Срок сессии истёк: войдите заново');
    expect(getTokenValue()).toBeNull();
    expect(notified).toHaveBeenCalledWith('Срок сессии истёк: войдите заново');
    unsubscribe();
  });

  it('отписка от уведомления гасит подписку', async () => {
    const notified = vi.fn();
    onSessionExpired(notified)();
    setToken('expired-token');
    stubFetch({ status: 401, body: '' });

    await rejectionFrom(api.dashboard());
    expect(notified).not.toHaveBeenCalled();
  });
});

describe('контракты API', () => {
  it('скачивает CSV расчёта по маршруту калькулятора', async () => {
    const calls = stubFetch({
      status: 200,
      body: 'estimate_id;score',
      contentType: 'text/csv',
    });

    const blob = await api.estimateCsv(42);

    expect(calls).toEqual(['/api/v1/calculator/estimates/42/csv']);
    expect(await blob.text()).toBe('estimate_id;score');
  });

  it('запрашивает настройку 2FA по partial token', async () => {
    const calls = stubFetch({
      status: 200,
      body: JSON.stringify({ secret: 'test-secret', otpauth_hint: 'otpauth://totp/test' }),
    });

    await api.setup2fa('partial-token');

    expect(calls).toEqual(['/api/v1/auth/2fa/setup']);
  });
});

describe('refresh: 401 → /auth/refresh → повтор запроса (ТЗ 13)', () => {
  it('после успешного refresh сохраняет новый токен и повторяет запрос', async () => {
    setToken('old-token');
    const calls = stubFetch([
      { status: 401, body: JSON.stringify({ detail: 'expired' }) },
      { status: 200, body: JSON.stringify({ access_token: 'fresh-token' }) },
      { status: 200, body: '[]' },
    ]);
    const rows = await api.companies({});
    expect(rows).toEqual([]);
    expect(getTokenValue()).toBe('fresh-token');
    expect(calls).toEqual([
      '/api/v1/companies',
      '/api/v1/auth/refresh',
      '/api/v1/companies',
    ]);
  });

  it('параллельные 401 выполняют только один refresh', async () => {
    setToken('old-token');
    const calls = stubFetch([
      { status: 401, body: '{"detail":"expired"}' },
      { status: 401, body: '{"detail":"expired"}' },
      { status: 200, body: '{"access_token":"fresh-token"}' },
      { status: 200, body: '[]' },
      { status: 200, body: '{"companies": 1}' },
    ]);
    await Promise.all([api.companies({}), api.dashboard()]);
    expect(calls.filter((url) => url.includes('/auth/refresh'))).toHaveLength(1);
    expect(getTokenValue()).toBe('fresh-token');
  });

  it('неудачный refresh не зацикливается: токен гасится как раньше', async () => {
    setToken('old-token');
    stubFetch({ status: 401, body: '{"detail":"expired"}' });
    const reason = await rejectionFrom(api.dashboard()).then((exc) => (exc as Error).message);
    expect(reason).toBe('Срок сессии истёк: войдите заново');
    expect(getTokenValue()).toBeNull();
  });
});

function getTokenValue(): string | null {
  return getToken();
}

describe('запросы', () => {
  it('не отдаёт пустые фильтры в строку запроса', async () => {
    const calls = stubFetch({ status: 200, body: '[]' });
    await api.companies({ region_id: null, industry_id: null, client_status: null });
    expect(calls[0]).toMatch(/\/companies$/);
  });

  it('подставляет непустые фильтры и заголовок авторизации', async () => {
    setToken('token-42');
    const calls = stubFetch({ status: 200, body: '[]' });
    await api.companies({ region_id: 7 });

    expect(calls[0]).toContain('/companies?region_id=7');
    const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-42');
  });

  it('DOCX сначала создаёт документ, затем скачивает его', async () => {
    const calls = stubFetch([
      { status: 200, body: JSON.stringify({ file_ref: '/exports/kp-12.docx', status: 'created' }) },
      { status: 200, body: 'PK..docx-bytes', contentType: undefined },
    ]);
    const blob = await api.exportProposal(12);

    expect(calls[0]).toContain('/exports/proposal?estimate_id=12');
    expect(calls[1]).toContain('/exports/proposal/12/download');
    expect(await blob.text()).toBe('PK..docx-bytes');
  });

  it('экспорт CSV сообщает об ошибке тем же текстом', async () => {
    stubFetch({ status: 400, body: JSON.stringify({ detail: 'Неподдерживаемый модуль экспорта' }) });
    expectApiError(
      await rejectionFrom(api.exportCsv('unknown', {}, 'general')),
      400,
      'Неподдерживаемый модуль экспорта',
    );
  });
});
