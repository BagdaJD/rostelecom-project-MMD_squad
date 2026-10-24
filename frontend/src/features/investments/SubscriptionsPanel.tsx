/** Подписка на новые события (ТЗ 3: «система оповещений» из кейса).
 *
 * Канал — только in-app: SMTP в MVP не закладываем, чтобы не обещать то, чего не поднимаем.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { EmptyState, ErrorState, Loading } from '@/components/states';

export function SubscriptionsPanel({
  module,
  filters,
}: {
  module: 'investments' | 'tenders';
  filters: Record<string, unknown>;
}) {
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const subscriptions = useQuery({ queryKey: ['subscriptions'], queryFn: api.subscriptions });

  const create = useMutation({
    mutationFn: () => api.createSubscription(module, filters),
    onSuccess: () => {
      setMessage('Подписка создана: новые проекты появятся в уведомлениях');
      void queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
    },
    onError: (error: Error) => setMessage(`Не удалось создать: ${error.message}`),
  });

  return (
    <section className="card">
      <h2>Уведомления</h2>
      {subscriptions.isPending && <Loading label="Загружаем подписки" />}
      {subscriptions.error && (
        <ErrorState error={subscriptions.error} onRetry={() => subscriptions.refetch()} />
      )}
      {subscriptions.data && subscriptions.data.filter((s) => s.module === module).length === 0 && (
        <EmptyState
          title="Подписок нет"
          hint="Подпишитесь на текущий набор фильтров, чтобы получать новые события"
        />
      )}
      <ul className="explanation">
        {(subscriptions.data ?? [])
          .filter((s) => s.module === module)
          .map((subscription) => (
            <li key={subscription.id}>
              {JSON.stringify(subscription.filters)} · {subscription.is_active ? 'активна' : 'выключена'}
            </li>
          ))}
      </ul>
      <button type="button" onClick={() => create.mutate()} disabled={create.isPending}>
        {create.isPending ? 'Создаём…' : 'Подписаться на эти фильтры'}
      </button>
      {message && <p className="muted">{message}</p>}
    </section>
  );
}
