import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api, downloadBlob } from '@/api/client';
import { EmptyState, ErrorState, Loading, Warning } from '@/components/states';
import { MapView } from '@/features/radar/MapView';
import { clientStatusLabel } from '@/styles/tokens';
import type { Company } from '@/types/api';

type Filters = { region_id: number | null; industry_group: string | null };

/**
 * Радар присутствия: таблица и объяснение «белых пятен» синхронизированы с фильтрами.
 * Карточный слой MapLibre подключается в `features/radar/MapView` — карта и таблица
 * читают один и тот же запрос, чтобы не расходиться (ТЗ 11.3).
 */
export function RadarPage() {
  const [filters, setFilters] = useState<Filters>({ region_id: null, industry_group: null });

  const cells = useQuery({
    queryKey: ['heatmap', filters],
    queryFn: () => api.heatmap(filters),
  });
  const spaces = useQuery({
    queryKey: ['white-spaces', filters],
    queryFn: () => api.whiteSpaces(filters),
  });
  const companies = useQuery({
    queryKey: ['companies', filters],
    queryFn: () => api.companies({ region_id: filters.region_id }),
  });

  const regionOptions = Array.from(
    new Map((cells.data ?? []).map((c) => [c.region_id, c.region_name])).entries(),
  );

  async function exportCsv() {
    const blob = await api.exportCsv('companies', { region_id: filters.region_id }, 'general');
    downloadBlob(blob, 'companies.csv');
  }

  return (
    <main className="app-body">
      <section className="card">
        <h2>Радар присутствия</h2>
        <div className="form-row">
          <label>
            Регион
            <select
              value={filters.region_id ?? ''}
              onChange={(event) =>
                setFilters({ ...filters, region_id: event.target.value ? Number(event.target.value) : null })
              }
            >
              <option value="">Все регионы</option>
              {regionOptions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Отрасль
            <input
              placeholder="ТЭК, Торговля, АПК…"
              value={filters.industry_group ?? ''}
              onChange={(event) => setFilters({ ...filters, industry_group: event.target.value || null })}
            />
          </label>
          <button type="button" onClick={exportCsv}>
            Экспорт CSV
          </button>
        </div>
        <p className="muted">
          Фильтры сохраняются в URL-состояании страницы; карта и таблица читают один запрос.
        </p>
      </section>

      {spaces.isPending && <Loading label="Ищем белые пятна" />}
      {spaces.error && <ErrorState error={spaces.error} onRetry={() => spaces.refetch()} />}

      {(cells.data?.length ?? 0) > 0 && (
        <section className="card">
          <h2>Карта потенциала</h2>
          <MapView
            cells={cells.data ?? []}
            onSelectRegion={(regionId) => setFilters({ ...filters, region_id: regionId })}
          />
          <p className="muted">
            Цвет — потенциал среза, радиус — присутствие: чем больше точка при ярком цвете, тем
            отчётливее белое пятно. Клик по точке задаёт фильтр региона.
          </p>
        </section>
      )}

      {spaces.data && spaces.data.length === 0 && (
        <EmptyState title="Белых пятен не найдено" hint="Ослабьте фильтры или пересчитайте скоринг" />
      )}

      {(spaces.data ?? []).map((space) => (
        <section className="card" key={`${space.region_id}-${space.industry_group}`}>
          <h2>
            {space.region_name} · {space.industry_group}
          </h2>
          <p>
            Потенциал <strong>{space.potential_score}</strong> · Присутствие{' '}
            <strong>{space.presence_score}</strong>
          </p>
          <ul className="explanation">
            {space.explanation.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <Warning>
            Расчёт выполнен экспертной эвристикой: это приоритет работы, а не доказанная вероятность
            сделки.
          </Warning>
        </section>
      ))}

      <section className="card table-scroll">
        <h2>Компании в срезе</h2>
        {companies.isPending && <Loading label="Загружаем компании" />}
        {companies.error && <ErrorState error={companies.error} onRetry={() => companies.refetch()} />}
        {companies.data && companies.data.length === 0 && (
          <EmptyState title="Нет компаний" hint="Ослабьте фильтры" />
        )}
        {companies.data && companies.data.length > 0 && <CompanyTable rows={companies.data} />}
      </section>
    </main>
  );
}

function CompanyTable({ rows }: { rows: Company[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Компания</th>
          <th>ИНН</th>
          <th>Статус</th>
          <th>Выручка, млн ₽</th>
          <th>Динамика</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.name}</td>
            <td>{row.inn ?? '—'}</td>
            <td>
              <span className={`badge badge--${row.client_status}`}>
                {clientStatusLabel[row.client_status] ?? row.client_status}
              </span>
            </td>
            <td>
              {row.revenue_latest ?? '—'}
              {row.revenue_year ? <span className="muted"> ({row.revenue_year})</span> : null}
            </td>
            <td>{row.revenue_yoy === null ? '—' : `${row.revenue_yoy > 0 ? '+' : ''}${row.revenue_yoy} %`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
