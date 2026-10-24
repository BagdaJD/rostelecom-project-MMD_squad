import { describe, expect, it } from 'vitest';

import type { CurvePoint, DealCatalog } from './types';

import { paymentOptions, pct, pointAt, rub } from './pricing';

const COST = 668_528.74;
const curve: CurvePoint[] = [
  { price: 800_000, margin_pct: 16.4, win_prob: 90, expected_profit: 0 },
  { price: 900_000, margin_pct: 25.7, win_prob: 80, expected_profit: 0 },
  { price: 1_000_000, margin_pct: 33.1, win_prob: 40, expected_profit: 0 },
];
const settings: DealCatalog['settings'] = {
  complexity_mode: 'works',
  margin_floor: 0.15,
  annual_rate: 0.2,
  installment_months: 12,
  opex_months: 36,
  opex_service_fee: 5000,
  unique_solution_coefficient: 1.15,
  nonstandard_reserve_share: 0.2,
};

describe('pointAt', () => {
  it('считает маржу точно и интерполирует шанс выиграть', () => {
    const p = pointAt(curve, COST, 950_000);
    expect(p.marginPct).toBeCloseTo(((950_000 - COST) / 950_000) * 100, 6);
    expect(p.winPct).toBeCloseTo(60, 6);
    expect(p.expectedProfit).toBeCloseTo((950_000 - COST) * 0.6, 2);
  });

  it('за пределами кривой берёт крайние значения', () => {
    expect(pointAt(curve, COST, 500_000).winPct).toBe(90);
    expect(pointAt(curve, COST, 2_000_000).winPct).toBe(40);
  });

  it('без модели шанса не выдумывает его', () => {
    const p = pointAt([{ price: 1, margin_pct: 1, win_prob: null, expected_profit: null }], COST, 900_000);
    expect(p.winPct).toBeNull();
    expect(p.expectedProfit).toBeNull();
  });
});

describe('paymentOptions', () => {
  it('совпадает с бэкендом (ml/deal_estimator.payment_options)', () => {
    const [capex, inst, opex] = paymentOptions(889_143, settings);
    expect(capex!.total).toBe(889_143);
    expect(inst!.monthly).toBeCloseTo(82_365, -1);
    expect(opex!.monthly).toBeCloseTo(33_044 + 5_000, -1);
    expect(inst!.overpayment).toBeGreaterThan(0);
  });
});

describe('форматирование', () => {
  it('рубли и проценты по-русски', () => {
    expect(rub(889143.22)).toBe('889 143 ₽');
    expect(rub(null)).toBe('—');
    expect(pct(24.81)).toBe('24,8%');
  });
});
