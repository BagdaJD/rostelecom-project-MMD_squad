/** Логика экрана калькулятора без React: ползунок цены, платежи, форматирование.
 *
 * Бэкенд отдаёт кривую «цена → маржа, шанс выиграть» точками; между точками ползунок
 * интерполирует линейно, поэтому пересчёт мгновенный и не требует запросов.
 */

import type { CurvePoint, DealCatalog, PaymentOption } from './types';

export type PricePoint = {
  price: number;
  marginPct: number;
  winPct: number | null;
  expectedProfit: number | null;
};

/** Значения кривой в произвольной точке: маржа считается точно, шанс — интерполяцией. */
export function pointAt(curve: CurvePoint[], cost: number, price: number): PricePoint {
  const marginPct = price > 0 ? ((price - cost) / price) * 100 : 0;
  const withWin = curve.filter((p) => p.win_prob !== null);
  if (withWin.length === 0) return { price, marginPct, winPct: null, expectedProfit: null };

  const first = withWin[0]!;
  const last = withWin[withWin.length - 1]!;
  let winPct: number;
  if (price <= first.price) winPct = first.win_prob!;
  else if (price >= last.price) winPct = last.win_prob!;
  else {
    const right = withWin.findIndex((p) => p.price >= price);
    const a = withWin[right - 1]!;
    const b = withWin[right]!;
    const t = (price - a.price) / (b.price - a.price);
    winPct = a.win_prob! + (b.win_prob! - a.win_prob!) * t;
  }
  return { price, marginPct, winPct, expectedProfit: (price - cost) * (winPct / 100) };
}

/** Схемы оплаты для любой цены — та же формула аннуитета, что в ml/deal_estimator.py. */
export function paymentOptions(price: number, s: DealCatalog['settings']): PaymentOption[] {
  const r = s.annual_rate / 12;
  const annuity = (n: number) => (r > 0 ? (price * r) / (1 - (1 + r) ** -n) : price / n);
  const inst = annuity(s.installment_months);
  const opex = annuity(s.opex_months) + s.opex_service_fee;
  return [
    { scheme: 'capex', label: 'Единовременно', months: 1, monthly: price, total: price, overpayment: 0 },
    {
      scheme: 'installment',
      label: `Рассрочка ${s.installment_months} мес.`,
      months: s.installment_months,
      monthly: inst,
      total: inst * s.installment_months,
      overpayment: inst * s.installment_months - price,
    },
    {
      scheme: 'opex',
      label: `Сервис ${s.opex_months} мес.`,
      months: s.opex_months,
      monthly: opex,
      total: opex * s.opex_months,
      overpayment: opex * s.opex_months - price,
      service_fee: s.opex_service_fee,
    },
  ];
}

const nbsp = ' ';

export function rub(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Math.round(Number(value));
  return `${n.toLocaleString('ru-RU').replace(/\s/g, nbsp)}${nbsp}₽`;
}

/** «889 тыс.» — для подписей графиков и ползунка. */
export function thousands(value: number): string {
  return `${Math.round(value / 1000).toLocaleString('ru-RU').replace(/\s/g, nbsp)}${nbsp}тыс.`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(digits).replace('.', ',')}%`;
}

export const FACTOR_LABELS: Record<string, string> = {
  project_level: 'Уровень',
  regional_coefficient: 'Регион',
  urgency: 'Срочность',
  unique_solution: 'Уникальность',
  complexity_mode: 'Сложность',
};
