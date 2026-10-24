/** Форма калькулятора: объект → уровень и оплата → состав оборудования. */

import type { DealCatalog, DealCustomItem, PaymentScheme, ProjectLevel } from './types';

import { rub } from './pricing';

export type FormState = {
  object_type: string;
  area_m2: number | null;
  region_id: number | null;
  project_level: ProjectLevel;
  duration_months: number | null;
  payment_scheme: PaymentScheme;
  has_unique_solution: boolean;
  /** Госзаказчик (торги по 44-ФЗ) — влияет на шанс выиграть в модели. */
  budget_customer: boolean;
  systems: string[];
  items: Record<string, number>;
  custom: DealCustomItem[];
  investment_project_id: number | null;
  company_id: number | null;
};

export const emptyForm: FormState = {
  object_type: 'retail',
  area_m2: 4500,
  region_id: null,
  project_level: 'advanced',
  duration_months: 3,
  payment_scheme: 'capex',
  has_unique_solution: false,
  budget_customer: false,
  systems: [],
  items: {},
  custom: [],
  investment_project_id: null,
  company_id: null,
};

type Props = {
  catalog: DealCatalog;
  form: FormState;
  onChange: (next: FormState) => void;
  onSuggest: () => void;
  onSubmit: () => void;
  pending: boolean;
  normMonths: number | null;
};

const num = (value: string): number | null => (value === '' ? null : Number(value));

