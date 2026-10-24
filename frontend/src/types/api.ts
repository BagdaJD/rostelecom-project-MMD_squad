/** Типы API-контрактов. Держатся в синхронизации с app/schemas (ТЗ 4). */

export type TrustMeta = {
  scoring_mode: 'heuristic' | 'trained' | 'rule_based';
  model_version: string;
  confidence: 'low' | 'medium' | 'high';
  data_quality: 'insufficient' | 'limited' | 'sufficient';
  calculated_at: string;
};

export type Company = {
  id: number;
  name: string;
  inn: string | null;
  industry_id: number | null;
  region_id: number | null;
  client_status: 'active' | 'prospect' | 'unknown';
  revenue_latest: string | null;
  revenue_year: number | null;
  revenue_yoy: number | null;
};

export type HeatCell = {
  region_id: number;
  region_name: string;
  industry_group: string;
  companies_count: number;
  revenue_sum: string;
  growth_share: number;
  potential_score: number;
  presence_score: number;
  /** Центр агрегата для карты; приходит из mv_region_density. */
  longitude?: number | null;
  latitude?: number | null;
};

export type WhiteSpace = {
  region_id: number;
  region_name: string;
  industry_group: string;
  service_type: string | null;
  potential_score: number;
  presence_score: number;
  explanation: string[];
};

export type InvestmentProject = {
  id: number;
  title: string;
  stage: string;
  planned_start: string | null;
  estimated_budget: string | null;
  region_id: number | null;
  initiator_company_id: number | null;
  source_url: string | null;
};

export type TimelinePoint = {
  period: string;
  region_id: number | null;
  industry_id: number | null;
  events_count: number;
  project_ids: number[];
};

export type Need = {
  need_category: string;
  probability: number | null;
  evidence: string | null;
  rule_id: string | null;
  model_version: string;
};

export type DealEstimateRequest = {
  project_type: string;
  scale: string;
  region_id?: number | null;
  works: string[];
  equipment: string[];
  software: string[];
  urgency: 'normal' | 'high' | 'critical';
  financing_scheme?: string | null;
  has_unique_solution: boolean;
};

export type Comparable = {
  deal_id: number;
  title: string;
  contract_value: string;
  similarity: number;
  retro_price_basis: string;
};

export type DealEstimate = {
  estimate_id: number;
  currency: string;
  estimate: { min: string; optimum: string; max: string };
  estimator_mode: string;
  confidence: string;
  data_quality: string;
  comparables: Comparable[];
  adjustments: { factor: string; value: number; note: string | null }[];
  breakdown: { article: string; amount: string }[];
  price_period: string | null;
  model_version: string;
  requires_human_approval: boolean;
  warning: string | null;
};

export type DashboardSummary = {
  companies: number;
  active_projects: number;
  open_tenders: number;
  unread_notifications: number;
};

/*
 * Ниже — контракты экранов, которых ещё нет в UI. Источник полей: backend/app/schemas
 * и ответственные хэндлеры, а не догадка. Поля Decimal приходят строками (Pydantic v2
 * в JSON), поэтому деньги — string, а не number: форматировать надо без потери разрядов.
 */

/** Закупка в карточке проекта: срез полей Tender (backend/app/models/investment.py). */
export type TenderBrief = {
  id: number;
  title: string;
  price: string | null;
  deadline_date: string | null;
  source_url: string | null;
};

/**
 * GET /investments/{id} — хэндлер project_card уже отдаёт эту форму
 * (backend/app/api/v1/endpoints/investments.py). contact_window — из ml/needs.py,
 * для stage = completed равен null.
 */
export type ProjectCard = {
  id: number;
  title: string;
  description: string | null;
  stage: string;
  planned_start: string | null;
  planned_end: string | null;
  estimated_budget: string | null;
  region_id: number | null;
  initiator_company_id: number | null;
  source_url: string | null;
  contact_window: string | null;
  tenders: TenderBrief[];
  /** Вехи проекта из GET /investments/{id} в форме будущего контракта (этап B). */
  milestones?: ProjectMilestone[];
};

