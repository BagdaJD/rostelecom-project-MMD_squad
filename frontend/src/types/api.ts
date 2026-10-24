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