export function ParamsForm({ catalog, form, onChange, onSuggest, onSubmit, pending, normMonths }: Props) {
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => onChange({ ...form, [key]: value });
  const prices = new Map(catalog.systems.flatMap((g) => g.items.map((i) => [i.code, i.price] as const)));
  const totalQty = Object.values(form.items).reduce((a, b) => a + b, 0);
  const equipmentSum = Object.entries(form.items).reduce((a, [code, q]) => a + q * (prices.get(code) ?? 0), 0);

  const rostov = catalog.regions.filter((r) => !r.is_zone && (r.code === 'RU-ROS' || r.code.startsWith('RU-ROS-')));
  const zones = catalog.regions.filter((r) => r.is_zone);
  const other = catalog.regions.filter((r) => !r.is_zone && !rostov.includes(r));
  const regionOption = (r: DealCatalog['regions'][number]) => (
    <option key={r.id} value={r.id}>
      {r.name.replace(/^Зона: /, '')} · ×{r.coefficient.toLocaleString('ru-RU')}
    </option>
  );
  const objectSystems = catalog.object_types.find((t) => t.code === form.object_type)?.systems ?? [];
  const activeSystems = form.systems.length ? form.systems : objectSystems;

  return (
    <form
      className="card calc-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <h2>Параметры проекта</h2>

      <fieldset className="calc-fields">
        <legend>1. Объект</legend>
        <label>
          Тип объекта
          <select
            value={form.object_type}
            onChange={(e) => onChange({ ...form, object_type: e.target.value, systems: [] })}
          >
            {catalog.object_types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Площадь, м²
          <input
            type="number"
            min={1}
            step="any"
            inputMode="numeric"
            value={form.area_m2 ?? ''}
            onChange={(e) => set('area_m2', num(e.target.value))}
          />
        </label>
        <label className="wide">
          Регион (коэффициент МОД3)
          <select value={form.region_id ?? ''} onChange={(e) => set('region_id', num(e.target.value))}>
            <option value="">Не указан · ×1</option>
            <optgroup label="Ростовская область">{rostov.map(regionOption)}</optgroup>
            <optgroup label="Зоны из справочника">{zones.map(regionOption)}</optgroup>
            {other.length > 0 && <optgroup label="Другие регионы">{other.map(regionOption)}</optgroup>}
          </select>
        </label>
        <label>
          Срок реализации, мес.
          <input
            type="number"
            min={0.5}
            step="any"
            inputMode="decimal"
            value={form.duration_months ?? ''}
            onChange={(e) => set('duration_months', num(e.target.value))}
          />
          {normMonths !== null && (
            <span className="hint">
              норма ≈ {normMonths.toLocaleString('ru-RU')} мес.; быстрее — дороже (до ×1,3)
            </span>
          )}
        </label>
      </fieldset>

      <fieldset>
        <legend>2. Уровень проекта</legend>
        <div className="choice-cards">
          {catalog.project_levels.map((level) => (
            <label key={level.code} className={form.project_level === level.code ? 'choice on' : 'choice'}>
              <input
                type="radio"
                name="level"
                checked={form.project_level === level.code}
                onChange={() => set('project_level', level.code)}
              />
              <strong>
                {level.label} · ×{level.value.toLocaleString('ru-RU')}
              </strong>
              <span>{level.description}</span>
            </label>
          ))}
        </div>
        <div className="calc-inline">
          <span className="muted">Оплата:</span>
          <div className="segmented" role="radiogroup" aria-label="Схема оплаты">
            {catalog.payment_schemes.map((p) => (
              <button
                type="button"
                key={p.code}
                role="radio"
                aria-checked={form.payment_scheme === p.code}
                className={form.payment_scheme === p.code ? 'on' : ''}
                onClick={() => set('payment_scheme', p.code)}
              >
                {p.label.replace(/ \(.*\)$/, '')}
              </button>
            ))}
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={form.has_unique_solution}
              onChange={(e) => set('has_unique_solution', e.target.checked)}
            />
            Уникальное решение (×{catalog.settings.unique_solution_coefficient.toLocaleString('ru-RU')})
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.budget_customer}
              onChange={(e) => set('budget_customer', e.target.checked)}
            />
            Госзаказчик (44-ФЗ)
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>3. Состав оборудования</legend>
        <div className="calc-inline">
          {catalog.systems.map((g) => (
            <label key={g.group} className="check chip-check">
              <input
                type="checkbox"
                checked={activeSystems.includes(g.group)}
                onChange={(e) =>
                  set(
                    'systems',
                    e.target.checked ? [...activeSystems, g.group] : activeSystems.filter((s) => s !== g.group),
                  )
                }
              />
              {g.group}
            </label>
          ))}
        </div>
        <div className="calc-inline">
          <button type="button" className="secondary" onClick={onSuggest} disabled={pending || !form.area_m2}>
            Подобрать по площади
          </button>
          <span className="muted">
            {totalQty} шт. · оборудование {rub(equipmentSum)} по ценам каталога
          </span>
        </div>

        <div className="systems">
          {catalog.systems.map((g) => {
            const qty = g.items.reduce((a, i) => a + (form.items[i.code] ?? 0), 0);
            return (
              <details key={g.group} open={qty > 0}>
                <summary>
                  <strong>{g.group}</strong>
                  <span className="muted">
                    {qty} шт. · сложность ×{g.items[0]?.complexity.toLocaleString('ru-RU')}
                  </span>
                </summary>
                {g.items.map((item) => (
                  <div className="item-row" key={item.code}>
                    <span>
                      {item.name}
                      <span className="muted"> · {rub(item.price)}</span>
                    </span>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      inputMode="numeric"
                      aria-label={`Количество: ${item.name}`}
                      value={form.items[item.code] ?? 0}
                      onChange={(e) => {
                        const v = Math.max(0, Number(e.target.value) || 0);
                        const items = { ...form.items, [item.code]: v };
                        if (v === 0) delete items[item.code];
                        set('items', items);
                      }}
                    />
                  </div>
                ))}
              </details>
            );
          })}
        </div>

        <details open={form.custom.length > 0}>
          <summary>
            <strong>Нестандартное оборудование и ПО</strong>
            <span className="muted">
              резерв +{Math.round(catalog.settings.nonstandard_reserve_share * 100)}%, цену подтверждает пресейл
            </span>
          </summary>
          {form.custom.map((row, i) => (
            <div className="custom-row" key={i}>
              <input
                placeholder="Наименование"
                value={row.name}
                onChange={(e) => set('custom', form.custom.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))}
              />
              <select
                value={row.kind}
                onChange={(e) =>
                  set(
                    'custom',
                    form.custom.map((r, j) => (j === i ? { ...r, kind: e.target.value as 'equipment' | 'software' } : r)),
                  )
                }
              >
                <option value="equipment">Оборудование</option>
                <option value="software">ПО</option>
              </select>
              <input
                type="number"
                min={1}
                aria-label="Количество"
                value={row.qty}
                onChange={(e) => set('custom', form.custom.map((r, j) => (j === i ? { ...r, qty: Number(e.target.value) } : r)))}
              />
              <input
                type="number"
                min={0}
                aria-label="Цена за единицу, ₽"
                placeholder="Цена, ₽"
                value={row.unit_price || ''}
                onChange={(e) =>
                  set('custom', form.custom.map((r, j) => (j === i ? { ...r, unit_price: Number(e.target.value) } : r)))
                }
              />
              <button type="button" className="link" onClick={() => set('custom', form.custom.filter((_, j) => j !== i))}>
                Удалить
              </button>
            </div>
          ))}
          <button
            type="button"
            className="link"
            onClick={() => set('custom', [...form.custom, { name: '', qty: 1, unit_price: 0, kind: 'equipment' }])}
          >
            + Добавить позицию
          </button>
        </details>
      </fieldset>

      <div className="calc-inline">
        <button type="submit" disabled={pending || (totalQty === 0 && !form.area_m2)}>
          {pending ? 'Считаем…' : 'Рассчитать цену'}
        </button>
        {totalQty === 0 && <span className="muted">Состав пуст — подберём его по площади автоматически</span>}
      </div>
    </form>
  );
}
