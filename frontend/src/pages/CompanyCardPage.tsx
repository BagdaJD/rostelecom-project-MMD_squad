/** Карточка компании (ТЗ 6, этап B): метрики по годам, присутствие, provenance.
 *
 * Экран открывается по клику из «Радара» и по ссылке на компанию (первичная запись).
 * Все значения, которых нет в источнике, показываются плашкой «нет данных» (ТЗ 6.8),
 * а не нулём: 0 — это значение, пропуск — отсутствие.
 */
import { useEffect, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

import { api } from '@/api/client';
import { EmptyState, ErrorState, Loading, Warning } from '@/components/states';
import { formatDate, formatShare } from '@/lib/format';
import { clientStatusLabel } from '@/styles/tokens';
import { needLabel, type CompanyMetricPoint } from '@/types/api';

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const metricLabel: Record<string, string> = {
  revenue: 'Выручка',
  profit: 'Прибыль',
  employees: 'Сотрудники',
  tax: 'Налоги',
  tenders_won: 'Выигранные закупки',
};

const metricName = (code: string): string => metricLabel[code] ?? code;

function MetricChart({ metrics }: { metrics: CompanyMetricPoint[] }) {
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = holder.current;
    if (!container) return;
    const chart = echarts.init(container);

    const years = Array.from(new Set(metrics.map((m) => m.period_year))).sort((a, b) => a - b);
    const codes = Array.from(new Set(metrics.map((m) => m.metric_code)));

    chart.clear();
    chart.setOption({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: number | null) =>
          value === null || Number.isNaN(value) ? 'нет данных' : String(value),
      },
      legend: { bottom: 0 },
      xAxis: { type: 'category', data: years },
      yAxis: { type: 'value', scale: true },
      grid: { left: 48, right: 16, top: 16, bottom: 32 },
      series: codes.map((code) => ({
        name: metricName(code),
        type: 'line',
        connectNulls: false,
        symbolSize: 6,
        data: years.map((year) => {
          const point = metrics.find((m) => m.metric_code === code && m.period_year === year);
          if (!point || point.value === null) return null;
          return Number(point.value);
        }),
      })),
    });

    const observer =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chart.resize()) : null;
    observer?.observe(container);
    return () => {
      observer?.disconnect();
      chart.dispose();
    };
  }, [metrics]);

  return (
    <div
      ref={holder}
      role="img"
      aria-label="Динамика показателей компании по годам"
      style={{ height: 280 }}
    />
  );
}

