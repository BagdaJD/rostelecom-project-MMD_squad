import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { EmptyState, ErrorState, Loading } from '@/components/states';

/** Главный дашборд: счётчики и переход в модули (ТЗ 11.3). */
export function DashboardPage() {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
  });

  if (isPending) return <Loading label="Загружаем показатели" />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <EmptyState title="Нет данных" hint="Загрузите демонстрационный набор" />;

  const metrics = [
    { label: 'Компаний в базе', value: data.companies },
    { label: 'Активных инвестпроектов', value: data.active_projects },
    { label: 'Закупок в системе', value: data.open_tenders },
    { label: 'Непрочитанных уведомлений', value: data.unread_notifications },
  ];

  return (
    <main className="app-body">
      <section className="card">
        <h2>Главный дашборд</h2>
        <div className="grid">
          {metrics.map((metric) => (
            <div key={metric.label}>
              <div className="metric">{metric.value}</div>
              <div className="muted">{metric.label}</div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
