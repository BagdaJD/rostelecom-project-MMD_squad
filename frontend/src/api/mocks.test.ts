/** Мок-слой: он заменяет бэкенд в разработке, поэтому должен вести себя как контракт.
 *
 * Проверяем то, на чём обычно расходятся мок и API: коды ответов, форма ошибки,
 * пустые выборки, файловые ответы и включение только по явному флагу.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { installMocks } from '@/api/mocks';
import type { Company, HeatCell, ProjectCard, WhiteSpace } from '@/types/api';

const realFetch = globalThis.fetch;

/** Минимальный sessionStorage: мок хранит в нём выбранный сценарий между загрузками. */
const storage = new Map<string, string>();

function enableMocks(query: string): void {
  vi.stubGlobal('location', { search: query });
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  storage.clear();
  globalThis.fetch = realFetch;
}

async function call(path: string, init?: RequestInit): Promise<Response> {
  return globalThis.fetch(`http://mock.local/api/v1${path}`, init);
}

afterEach(() => {
  vi.unstubAllGlobals();
  globalThis.fetch = realFetch;
});

describe('включение мока', () => {
  it('без флага не подменяет fetch', () => {
    enableMocks('');
    const before = globalThis.fetch;
    expect(installMocks()).toBeNull();
    expect(globalThis.fetch).toBe(before);
  });

  it('включается параметром ?mock и сообщает сценарий', () => {
    enableMocks('?mock=1');
    expect(installMocks()).toBe('data');
  });

  it('переживает переход после входа: ?mock теряется, а мок обязан остаться', () => {
    enableMocks('?mock=1&scenario=empty');
    expect(installMocks()).toBe('empty');

    // Вход делает window.location.assign('/') — адрес приходит без параметров.
    vi.stubGlobal('location', { search: '' });
    expect(installMocks()).toBe('empty');
  });

  it('?mock=0 выключает мок и забывает сценарий', () => {
    enableMocks('?mock=1');
    installMocks();

    vi.stubGlobal('location', { search: '?mock=0' });
    expect(installMocks()).toBeNull();
    expect(storage.size).toBe(0);
  });

  it('неизвестный сценарий сводится к данным, а не к падению', () => {
    enableMocks('?mock=1&scenario=whatever');
    expect(installMocks()).toBe('data');
  });
});

describe('сценарий data', () => {
  it('отдаёт тепловую карту и фильтрует по региону', async () => {
    enableMocks('?mock=1');
    installMocks();

    const all = (await (await call('/radar/heatmap')).json()) as HeatCell[];
    const onlyTyumen = (await (await call('/radar/heatmap?region_id=3')).json()) as HeatCell[];

    expect(all.length).toBeGreaterThan(1);
    expect(onlyTyumen).toHaveLength(1);
    expect(onlyTyumen[0]?.region_name).toBe('Тюменская область');
  });

  it('белое пятно объясняется метриками, а не цветом', async () => {
    enableMocks('?mock=1');
    installMocks();

    const spaces = (await (await call('/radar/white-spaces')).json()) as WhiteSpace[];
    expect(spaces[0]?.explanation.length).toBeGreaterThanOrEqual(3);
    expect(spaces[0]?.potential_score).toBeGreaterThan(spaces[0]?.presence_score ?? 0);
  });

  it('карточка компании содержит временной ряд с пропуском (null, не 0)', async () => {
    enableMocks('?mock=1');
    installMocks();

    const card = await (await call('/companies/102')).json();
    const profit = card.metrics.find((m: { metric_code: string }) => m.metric_code === 'profit');
    expect(profit.value).toBeNull();
    expect(card.provenance[0].source).toBeTruthy();
  });

  it('карточка проекта отдаёт окно контакта и связанные закупки', async () => {
    enableMocks('?mock=1');
    installMocks();

    const card = (await (await call('/investments/201')).json()) as ProjectCard;
    expect(card.contact_window).toBe('6–12 мес. до старта');
    expect(card.tenders[0]?.deadline_date).toBe('2026-10-20');
  });

  it('список компаний фильтруется по региону', async () => {
    enableMocks('?mock=1');
    installMocks();

    const rows = (await (await call('/companies?region_id=3')).json()) as Company[];
    expect(rows).toHaveLength(1);
    expect(rows[0]?.client_status).toBe('prospect');
  });

  it('CSV начинается с BOM и содержит идентификаторы (ТЗ 12)', async () => {
    enableMocks('?mock=1');
    installMocks();

    const response = await call('/exports/csv', { method: 'POST', body: '{}' });
    // text() по спеке отбрасывает BOM при декодировании, поэтому смотрим байты: именно
    // они уйдут в скачанный файл, и именно их проверяет Excel/табличный редактор.
    const bytes = new Uint8Array(await response.arrayBuffer());
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);

    const text = await new Response(bytes.slice(3)).text();
    expect(text.split('\r\n')[0]).toContain('ИНН');
    expect(text.split('\r\n')[1]).toContain('7700000016');
  });

  it('DOCX создаётся первым запросом и скачивается вторым', async () => {
    enableMocks('?mock=1');
    installMocks();

    const created = await (await call('/exports/proposal?estimate_id=1', { method: 'POST' })).json();
    const file = await call('/exports/proposal/1/download');

    expect(created.status).toBe('created');
    expect(file.headers.get('Content-Type')).toContain('wordprocessingml');
  });

  it('неизвестный маршрут отвечает 404 с detail, а не пустотой', async () => {
    enableMocks('?mock=1');
    installMocks();

    const response = await call('/audit');
    expect(response.status).toBe(404);
    expect((await response.json()).detail).toContain('/audit');
  });
});

describe('сценарии состояний', () => {
  it('empty отдаёт пустые выборки: экран пустых данных проверяем без бэкенда', async () => {
    enableMocks('?mock=1&scenario=empty');
    installMocks();

    expect(await (await call('/radar/white-spaces')).json()).toEqual([]);
    expect((await (await call('/dashboard/summary')).json()).companies).toBe(0);
  });

  it('error отдаёт 500 с текстом в detail: экран ошибки проверяем без бэкенда', async () => {
    enableMocks('?mock=1&scenario=error');
    installMocks();

    const response = await call('/companies');
    expect(response.status).toBe(500);
    expect((await response.json()).detail).toBeTruthy();
  });
});
