/** Типы API калькулятора (/calculator/*). Общие типы src/types/api.ts не меняются. */

export type DealItem = { code: string; qty: number };

export type DealCustomItem = {
  name: string;
  qty: number;
  unit_price: number;
  kind: 'equipment' | 'software';
  nonstandard?: boolean;
};

export type ProjectLevel = 'basic' | 'advanced' | 'expert';
export type PaymentScheme = 'capex' | 'installment' | 'opex';

export type DealEstimateRequest = {
  project_type?: 'dispatching';
  object_type?: string | null;
  area_m2?: number | null;
  /** id региона калькулятора (список — в каталоге). */
  region_id?: number | null;
  systems?: string[] | null;
  project_level?: ProjectLevel;
  items?: DealItem[];
  custom_items?: DealCustomItem[];
  duration_months?: number | null;
  has_unique_solution?: boolean;
  /** budget — госзаказчик (44-ФЗ). */
  financing_scheme?: string | null;
  payment_scheme?: PaymentScheme;
  investment_project_id?: number | null;
  company_id?: number | null;
};

export type Comparable = {
  deal_id: number;
  title: string;
  contract_value: string;
  similarity: number;
  retro_price_basis: string;
  cost_value?: number | null;
  price_index?: number | null;
  outcome?: 'won' | 'lost' | null;
  area_m2?: number | null;
};

export type CostFactor = { factor: string; value: number; note: string; source: string };

export type CostLine = {
  code: string | null;
  name: string;
  group: string;
  qty: number;
  unit_price: number;
  amount: number;
};

export type DealCost = {
  total: number;
  breakdown: { article: string; label: string; amount: number; basis: string | null }[];
  factors: CostFactor[];
  lines: CostLine[];
  points: number;
  norm_months: number;
  object_type: string;
  object_label: string | null;
  area_m2: number | null;
  complexity_mode: string;
  region_label: string | null;
  systems: string[];
};

export type CurvePoint = {
  price: number;
  margin_pct: number;
  win_prob: number | null;
  expected_profit: number | null;
};

export type PaymentOption = {
  scheme: PaymentScheme;
  label: string;
  months: number;
  monthly: number;
  total: number;
  overpayment: number;
  service_fee?: number;
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
  breakdown: { article: string; label?: string; amount: string }[];
  price_period: string | null;
  model_version: string;
  requires_human_approval: boolean;
  warning: string | null;
  cost: DealCost | null;
  margin: { min: number; optimum: number; max: number } | null;
  win_probability: number | null;
  optimum_method: string | null;
  index_stats: { q25?: number; median?: number; q75?: number; n: number } | null;
  curve: CurvePoint[];
  payment_options: PaymentOption[];
  payment_scheme: PaymentScheme | null;
  warnings: string[];
  approved_price: string | null;
  win_model: WinModelInfo | null;
};

export type WinFactor = {
  factor: string;
  label: string;
  value: string;
  typical: string;
  /** На сколько процентных пунктов шанс выше (+) или ниже (−), чем у типичного проекта. */
  delta_pp: number;
};

export type WinModelInfo =
  | {
      type: 'multifactor';
      model: string;
      n_train: number;
      n_test: number;
      auc: number | null;
      auc_baseline: number | null;
      brier: number | null;
      basis: string;
      factors: WinFactor[];
    }
  | { type: 'single_factor'; model: string; n: number; basis: string };

export type CatalogItem = {
  code: string;
  name: string;
  unit: string;
  price: number;
  complexity: number;
  is_synthetic: boolean;
};

export type DealCatalog = {
  systems: { group: string; items: CatalogItem[] }[];
  object_types: { code: string; label: string; systems: string[] }[];
  project_levels: { code: ProjectLevel; label: string; value: number; description: string | null }[];
  work_stages: { code: string; label: string; value: number; description: string | null }[];
  payment_schemes: { code: PaymentScheme; label: string }[];
  regions: {
    id: number;
    code: string;
    name: string;
    parent_id: number | null;
    coefficient: number;
    is_zone: boolean;
  }[];
  settings: {
    complexity_mode: string;
    margin_floor: number;
    annual_rate: number;
    installment_months: number;
    opex_months: number;
    opex_service_fee: number;
    unique_solution_coefficient: number;
    nonstandard_reserve_share: number;
  };
};

export type DealDraft = {
  request: DealEstimateRequest;
  explain: {
    project_title: string;
    object_type_label: string;
    object_type_from: string;
    area_is_estimated: boolean;
    area_from: string;
    duration_from: string;
    company: { id: number; name: string; inn: string | null } | null;
  };
};
