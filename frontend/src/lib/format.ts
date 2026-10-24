/** Форматирование значений для экранов: деньги и проценты приходят строками Decimal
 * (Pydantic v2), поэтому парсим Number, а не предполагаем число на входе (ТЗ 6.8,
 * «Данные и деньги не должны терять разряды при отображении»).
 */

const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const precise = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const shortDate = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });

function toFinite(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

/** Деньги: "850000000.00" → "850 000 000", null/пропуск → "—" (не «0») (ТЗ 6.8). */
export function formatMoney(value: string | number | null | undefined): string {
  const num = toFinite(value);
  return num === null ? '—' : `${precise.format(num)} ₽`;
}

/** Целое число с разделителями: годы, количество, покрытие без знака ₽. */
export function formatNumber(value: string | number | null | undefined): string {
  const num = toFinite(value);
  return num === null ? '—' : integer.format(num);
}

/** Процентное значение уже в процентах: 6.4 → "6,4 %". */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: digits })} %`;
}

/** Доля в долях единицы: 0.22 → "22 %". */
export function formatShare(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toLocaleString('ru-RU', { maximumFractionDigits: digits })} %`;
}

/** ISO-дата "2026-09-01" → "01.09.2026"; пусто → "—". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return Number.isNaN(date.getTime()) ? value : shortDate.format(date);
}