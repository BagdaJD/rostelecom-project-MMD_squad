import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api, downloadBlob } from '@/api/client';
import { EmptyState, ErrorState, Loading, Warning } from '@/components/states';
import { MapView } from '@/features/radar/MapView';
import { clientStatusLabel } from '@/styles/tokens';
import type { Company } from '@/types/api';

type Filters = { region_id: number | null; industry_group: string | null };

function readFilters(params: URLSearchParams): Filters {
  const raw = Number(params.get('region_id'));
  return {
    region_id: Number.isInteger(raw) && raw > 0 ? raw : null,
    industry_group: params.get('industry_group') || null,
  };
}

/**
 * Радар присутствия: таблица и объяснение «белых пятен» синхронизированы с фильтрами.
 * Карточный слой MapLibre подключается в `features/radar/MapView` — карта и таблица
 * читают один и тот же запрос, чтобы не расходиться (ТЗ 11.3).
 */
export function RadarPage() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const [exportError, setExportError] = useState<string | null>(null);

  // Фильтры живут в URL: ссылку на срез можно переслать коллеге, а «назад» работает.
  function patchFilters(patch: Partial<Filters>) {
    const next = { ...filters, ...patch };
    const search = new URLSearchParams();
    if (next.region_id !== null) search.set('region_id', String(next.region_id));
    if (next.industry_group) search.set('industry_group', next.industry_group);
    setParams(search, { replace: true });
  }

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
    setExportError(null);
    try {
      const blob = await api.exportCsv('companies', { region_id: filters.region_id }, 'general');
      downloadBlob(blob, 'companies.csv');
    } catch (exc) {
      setExportError(exc instanceof Error ? exc.message : 'Экспорт не выполнен');
    }
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
                patchFilters({ region_id: event.target.value ? Number(event.target.value) : null })
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
              onChange={(event) => patchFilters({ industry_group: event.target.value || null })}
            />
          </label>
          <button type="button" onClick={exportCsv}>
            Экспорт CSV
          </button>
        </div>
        {exportError && (
          <p className="warning" role="alert">
            {exportError}
          </p>
        )}
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
            onSelectRegion={(regionId) => patchFilters({ region_id: regionId })}
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
