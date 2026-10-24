import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { EmptyState, ErrorState, Loading, QualityBadge } from '@/components/states';
import { SubscriptionsPanel } from '@/features/investments/SubscriptionsPanel';
import { needLabel, stageLabel } from '@/types/api';

/**
 * Инвестиционный навигатор: таймлайн и карточки проектов.
 * Точка таймлайна знает project_ids — по клику фильтруются карточки и карта.
 */
export function NavigatorPage() {
  const [stage, setStage] = useState<string>('');
  const [selected, setSelected] = useState<number | null>(null);

  const projects = useQuery({
    queryKey: ['projects', stage],
    queryFn: () => api.projects({ stage: stage || null }),
  });
  const timeline = useQuery({ queryKey: ['timeline'], queryFn: () => api.timeline({ period: 'month' }) });

  const needs = useQuery({
    queryKey: ['needs', selected],
    queryFn: () => api.needs(selected as number),
    enabled: selected !== null,
  });

  const visible = (projects.data ?? []).filter((project) => selected === null || project.id === selected);

  return (
    <main className="app-body">
      <section className="card">
        <h2>Инвестиционный навигатор</h2>
        <div className="form-row">
          <label>
            Стадия
            <select value={stage} onChange={(event) => setStage(event.target.value)}>
              <option value="">Все стадии</option>
              {Object.entries(stageLabel).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {selected !== null && (
            <button type="button" onClick={() => setSelected(null)}>
              Показать все проекты
            </button>
          )}
        </div>
      </section>

      <SubscriptionsPanel module="investments" filters={{ stage: stage || null }} />

      <section className="card">
        <h2>Таймлайн инвестсобытий</h2>
        {timeline.isPending && <Loading label="Строим таймлайн" />}
        {timeline.error && <ErrorState error={timeline.error} onRetry={() => timeline.refetch()} />}
        {timeline.data && timeline.data.length === 0 && (
          <EmptyState title="Событий нет" hint="Загрузите демонстрационный набор" />
        )}
        <ul className="explanation">
          {(timeline.data ?? []).map((point) => (
            <li key={`${point.period}-${point.region_id}-${point.industry_id}`}>
              <strong>{point.period}</strong> · событий: {point.events_count}{' '}
              {point.project_ids.map((id) => (
                <button
                  type="button"
                  key={id}
                  onClick={() => setSelected(id)}
                  style={{ marginLeft: 6 }}
                >
                  проект #{id}
                </button>
              ))}
            </li>
          ))}
        </ul>
      </section>

      {projects.isPending && <Loading label="Загружаем проекты" />}
      {projects.error && <ErrorState error={projects.error} onRetry={() => projects.refetch()} />}
      {projects.data && visible.length === 0 && (
        <EmptyState
          title={selected === null ? 'Проектов в срезе нет' : 'Проект не попадает в текущий фильтр'}
          hint={
            selected === null
              ? 'Ослабьте фильтр стадии'
              : 'Снимите фильтр стадии — выбранный проект в неё не входит'
          }
        />
      )}

      {visible.map((project) => (
        <article className="card" key={project.id}>
          <h2>{project.title}</h2>
          <p className="muted">
            {stageLabel[project.stage] ?? project.stage} · старт {project.planned_start ?? '—'} · бюджет{' '}
            {project.estimated_budget ?? '—'} ₽
          </p>
          {project.source_url && (
            <p className="muted">
              Источник:{' '}
              <a href={project.source_url} target="_blank" rel="noreferrer">
                первичная запись
              </a>
            </p>
          )}

          {selected === project.id && (
            <>
              <h3>Вероятные потребности</h3>
              {needs.isPending && <Loading label="Определяем потребности" />}
              {needs.data?.map((need) => (
                <p key={need.need_category}>
                  <strong>{needLabel[need.need_category] ?? need.need_category}</strong>{' '}
                  {need.probability !== null ? `· ${(need.probability * 100).toFixed(0)} %` : ''}{' '}
                  <QualityBadge quality="limited" />
                  <br />
                  <span className="muted">
                    Доказательство: {need.evidence ?? 'не найдено в описании'} · правило{' '}
                    {need.rule_id ?? '—'} · модель {need.model_version}
                  </span>
                </p>
              ))}
              {needs.data && needs.data.length === 0 && (
                <EmptyState title="Потребности не определены" hint="В описании нет маркеров" />
              )}
            </>
          )}
        </article>
      ))}
    </main>
  );
}
