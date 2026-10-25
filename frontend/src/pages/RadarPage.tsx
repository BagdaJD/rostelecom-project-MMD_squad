import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api, downloadBlob } from '@/api/client';
import { DataGap, EmptyState, ErrorState, Loading, Warning } from '@/components/states';
import { DataTable, type DataTableColumn } from '@/components/DataTable';
import { useGlobalRegion } from '@/components/GlobalFilter';
import { formatNumber } from '@/lib/format';
import { MapView } from '@/features/radar/MapView';
import { QuadrantChart, quadrantLabel, quadrantOf, type Quadrant } from '@/features/radar/QuadrantChart';
import { clientStatusLabel } from '@/styles/tokens';
import { Link } from 'react-router-dom';
import type { Company } from '@/types/api';

type Filters = { region_id: number | null; industry_group: string | null; quadrant: Quadrant | null };

function readFilters(params: URLSearchParams): Filters {
  const raw = Number(params.get('region_id'));
  const quadrantRaw = params.get('quadrant');
  const quadrant: Quadrant | null =
    quadrantRaw === 'white' || quadrantRaw === 'strong' || quadrantRaw === 'stable' || quadrantRaw === 'weak'
      ? quadrantRaw
      : null;
  return {
    region_id: Number.isInteger(raw) && raw > 0 ? raw : null,
    industry_group: params.get('industry_group') || null,
    quadrant,
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
  const globalRegion = useGlobalRegion();
  const [exportError, setExportError] = useState<string | null>(null);
  const [openCompany, setOpenCompany] = useState<number | null>(null);

  // Глобальный фильтр шапки — fallback: URL-фильтр страницы переносим по ссылке,
  // а без него срез задаёт выбор в шапке (ТЗ 11.1).
  const effectiveRegion = filters.region_id ?? globalRegion;

  // Фильтры живут в URL: ссылку на срез можно переслать коллеге, а «назад» работает.
  function patchFilters(patch: Partial<Filters>) {
    const next = { ...filters, ...patch };
    const search = new URLSearchParams();
    if (next.region_id !== null) search.set('region_id', String(next.region_id));
    if (next.industry_group) search.set('industry_group', next.industry_group);
    if (next.quadrant) search.set('quadrant', next.quadrant);
    setParams(search, { replace: true });
  }

  const cells = useQuery({
    queryKey: ['heatmap', { region_id: effectiveRegion, industry_group: filters.industry_group }],
    queryFn: () => api.heatmap({ region_id: effectiveRegion, industry_group: filters.industry_group }),
  });
  const spaces = useQuery({
    queryKey: ['white-spaces', { region_id: effectiveRegion, industry_group: filters.industry_group }],
    queryFn: () => api.whiteSpaces({ region_id: effectiveRegion, industry_group: filters.industry_group }),
  });
  const companies = useQuery({
    queryKey: ['companies', { region_id: effectiveRegion }],
    queryFn: () => api.companies({ region_id: effectiveRegion }),
  });
  // Полный список для селектора: фильтрованные ячейки показывали бы один регион,
  // и переключить срез было бы невозможно.
  const regions = useQuery({ queryKey: ['regions'], queryFn: api.regions });

  const regionOptions = Array.from(
    new Map((regions.data ?? []).map((item) => [item.id, item.name])).entries(),
  );

  /** Строки компаний, попадающие в выбранный квадрант по региональному срезу. */
  const companiesInQuadrant = (companies.data ?? []).filter((company) => {
    if (!filters.quadrant) return true;
    const cell = (cells.data ?? []).find((item) => item.region_id === company.region_id);
    if (!cell) return false;
    return (
      quadrantOf(cell.potential_score, cell.presence_score, 50) === filters.quadrant
    );
  });

  async function exportCsv(mode: 'general' | 'crm') {
    setExportError(null);
    try {
      // Текущий набор фильтров: регион, отрасль и квадрант — как в URL (ТЗ 12).
      const blob = await api.exportCsv('companies', { ...filters, region_id: effectiveRegion }, mode);
      downloadBlob(blob, mode === 'crm' ? 'companies-crm.csv' : 'companies.csv');
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
              value={effectiveRegion ?? ''}
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
          {filters.quadrant && (
            <label>
              Статус квадранта
              <select
                value={filters.quadrant}
                onChange={(event) =>
                  patchFilters({ quadrant: event.target.value ? (event.target.value as Quadrant) : null })
                }
              >
                <option value="">Все статусы</option>
                {(['white', 'strong', 'stable', 'weak'] as Quadrant[]).map((q) => (
                  <option key={q} value={q}>
                    {quadrantLabel[q]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="button" onClick={() => exportCsv('general')}>
            Экспорт CSV
          </button>
          <button type="button" onClick={() => exportCsv('crm')}>
            Экспорт CSV (CRM)
          </button>
        </div>
        {exportError && (
          <p className="warning" role="alert">
            {exportError}
          </p>
        )}
        <p className="muted">
          Фильтры сохраняются в URL-состояании страницы; карта, квадрант и таблица читают один
          запрос.
        </p>
      </section>

      {spaces.isPending && <Loading label="Ищем белые пятна" />}
      {spaces.error && <ErrorState error={spaces.error} onRetry={() => spaces.refetch()} />}

      {(cells.data?.length ?? 0) > 0 && (
        <section className="card">
          <h2>Карта потенциала</h2>
          <MapView
            points={(cells.data ?? []).map((cell) => ({
              region_id: cell.region_id,
              region_name: cell.region_name,
              longitude: cell.longitude,
              latitude: cell.latitude,
              colorValue: cell.potential_score,
              radiusValue: 100 - cell.presence_score,
            }))}
            selectedRegion={filters.region_id ?? globalRegion}
            onSelectRegion={(regionId) => patchFilters({ region_id: regionId })}
            ariaLabel="Тепловая карта потенциала регионов"
          />
          <p className="muted">
            Цвет — потенциал среза, радиус — присутствие: чем больше точка при ярком цвете, тем
            отчётливее белое пятно. Клик по точке задаёт фильтр региона.
          </p>
        </section>
      )}

      {(cells.data?.length ?? 0) > 0 && (
        <section className="card">
          <h2>Квадрант «потенциал × присутствие»</h2>
          <QuadrantChart
            cells={cells.data ?? []}
            selected={filters.region_id ?? globalRegion}
            onSelect={(q) => patchFilters({ quadrant: q })}
            onSelectCell={(regionId) => patchFilters({ region_id: regionId })}
          />
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
        {companies.data && companiesInQuadrant.length === 0 && (
          <EmptyState
            title={filters.quadrant ? 'Нет компаний в этом квадранте' : 'Нет компаний'}
            hint={filters.quadrant ? 'Ослабьте фильтр статуса' : 'Ослабьте фильтры'}
          />
        )}
        {companies.data && companiesInQuadrant.length > 0 && (
          <CompanyTable rows={companiesInQuadrant} onOpen={setOpenCompany} />
        )}
      </section>

      {openCompany !== null && (
        <section className="card">
          <h3>Карточка компании</h3>
          <CompanyCardPanel companyId={openCompany} onClose={() => setOpenCompany(null)} />
        </section>
      )}
    </main>
  );
}

function CompanyCardPanel({ companyId, onClose }: { companyId: number; onClose: () => void }) {
  const card = useQuery({
    queryKey: ['company', companyId],
    queryFn: () => api.companyCard(companyId),
  });

  if (card.isPending) return <Loading label="Загружаем карточку компании" />;
  if (card.error) return <ErrorState error={card.error} onRetry={() => card.refetch()} />;
  if (!card.data) return <EmptyState title="Компания не найдена" />;

  const company = card.data;
  return (
    <>
      <p className="muted">
        <button type="button" onClick={onClose}>
          Закрыть
        </button>{' '}
        <Link to={`/companies/${company.id}`}>Открыть карточку целиком →</Link>
      </p>
      <p>
        ИНН {company.inn ?? <DataGap what="ИНН" />} · ОГРН{' '}
        {company.ogrn ?? <DataGap what="ОГРН" />} · сотрудники{' '}
        {company.employee_count ?? <DataGap what="Сотрудники" />}
      </p>
      <h4>Метрики по годам</h4>
      {company.metrics.length === 0 && <EmptyState title="Метрик нет" />}
      <ul className="explanation">
        {company.metrics.map((metric) => (
          <li key={`${metric.metric_code}-${metric.period_year}`}>
            {metric.period_year}: {metric.metric_code} —{' '}
            {metric.value === null ? (
              <DataGap what="Значение" />
            ) : (
              formatNumber(metric.value)
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function CompanyTable({ rows, onOpen }: { rows: Company[]; onOpen: (id: number) => void }) {
  const columns: DataTableColumn<Company>[] = [
    {
      key: 'name',
      header: 'Компания',
      sortValue: (row) => row.name,
      render: (row) => row.name,
    },
    {
      key: 'inn',
      header: 'ИНН',
      sortValue: (row) => row.inn,
      render: (row) => row.inn ?? '—',
    },
    {
      key: 'status',
      header: 'Статус',
      sortValue: (row) => row.client_status,
      render: (row) => (
        <span className={`badge badge--${row.client_status}`}>
          {clientStatusLabel[row.client_status] ?? row.client_status}
        </span>
      ),
    },
    {
      key: 'revenue',
      header: 'Выручка, млн ₽',
      align: 'right',
      sortValue: (row) => (row.revenue_latest ? Number(row.revenue_latest) : null),
      render: (row) =>
        row.revenue_latest ? (
          <>
            {row.revenue_latest}
            {row.revenue_year ? <span className="muted"> ({row.revenue_year})</span> : null}
          </>
        ) : (
          <DataGap what="Выручка" />
        ),
    },
    {
      key: 'dynamics',
      header: 'Динамика',
      align: 'right',
      sortValue: (row) => row.revenue_yoy,
      render: (row) =>
        row.revenue_yoy === null ? (
          <DataGap what="Динамика" />
        ) : (
          `${row.revenue_yoy > 0 ? '+' : ''}${row.revenue_yoy} %`
        ),
    },
    {
      key: 'open',
      header: '',
      render: (row) => (
        <button type="button" onClick={() => onOpen(row.id)}>
          Карточка
        </button>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      pageSize={5}
      emptyLabel="Нет компаний в срезе"
    />
  );
}