/** Веха/стадия проекта с датами и источником (ТЗ 7: стадии/вехи проекта). */
export type ProjectMilestone = {
  id?: number;
  title: string;
  date: string | null;
  status: string;
  source_url: string | null;
};

/**
 * Строка временного ряда показателя (CompanyMetric, ТЗ 6.2).
 * value === null означает «данных нет»; 0 — это значение, а не пропуск (ТЗ 6.8).
 */
export type CompanyMetricPoint = {
  metric_code: 'revenue' | 'profit' | 'employees' | 'tax' | 'tenders_won' | string;
  period_year: number;
  value: string | null;
  unit: string;
  source_id: number;
  fetched_at: string;
};

/** Подтверждённое присутствие услуг в регионе (CustomerPresence) — основа client_status. */
export type CustomerPresencePoint = {
  region_id: number;
  municipality: string | null;
  service_type: string;
  coverage_percent: string | null;
  contracts_count: number | null;
  as_of_date: string;
  /** Синтетическое покрытие в демо: показывать плашкой, а не выдавать за факт (ТЗ 6.8). */
  is_synthetic: boolean;
  source_id: number | null;
};

/** Provenance значения: «Как получено это значение» — источник, дата, ссылка (ТЗ 2). */
export type Provenance = {
  source: string;
  external_id: string | null;
  fetched_at: string;
  license_note: string | null;
  source_url?: string | null;
};

/**
 * ЗАГЛУШКА: GET /companies/{id} на бэкенде ещё не реализован (в OpenAPI его нет).
 * Форма собрана по сущностям ТЗ 6.2 и по тому, что уже отдают соседние хэндлеры.
 * Утверждать вместе с бэкендом до подключения экрана карточки компании.
 */
export type CompanyCard = Company & {
  ogrn: string | null;
  employee_count: number | null;
  metrics: CompanyMetricPoint[];
  presence: CustomerPresencePoint[];
  provenance: Provenance[];
  /** Признак спроса, из-за которого компания стала потенциальной (ТЗ 7). */
  demand_signals: string[];
};

/** ЗАГЛУШКА: GET /positions/prices не реализован. Без него состав «оборудование и ПО» неоткуда считать. */
export type PositionPrice = {
  id: number;
  name: string;
  category: 'equipment' | 'software' | 'works' | string;
  unit: string;
  price_min: string | null;
  price_max: string | null;
  price_typical: string | null;
  region_id: number | null;
  price_period: string | null;
  is_synthetic: boolean;
};

/** ЗАГЛУШКА: GET /radar/insights не реализован. Вход федеральных игроков — требование кейса. */
export type MarketEntrySignal = {
  id: number;
  company_id: number;
  region_id: number | null;
  signal_type: 'new_registration' | 'new_branch' | 'cross_region' | 'first_tender_in_region' | string;
  detected_at: string;
  evidence: string | null;
  source_id: number | null;
};

/** ЗАГЛУШКА: GET /regions, /industries, /dictionaries/{code} не реализованы. */
export type RegionOption = { id: number; name: string; code: string };
export type IndustryOption = { id: number; code: string; name: string; group: string };
export type DictionaryItem = { code: string; label: string; order_no: number };

/** GET /notifications — маршрут есть (NotificationOut), экрана пока нет. */
export type NotificationItem = {
  id: number;
  type: string;
  payload_json: Record<string, unknown>;
  related_object: string | null;
  created_at: string;
  read_at: string | null;
};

/** Стадии проекта — словарь из ТЗ 7, подписи совпадают с формулировками кейса. */
export const stageLabel: Record<string, string> = {
  design: 'Проектирование',
  modernization: 'Модернизация',
  construction: 'Стройка',
  launch: 'Запуск',
  completed: 'Завершён',
};

export const needLabel: Record<string, string> = {
  connectivity: 'Связь и каналы',
  it_infrastructure: 'ИТ-инфраструктура и ЦОД',
  information_security: 'Информационная безопасность',
  video_surveillance: 'Видеонаблюдение',
  iot_asu_tp: 'IoT и АСУ ТП',
  insufficient_data: 'Недостаточно данных',
};
