/** Квадрант «потенциал × присутствие» (ТЗ 6.4, этап B).
 *
 * Ось X — присутствие услуг компании в регионе, ось Y — потенциал среза.
 * Четыре зоны читаются как статусы: «белое пятно», «стабильный клиент»,
 * «сильный потенциал» и «низкий приоритет». Клик по зоне — фильтр по этому
 * сочетанию; контур активной точки показывает выбранный регион.
 */
import type { HeatCell } from '@/types/api';

export type Quadrant = 'white' | 'strong' | 'stable' | 'weak';

export const QUADRANTS: {
  id: Quadrant;
  label: string;
  hint: string;
  short: string;
}[] = [
  {
    id: 'white',
    label: 'Белое пятно',
    hint: 'Высокий потенциал, слабое присутствие — работаем с регионом',
    short: 'белое пятно',
  },
  {
    id: 'strong',
    label: 'Сильный потенциал',
    hint: 'Потенциал и присутствие выше среднего — удерживаем и расширяем',
    short: 'сильный потенциал',
  },
  // Порядок = раскладка 2×2: X — присутствие (слева низкое, справа высокое),
  // Y — потенциал (снизу низкий, сверху высокий).
  {
    id: 'weak',
    label: 'Низкий приоритет',
    hint: 'Потенциал и присутствие ниже среднего — следим, но не инвестируем',
    short: 'низкий приоритет',
  },
  {
    id: 'stable',
    label: 'Стабильный клиент',
    hint: 'Сильное присутствие, средний потенциал — сервисная рутина',
    short: 'стабильный клиент',
  },
];

export const quadrantLabel: Record<Quadrant, string> = {
  white: 'Белое пятно',
  strong: 'Сильный потенциал',
  stable: 'Стабильный клиент',
  weak: 'Низкий приоритет',
};

export function quadrantOf(potential: number, presence: number, threshold: number): Quadrant {
  if (potential >= threshold && presence < threshold) return 'white';
  if (potential >= threshold && presence >= threshold) return 'strong';
  if (presence >= threshold) return 'stable';
  return 'weak';
}

export function quadrantIcon(q: Quadrant): string {
  switch (q) {
    case 'white':
      return 'Б';
    case 'strong':
      return 'С';
    case 'stable':
      return 'К';
    case 'weak':
      return 'Н';
  }
}

type Props = {
  cells: HeatCell[];
  selected: number | null;
  threshold?: number;
  onSelect?: (q: Quadrant) => void;
  onSelectCell?: (regionId: number) => void;
};

export function QuadrantChart({ cells, selected, threshold = 50, onSelect, onSelectCell }: Props) {
  const quadrantCells = cells.map((cell) => ({ cell, q: quadrantOf(cell.potential_score, cell.presence_score, threshold) }));

  function zoneTitle(q: Quadrant): string {
    const item = QUADRANTS.find((entry) => entry.id === q);
    return item ? `${item.label}: ${item.hint}` : q;
  }

  function clickCell(regionId: number): void {
    onSelectCell?.(regionId);
  }

  return (
    <div className="quadrant-wrap">
      <div className="quadrant-chart" role="group" aria-label="Квадрант потенциал × присутствие">
        {/* Оси подписи */}
        <div className="quadrant-axis quadrant-axis--x" aria-hidden="true">
          Присутствие →
        </div>
        <div className="quadrant-axis quadrant-axis--y" aria-hidden="true">
          Потенциал ↑
        </div>

        <div className="quadrant-grid">
          {QUADRANTS.map((q) => (
            <button
              type="button"
              key={q.id}
              className={`quadrant-cell quadrant-cell--${q.id}`}
              title={zoneTitle(q.id)}
              aria-label={zoneTitle(q.id)}
              onClick={() => onSelect?.(q.id)}
            >
              <span className="quadrant-cell-title">{q.label}</span>
              <span className="quadrant-cell-hint">{q.hint}</span>
            </button>
          ))}
        </div>

        <div className="quadrant-points">
          {quadrantCells.map(({ cell, q }) => (
            <button
              type="button"
              key={cell.region_id}
              className={`quadrant-point quadrant-point--${q} ${
                selected === cell.region_id ? 'quadrant-point--selected' : ''
              }`}
              style={{ left: `${cell.presence_score}%`, bottom: `${cell.potential_score}%` }}
              title={`${cell.region_name}: потенциал ${cell.potential_score}, присутствие ${cell.presence_score}`}
              aria-label={`${cell.region_name}: ${quadrantLabel[q]}, потенциал ${cell.potential_score}, присутствие ${cell.presence_score}`}
              onClick={() => clickCell(cell.region_id)}
            >
              {quadrantIcon(q)}
            </button>
          ))}
        </div>
      </div>

      <div className="quadrant-legend" role="list" aria-label="Легенда статусов квадранта">
        {QUADRANTS.map((q) => (
          <div className="quadrant-legend-item" role="listitem" key={q.id}>
            <button
              type="button"
              className={`quadrant-chip quadrant-chip--${q.id}`}
              onClick={() => onSelect?.(q.id)}
            >
              {quadrantIcon(q.id)}
            </button>
            <div>
              <strong>{q.label}</strong>
              <div className="muted">{q.hint}</div>
            </div>
          </div>
        ))}
        <div className="quadrant-legend-note muted">
          Точки — региональные срезы: позиция = потенциал и присутствие. Клик по точке задаёт
          фильтр региона, клик по зоне — фильтр статуса.
        </div>
      </div>
    </div>
  );
}