/** Форматирование значений: Decimal-строки и пропуски (null ≠ 0, ТЗ 6.8). */

import { describe, expect, it } from 'vitest';

import { formatDate, formatMoney, formatNumber, formatPercent, formatShare, safeExternalUrl } from '@/lib/format';

describe('форматирование денег и чисел', () => {
  it('деньги из Decimal-строки не теряют разряды и получают знак ₽', () => {
    expect(formatMoney('850000000.00')).toBe('850\u00A0000\u00A0000 ₽');
    expect(formatMoney('4.15')).toBe('4,15 ₽');
  });

  it('числа из строки не превращаются в NaN', () => {
    expect(formatNumber('18')).toBe('18');
    expect(formatNumber('11240.50')).toBe('11\u00A0241');
  });

  it('пропуск и null показываются как «—», а не как ноль (ТЗ 6.8)', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney('')).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(formatPercent(null)).toBe('—');
    expect(formatShare(null)).toBe('—');
  });

  it('нечисловое значение не роняет экран', () => {
    expect(formatMoney('abc')).toBe('—');
    expect(formatNumber('NaN')).toBe('—');
  });

  it('процент уже в процентах, доля — приведение к процентам', () => {
    expect(formatPercent(6.4)).toBe('6,4 %');
    expect(formatShare(0.22)).toBe('22 %');
    expect(formatShare(0.715, 1)).toBe('71,5 %');
  });

  it('дата ISO отображается в русском формате', () => {
    expect(formatDate('2026-09-01')).toBe('01.09.2026');
    expect(formatDate('2026-10-05T09:15:00Z')).toBe('05.10.2026');
    expect(formatDate(null)).toBe('—');
  });

  it('внешняя ссылка пропускает только http/https, остальное — null (XSS-защита)', () => {
    expect(safeExternalUrl('https://example.com/a')).toBe('https://example.com/a');
    expect(safeExternalUrl('http://example.com')).toBe('http://example.com/');
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull();
    expect(safeExternalUrl('data:text/html,<script>')).toBeNull();
    expect(safeExternalUrl('not a url')).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
  });
});