export function CompanyCardPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);

  const card = useQuery({
    queryKey: ['company', companyId],
    queryFn: () => api.companyCard(companyId),
    enabled: Number.isInteger(companyId) && companyId > 0,
  });

  if (card.isPending) return <Loading label="Загружаем карточку компании" />;
  if (card.error) return <ErrorState error={card.error} onRetry={() => card.refetch()} />;
  if (!card.data) return <EmptyState title="Компания не найдена" hint="Откройте карточку из списка" />;

  const company = card.data;
  const hasMetrics = company.metrics.length > 0;

  return (
    <main className="app-body">
      <p className="muted">
        <Link to="/radar">← Радар присутствия</Link>
      </p>

      <section className="card">
        <h2>{company.name}</h2>
        <table className="compact">
          <tbody>
            <tr>
              <th>ИНН</th>
              <td>{company.inn ?? '—'}</td>
              <th>ОГРН</th>
              <td>{company.ogrn ?? '—'}</td>
              <th>Статус</th>
              <td>
                <span className={`badge badge--${company.client_status}`}>
                  {clientStatusLabel[company.client_status] ?? company.client_status}
                </span>
              </td>
            </tr>
            <tr>
              <th>Выручка</th>
              <td>
                {company.revenue_latest
                  ? `${Number(company.revenue_latest).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`
                  : '—'}
                {company.revenue_latest && company.revenue_year ? (
                  <span className="muted"> ({company.revenue_year})</span>
                ) : null}
              </td>
              <th>Динамика</th>
              <td>
                {company.revenue_yoy === null
                  ? '—'
                  : `${company.revenue_yoy > 0 ? '+' : ''}${company.revenue_yoy} %`}
              </td>
              <th>Сотрудники</th>
              <td>{company.employee_count === null ? '—' : company.employee_count}</td>
            </tr>
          </tbody>
        </table>

        {hasMetrics ? (
          <>
            <h3>Метрики по годам</h3>
            {metricsByYear(company.metrics).map(([year, points]) => (
              <p className="muted" key={year}>
                {year}:{' '}
                {points.map((point, index) => (
                  <span key={`${point.metric_code}-${index}`}>
                    {index > 0 ? ' · ' : ''}
                    {metricName(point.metric_code)}:{' '}
                    {point.value === null ? 'нет данных' : Number(point.value).toLocaleString('ru-RU')}
                  </span>
                ))}
              </p>
            ))}
            <MetricChart metrics={company.metrics} />
          </>
        ) : (
          <EmptyState title="Метрик нет" hint="Источник не отдал временной ряд" />
        )}
      </section>

      <section className="card">
        <h3>Присутствие услуг в регионе</h3>
        {company.presence.length === 0 && (
          <EmptyState title="Присутствие не подтверждено" hint="Записей о выполненных работах нет" />
        )}
        <div className="table-scroll">
          <table className="compact">
            <thead>
              <tr>
                <th>Услуга</th>
                <th>Муниципалитет</th>
                <th>Покрытие</th>
                <th>Контрактов</th>
                <th>По состоянию на</th>
              </tr>
            </thead>
            <tbody>
              {company.presence.map((row, index) => (
                <tr key={`${row.region_id}-${row.municipality ?? '—'}-${index}`}>
                  <td>{needLabel[row.service_type] ?? row.service_type}</td>
                  <td>{row.municipality ?? '—'}</td>
                  <td>
                    {row.coverage_percent === null
                      ? '—'
                      : formatShare(Number(row.coverage_percent) / 100)}
                    {row.is_synthetic ? <span className="muted"> (синтетика)</span> : null}
                  </td>
                  <td>{row.contracts_count === null ? '—' : row.contracts_count}</td>
                  <td>{formatDate(row.as_of_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Warning>
          Синтетические записи помечены: это демонстрационные данные, а не подтверждённое
          присутствие.
        </Warning>
      </section>

      <section className="card">
        <h3>Как получено это значение (provenance)</h3>
        {company.provenance.length === 0 && (
          <EmptyState title="Источники не зафиксированы" hint="Запись создана без источника" />
        )}
        {company.provenance.map((item, index) => (
          <p className="muted" key={`${item.source}-${index}`}>
            Источник: <strong>{item.source}</strong> · получено {formatDate(item.fetched_at)}
            {item.external_id ? ` · внешний id ${item.external_id}` : ''}
            {item.license_note ? ` · ${item.license_note}` : ''}
            {item.source_url ? (
              <>
                {' · '}
                <a href={item.source_url} target="_blank" rel="noreferrer">
                  первичная запись
                </a>
              </>
            ) : null}
          </p>
        ))}
      </section>

      {company.demand_signals.length > 0 && (
        <section className="card">
          <h3>Признаки спроса</h3>
          <ul className="explanation">
            {company.demand_signals.map((signal) => (
              <li key={signal}>{signal}</li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

/** Сгруппированные по годам точки: таблица-дубликат графика для доступности. */
function metricsByYear(metrics: CompanyMetricPoint[]): [number, CompanyMetricPoint[]][] {
  const years = Array.from(new Set(metrics.map((m) => m.period_year))).sort((a, b) => a - b);
  return years.map((year) => [year, metrics.filter((m) => m.period_year === year)] as [number, CompanyMetricPoint[]]);
}