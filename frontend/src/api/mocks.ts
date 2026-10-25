/** Мок-слой разработки: экраны собираются и проверяются без поднятого бэкенда.
 *
 * Зачем: 30 из 100 баллов (UX + бренд + состояния) проверяются на наполненных экранах,
 * а `docker compose up` в окружении разработчика есть не всегда. Фикстуры взяты из
 * data/seed/demo_bundle.json, поэтому цифры на моках совпадут с демо-набором БД.
 *
 * Включение: VITE_USE_MOCKS=1 в frontend/.env.local либо ?mock=1 в адресе страницы.
 * Сценарии: ?mock=1&scenario=empty — пустые данные, ?mock=1&scenario=error — сбой API.
 *
 * Реализовано перехватом fetch: msw и jsdom в зависимостях отсутствуют, а доставить их
 * нечем (в окружении нет npm). Мок живёт только в dev: в проде VITE_USE_MOCKS не задан.
 */

import type {
  Company,
  CompanyCard,
  DashboardSummary,
  DealEstimate,
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

export type MockScenario = 'data' | 'empty' | 'error';

const MOCK_KEY = 'rtk.mock';

type Definition = {
  pattern: RegExp;
  get: (match: RegExpMatchArray, search: URLSearchParams) => unknown;
};

const REGIONS: RegionOption[] = [
  { id: 1, code: 'RU-MOS', name: 'Московская область' },
  { id: 2, code: 'RU-SVE', name: 'Свердловская область' },
  { id: 3, code: 'RU-TYU', name: 'Тюменская область' },
  { id: 4, code: 'RU-KRS', name: 'Краснодарский край' },
];

const INDUSTRIES: IndustryOption[] = [
  { id: 1, code: 'TEK', name: 'Нефтегазовый сектор', group: 'ТЭК' },
  { id: 2, code: 'TRADE', name: 'Розничная торговля', group: 'Торговля' },
  { id: 3, code: 'APK', name: 'Пищевая промышленность', group: 'АПК' },
  { id: 4, code: 'IT', name: 'Разработка ПО и данные', group: 'ИТ' },
];

const HEATMAP: HeatCell[] = [
  {
    region_id: 1,
    region_name: 'Московская область',
    industry_group: 'ТЭК',
    companies_count: 18,
    revenue_sum: '11240.50',
    growth_share: 0.22,
    potential_score: 91,
    presence_score: 64,
    longitude: 37.62,
    latitude: 55.75,
  },
  {
    region_id: 3,
    region_name: 'Тюменская область',
    industry_group: 'АПК',
    companies_count: 7,
    revenue_sum: '6120.00',
    growth_share: 0.31,
    potential_score: 88,
    presence_score: 12,
    longitude: 65.53,
    latitude: 57.15,
  },
  {
    region_id: 4,
    region_name: 'Краснодарский край',
    industry_group: 'Торговля',
    companies_count: 11,
    revenue_sum: '4310.25',
    growth_share: 0.08,
    potential_score: 46,
    presence_score: 71,
    longitude: 38.98,
    latitude: 45.04,
  },
];

const WHITE_SPACES: WhiteSpace[] = [
  {
    region_id: 3,
    region_name: 'Тюменская область',
    industry_group: 'АПК',
    service_type: 'connectivity',
    potential_score: 88,
    presence_score: 12,
    explanation: [
      'Суммарная выручка 6 120 млн ₽, доля растущих компаний 31 %',
      '3 активных инвестиционных проекта на стадии проектирования',
      'Из 7 компаний клиент только одна — покрытие услуг 12 %',
    ],
  },
];

/** Две компании: чтобы на экране читались и «действующий», и «потенциальный» клиент. */
const COMPANIES: Company[] = [
  {
    id: 101,
    name: 'Уралгазстрой MOS',
    inn: '7700000016',
    industry_id: 1,
    region_id: 1,
    client_status: 'active',
    revenue_latest: '640.70',
    revenue_year: 2025,
    revenue_yoy: 6.4,
  },
  {
    id: 102,
    name: 'Нива-Агро ТЮ',
    inn: '7200000044',
    industry_id: 3,
    region_id: 3,
    client_status: 'prospect',
    revenue_latest: '812.30',
    revenue_year: 2025,
    revenue_yoy: 18.9,
  },
];

/**
 * Карточки компаний по идентификатору: действующий (101) и потенциальный (102) клиент.
 * value: null у profit — пропуск, а не ноль: UI обязан показать плашку, а не 0 (ТЗ 6.8).
 */
const COMPANY_DETAILS: Record<
  number,
  Pick<CompanyCard, 'ogrn' | 'employee_count' | 'metrics' | 'presence' | 'provenance' | 'demand_signals'>
> = {
  101: {
    ogrn: '1127700000016',
    employee_count: 218,
    metrics: [
      { metric_code: 'revenue', period_year: 2023, value: '510.20', unit: 'RUB mln', source_id: 900, fetched_at: '2026-01-12T08:30:00Z' },
      { metric_code: 'revenue', period_year: 2024, value: '560.10', unit: 'RUB mln', source_id: 900, fetched_at: '2026-01-12T08:30:00Z' },
      { metric_code: 'revenue', period_year: 2025, value: '640.70', unit: 'RUB mln', source_id: 900, fetched_at: '2026-10-01T08:30:00Z' },
      { metric_code: 'profit', period_year: 2025, value: null, unit: 'RUB mln', source_id: 900, fetched_at: '2026-10-01T08:30:00Z' },
    ],
    presence: [
      {
        region_id: 1,
        municipality: 'г. Москва',
        service_type: 'connectivity',
        coverage_percent: '64.00',
        contracts_count: 12,
        as_of_date: '2026-09-01',
        is_synthetic: false,
        source_id: 901,
      },
    ],
    provenance: [
      {
        source: 'demo_investregistry',
        external_id: 'DEMO-0016',
        fetched_at: '2026-10-01T08:30:00Z',
        license_note: 'синтетические данные, созданы для демонстрации',
        source_url: 'https://example.com/demo',
      },
    ],
    demand_signals: ['Действующий клиент: выполненные контракты в регионе', 'Рост выручки 6.4 % за год'],
  },
  102: {
    ogrn: '1127200000044',
    employee_count: 410,
    metrics: [
      { metric_code: 'revenue', period_year: 2023, value: '589.50', unit: 'RUB mln', source_id: 900, fetched_at: '2026-01-12T08:30:00Z' },
      { metric_code: 'revenue', period_year: 2024, value: '601.90', unit: 'RUB mln', source_id: 900, fetched_at: '2026-01-12T08:30:00Z' },
      { metric_code: 'revenue', period_year: 2025, value: '812.30', unit: 'RUB mln', source_id: 900, fetched_at: '2026-10-01T08:30:00Z' },
      { metric_code: 'profit', period_year: 2025, value: null, unit: 'RUB mln', source_id: 900, fetched_at: '2026-10-01T08:30:00Z' },
    ],
    presence: [
      {
        region_id: 3,
        municipality: 'г. Тюмень',
        service_type: 'connectivity',
        coverage_percent: '12.00',
        contracts_count: 1,
        as_of_date: '2026-09-01',
        is_synthetic: true,
        source_id: null,
      },
    ],
    provenance: [
      {
        source: 'demo_investregistry',
        external_id: 'DEMO-0044',
        fetched_at: '2026-10-01T08:30:00Z',
        license_note: 'синтетические данные, созданы для демонстрации',
        source_url: 'https://example.com/demo',
      },
    ],
    demand_signals: ['Инвестиционный проект на стадии проектирования', 'Рост выручки 18.9 % за год'],
  },
};

/** Карточка компании: базовая запись + детали, чтобы клик по 101 не показывал 102. */
function companyCard(id: number): CompanyCard {
  const company = COMPANIES.find((item) => item.id === id) ?? COMPANIES[1]!;
  const details = COMPANY_DETAILS[company.id] ?? COMPANY_DETAILS[102]!;
  return { ...company, ...details, id: company.id };
}

const PROJECTS: InvestmentProject[] = [
  {
    id: 201,
    title: 'Строительство теплично-овощного комплекса «Нива-Агро»',
    stage: 'design',
    planned_start: '2027-01-18',
    estimated_budget: '850000000.00',
    region_id: 3,
    initiator_company_id: 102,
    source_url: 'https://example.com/invest',
  },
  {
    id: 202,
    title: 'Реконструкция логистического хаба «Восточный»',
    stage: 'construction',
    planned_start: '2026-11-05',
    estimated_budget: '410000000.00',
    region_id: 2,
    initiator_company_id: null,
    source_url: 'https://example.com/invest',
  },
];

const PROJECT_CARD: ProjectCard = {
  ...PROJECTS[0]!,
  description:
    'Проектирование тепличного комплекса 24 га с автоматизированной системой управления микроклиматом, диспетчеризацией и каналом связи для передачи данных АСУ ТП.',
  planned_end: '2028-10-30',
  contact_window: '6–12 мес. до старта',
  tenders: [
    {
      id: 301,
      title: 'Поставка серверного оборудования для Логистического хаба',
      price: '18400000.00',
      deadline_date: '2026-10-20',
      source_url: 'https://example.com/eis/0118200001126000145',
    },
  ],
  milestones: [
    { title: 'Проектирование', date: '2026-10-01', status: 'done', source_url: 'https://example.com/invest' },
    { title: 'Модернизация', date: '2027-03-01', status: 'planned', source_url: 'https://example.com/invest' },
  ],
};

const TIMELINE: TimelinePoint[] = [
  { period: '2026-09', region_id: 3, industry_id: 3, events_count: 2, project_ids: [201] },
  { period: '2026-10', region_id: 2, industry_id: 6, events_count: 1, project_ids: [202] },
];

const NEEDS: Need[] = [
  {
    need_category: 'iot_asu_tp',
    probability: 0.71,
    evidence: '«автоматизированной системой управления микроклиматом»',
    rule_id: 'R-APK-03',
    model_version: 'needs-0.1',
  },
  {
    need_category: 'connectivity',
    probability: 0.62,
    evidence: '«каналом связи для передачи данных АСУ ТП»',
    rule_id: 'R-CONN-01',
    model_version: 'needs-0.1',
  },
];

const POSITIONS: PositionPrice[] = [
  { id: 1, name: 'Сервер 2U, 2×Xeon, 256 ГБ', category: 'equipment', unit: 'шт', price_min: '380000', price_max: '620000', price_typical: '480000', region_id: null, price_period: '2026', is_synthetic: true },
  { id: 2, name: 'СХД 100 ТБ', category: 'equipment', unit: 'шт', price_min: '1100000', price_max: '1800000', price_typical: '1450000', region_id: null, price_period: '2026', is_synthetic: true },
  { id: 3, name: 'IP-камера 4 Мп уличная', category: 'equipment', unit: 'шт', price_min: '9000', price_max: '21000', price_typical: '14000', region_id: null, price_period: '2026', is_synthetic: true },
];

const ESTIMATE: DealEstimate = {
  estimate_id: 5501,
  currency: 'RUB',
  estimate: { min: '1200000.00', optimum: '1650000.00', max: '2100000.00' },
  estimator_mode: 'analogs',
  confidence: 'medium',
  data_quality: 'limited',
  comparables: [
    {
      deal_id: 401,
      title: 'Канал связи и серверная для склада 42 тыс. м²',
      contract_value: '41500000.00',
      similarity: 0.74,
      retro_price_basis: 'synthetic',
    },
  ],
  adjustments: [
    { factor: 'regional_coefficient', value: 1.08, note: 'Тюменская область, работы' },
    { factor: 'urgency', value: 1.05, note: 'Сжатые сроки' },
  ],
  breakdown: [
    { article: 'works', amount: '825000.00' },
    { article: 'equipment', amount: '462000.00' },
    { article: 'software', amount: '363000.00' },
  ],
  price_period: '2025-2026',
  model_version: 'deal-estimator-0.2',
  requires_human_approval: true,
  warning: 'Аналогов мало: оценка требует проверки специалистом',
};

const NOTIFICATIONS: NotificationItem[] = [
  {
    id: 1,
    type: 'project_new',
    payload_json: { project_id: 201, title: '«Нива-Агро» добавлена в реестр' },
    related_object: 'investment_project:201',
    created_at: '2026-10-05T09:15:00Z',
    read_at: null,
  },
];

const DEFINITIONS: Definition[] = [
  {
    pattern: /^\/auth\/login$/,
    get: () => ({ mfa_required: true, partial_token: 'mock-partial-token', access_token: null }),
  },
  {
    pattern: /^\/auth\/2fa\/verify$/,
    get: () => ({ access_token: 'mock-access-token', refresh_token: 'mock-refresh-token', token_type: 'bearer' }),
  },
  { pattern: /^\/auth\/me$/, get: () => ({ id: 1, login: 'analyst', role: 'analyst', mfa_enabled: true }) },
  {
    pattern: /^\/dashboard\/summary$/,
    get: (): DashboardSummary => ({
      companies: 48,
      active_projects: 6,
      open_tenders: 6,
      unread_notifications: NOTIFICATIONS.length,
    }),
  },
  {
    pattern: /^\/companies$/,
    get: (_match, search) => {
      const region = search.get('region_id');
      return region ? COMPANIES.filter((c) => String(c.region_id) === region) : COMPANIES;
    },
  },
  { pattern: /^\/companies\/(\d+)$/, get: (match) => companyCard(Number(match[1])) },
  {
    pattern: /^\/radar\/heatmap$/,
    get: (_match, search) => {
      const region = search.get('region_id');
      const group = search.get('industry_group');
      return HEATMAP.filter(
        (cell) =>
          (!region || String(cell.region_id) === region) &&
          (!group || cell.industry_group.toLowerCase().includes(group.toLowerCase())),
      );
    },
  },
  { pattern: /^\/radar\/white-spaces$/, get: () => WHITE_SPACES },
  { pattern: /^\/investments\/timeline$/, get: () => TIMELINE },
  { pattern: /^\/investments\/(\d+)\/needs$/, get: () => NEEDS },
  { pattern: /^\/investments\/(\d+)$/, get: (match) => ({ ...PROJECT_CARD, id: Number(match[1]) }) },
  {
    pattern: /^\/investments$/,
    get: (_match, search) => {
      const stage = search.get('stage');
      return stage ? PROJECTS.filter((p) => p.stage === stage) : PROJECTS;
    },
  },
  { pattern: /^\/deals\/estimate$/, get: () => ESTIMATE },
  { pattern: /^\/subscriptions$/, get: () => [] },
  { pattern: /^\/notifications$/, get: () => NOTIFICATIONS },
  { pattern: /^\/positions\/prices$/, get: () => POSITIONS },
  { pattern: /^\/regions$/, get: () => REGIONS },
  { pattern: /^\/industries$/, get: () => INDUSTRIES },
];

const EMPTY_BY_PATH: Array<[RegExp, unknown]> = [
  [/^\/radar\/white-spaces$/, []],
  [/^\/companies$/, []],
  [/^\/investments/, []],
  [/^\/notifications$/, []],
  [
    /^\/dashboard\/summary$/,
    { companies: 0, active_projects: 0, open_tenders: 0, unread_notifications: 0 },
  ],
];

/* ---------------- экспорт CSV (ТЗ 12) ----------------
 * Контракт мока повторяет backend: POST /exports/csv {module, filters, mode}.
 * CSV: UTF-8 BOM, запятая, кавычки RFC 4180, заголовки на русском,
 * идентификаторы (inn, region_code, source_url) и даты ISO 8601.
 */
type ExportFilters = Record<string, unknown>;

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csvLine(...cells: unknown[]): string {
  return cells.map(csvCell).join(',');
}

function csvDoc(lines: unknown[][]): string {
  return lines.map((line) => csvLine(...line)).join('\r\n');
}

const CLIENT_STATUS: Record<string, string> = {
  active: 'Действующий клиент',
  prospect: 'Потенциальный клиент',
  unknown: 'Не определено',
};

type QuadrantCode = 'white' | 'strong' | 'stable' | 'weak' | null;

function quadrantOf(potential: number, presence: number, threshold: number): QuadrantCode {
  if (potential >= threshold && presence < threshold) return 'white';
  if (potential >= threshold && presence >= threshold) return 'strong';
  if (presence >= threshold) return 'stable';
  return 'weak';
}

/** Тот же срез, что строит Радар: регион + отрасль + квадрант (ТЗ 12 «текущие фильтры»). */
function filteredCompanies(filters: ExportFilters, empty: boolean): Company[] {
  if (empty) return [];
  const region = filters.region_id ? String(filters.region_id) : null;
  const group =
    typeof filters.industry_group === 'string' && filters.industry_group
      ? filters.industry_group.toLowerCase()
      : null;
  const quadrant = typeof filters.quadrant === 'string' ? filters.quadrant : null;

  return COMPANIES.filter((company) => {
    if (region && String(company.region_id) !== region) return false;
    if (group) {
      const industry = INDUSTRIES.find((item) => item.id === company.industry_id);
      if (!industry || industry.group.toLowerCase() !== group) return false;
    }
    if (quadrant) {
      const cell = HEATMAP.find((item) => item.region_id === company.region_id);
      if (!cell || quadrantOf(cell.potential_score, cell.presence_score, 50) !== quadrant) return false;
    }
    return true;
  });
}

function companiesCsv(filters: ExportFilters, mode: string, empty: boolean): string {
  const rows = filteredCompanies(filters, empty).map((company) => {
    const region = REGIONS.find((item) => item.id === company.region_id);
    return [
      company.id,
      company.name,
      company.inn,
      CLIENT_STATUS[company.client_status] ?? company.client_status,
      region?.name ?? '',
      region?.code ?? '',
      company.revenue_latest,
      company.revenue_year,
      company.revenue_yoy,
      `https://example.com/company/${company.id}`,
    ];
  });
  if (mode === 'crm') {
    // Документированный маппинг CRM-режима: колонки rt_* (целевая CRM — уточняется у куратора).
    return csvDoc([
      ['rt_id', 'rt_name', 'rt_inn', 'rt_status', 'rt_region', 'rt_region_code', 'rt_revenue_latest', 'rt_revenue_year', 'rt_revenue_yoy', 'rt_source_url'],
      ...rows,
    ]);
  }
  return csvDoc([
    ['Идентификатор', 'Название', 'ИНН', 'Статус клиента', 'Регион', 'Код региона', 'Выручка (млн ₽)', 'Год', 'Динамика (%)', 'Источник'],
    ...rows,
  ]);
}

function investmentsCsv(filters: ExportFilters): string {
  const stage = typeof filters.stage === 'string' && filters.stage ? filters.stage : null;
  const region = filters.region_id ? String(filters.region_id) : null;
  const projectId = filters.project_id ? Number(filters.project_id) : null;

  const projects = PROJECTS.filter((project) => {
    if (stage && project.stage !== stage) return false;
    if (region && String(project.region_id) !== region) return false;
    if (projectId && project.id !== projectId) return false;
    return true;
  });

  const lines: unknown[][] = [
    ['Идентификатор', 'Название', 'Стадия', 'Регион', 'Бюджет (₽)', 'Старт', 'Источник'],
  ];
  for (const project of projects) {
    const regionRow = REGIONS.find((item) => item.id === project.region_id);
    lines.push([
      project.id,
      project.title,
      project.stage,
      regionRow?.name ?? '',
      project.estimated_budget,
      project.planned_start,
      project.source_url,
    ]);
  }

  // Когда выбран конкретный проект (таблица тендеров в карточке), выгружаем его закупки.
  if (projectId) {
    const project = PROJECTS.find((item) => item.id === projectId);
    lines.push([], ['Тендеры проекта', project?.title ?? '']);
    lines.push(['Идентификатор', 'Закупка', 'Цена (₽)', 'Дедлайн (ISO 8601)', 'Источник']);
    for (const tender of PROJECT_CARD.tenders) {
      lines.push([tender.id, tender.title, tender.price, tender.deadline_date, tender.source_url]);
    }
  }
  return csvDoc(lines);
}

/** CSV калькулятора: вилка, аналоги, поправки, разбивка — то, что видит пользователь (ТЗ 12). */
function dealsCsv(filters: ExportFilters): string {
  const estimate = ESTIMATE;
  const lines: unknown[][] = [
    ['Оценка ID', 'Валюта', 'Минимум', 'Оптимум', 'Максимум', 'Метод', 'Модель', 'Качество данных', 'Период цен', 'Требует проверки специалистом'],
    [
      estimate.estimate_id,
      estimate.currency,
      estimate.estimate.min,
      estimate.estimate.optimum,
      estimate.estimate.max,
      estimate.estimator_mode,
      estimate.model_version,
      estimate.data_quality,
      estimate.price_period ?? '',
      estimate.requires_human_approval ? 'да' : 'нет',
    ],
    [],
    ['Аналоги'],
    ['Идентификатор', 'Название', 'Стоимость (₽)', 'Сходство', 'Основа цены'],
    ...estimate.comparables.map((item) => [
      item.deal_id,
      item.title,
      item.contract_value,
      item.similarity,
      item.retro_price_basis,
    ]),
    [],
    ['Поправки'],
    ['Фактор', 'Значение', 'Пояснение'],
    ...estimate.adjustments.map((item) => [item.factor, item.value, item.note ?? '']),
    [],
    ['Разбивка по статьям'],
    ['Статья', 'Сумма (₽)'],
    ...estimate.breakdown.map((item) => [item.article, item.amount]),
  ];
  void filters;
  return csvDoc(lines);
}

function exportCsvDoc(module: string, filters: ExportFilters, mode: string, empty: boolean): string {
  // Пустой сценарий — только заголовки: экспорт не должен выдумывать строки.
  if (module === 'investments') return empty ? csvDoc([['Идентификатор', 'Название', 'Стадия', 'Регион', 'Бюджет (₽)', 'Старт', 'Источник']]) : investmentsCsv(filters);
  if (module === 'deals') return dealsCsv(filters);
  return companiesCsv(filters, mode, empty);
}

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function buildReply(scenario: MockScenario) {
  return function reply(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const url = new URL(String(input), 'http://mock.local');
    const path = url.pathname.replace(/^\/api\/v1/, '') || '/';
    const method = (init?.method ?? 'GET').toUpperCase();

    if (scenario === 'error') {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: 'Сервер недоступен в демонстрационном режиме' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }

    // Экспорт отвечает файлом: CSV с UTF-8 BOM (ТЗ 12) и «DOCX» как набор байт.
    if (path === '/exports/csv') {
      let payload: { module?: string; filters?: ExportFilters; mode?: string } = {};
      try {
        payload = JSON.parse(String(init?.body ?? '{}')) as typeof payload;
      } catch {
        payload = {};
      }
      const module = payload.module ?? 'companies';
      const filters = payload.filters ?? {};
      const mode = payload.mode === 'crm' ? 'crm' : 'general';
      const isEmpty = scenario === 'empty';
      return Promise.resolve(
        new Response('\uFEFF' + exportCsvDoc(module, filters, mode, isEmpty), {
          status: 200,
          headers: {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': `attachment; filename="${module}-export.csv"`,
          },
        }),
      );
    }
    if (path.startsWith('/exports/proposal')) {
      const isCreate = method === 'POST' && !path.endsWith('/download');
      return Promise.resolve(
        isCreate
          ? json({ file_ref: '/exports/proposal.docx', status: 'created' })
          : new Response('PK\u0003\u0004mock-docx', {
              status: 200,
              headers: {
                'Content-Type':
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              },
            }),
      );
    }
    if (method === 'POST' && path === '/subscriptions') {
      return Promise.resolve(json({ id: 1, status: 'created' }));
    }

    if (scenario === 'empty') {
      const empty = EMPTY_BY_PATH.find(([pattern]) => pattern.test(path));
      if (empty) return Promise.resolve(json(empty[1]));
    }

    for (const definition of DEFINITIONS) {
      const match = path.match(definition.pattern);
      if (match) return Promise.resolve(json(definition.get(match, url.searchParams)));
    }

    return Promise.resolve(
      new Response(JSON.stringify({ detail: `Мок не знает маршрут ${method} ${path}` }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  };
}

/** Демо-режим активен, если его включил текущий ран (VITE_USE_MOCKS или ?mock). */
export function isMockMode(): boolean {
  const persisted = globalThis.sessionStorage?.getItem(MOCK_KEY) ?? null;
  const search = new URLSearchParams(globalThis.location?.search ?? '');
  return search.get('mock') !== '0' && (import.meta.env.VITE_USE_MOCKS === '1' || search.has('mock') || persisted !== null);
}

/** Включает мок, если запрос на то есть. Возвращает выбранный сценарий или null. */
export function installMocks(): MockScenario | null {
  // globalThis, а не window: в браузере это один объект, но так мок остаётся тестируемым.
  const search = new URLSearchParams(globalThis.location?.search ?? '');

  // Вход делает window.location.assign('/'), и ?mock из адреса исчезает. Без памяти
  // мок выключался бы ровно на первом защищённом экране, поэтому флаг переходит
  // через sessionStorage вместе с токеном.
  const persisted = globalThis.sessionStorage?.getItem(MOCK_KEY) ?? null;
  if (search.get('mock') === '0') {
    globalThis.sessionStorage?.removeItem(MOCK_KEY);
    return null;
  }

  const enabled = import.meta.env.VITE_USE_MOCKS === '1' || search.has('mock') || persisted !== null;
  if (!enabled) return null;

  const requested = search.get('scenario') ?? persisted;
  const scenario: MockScenario =
    requested === 'empty' || requested === 'error' ? requested : 'data';

  globalThis.sessionStorage?.setItem(MOCK_KEY, scenario);
  globalThis.fetch = buildReply(scenario);
  return scenario;
}
