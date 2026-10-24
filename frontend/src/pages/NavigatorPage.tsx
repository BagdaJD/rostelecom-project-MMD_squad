import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { EmptyState, ErrorState, Loading, QualityBadge } from '@/components/states';
import { MapView } from '@/features/radar/MapView';
import { SubscriptionsPanel } from '@/features/investments/SubscriptionsPanel';
import { formatDate, formatMoney } from '@/lib/format';
import { needLabel, stageLabel } from '@/types/api';

/**
 * Инвестиционный навигатор: таймлайн и карточки проектов.
 * Точка таймлайна знает project_ids — по клику фильтруются карточки и карта.
 */
function formatBudget(value: string | null): string {
  return value ? `${Number(value).toLocaleString('ru-RU')} ₽` : '—';
}

/** Человекочитаемая стоимость закупки: Decimal-строка + ₽, без потери разрядов. */
function formatTenderPrice(value: string | null): string {
  return value ? formatMoney(value) : '—';
}

export function NavigatorPage() {
  const [stage, setStage] = useState<string>('');
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<number | null>(null);

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

  const projectCard = useQuery({
    queryKey: ['project-card', selected],
    queryFn: () => api.projectCard(selected as number),
    enabled: selected !== null,
  });

  // Двусторонняя связь «таймлайн ↔ карта» (ТЗ 9): точки карты считаются из таймлайна,
  // а выбранный регион подсвечивается и фильтрует список точек.
  const regionPoints = Array.from(
    new Map(
      (timeline.data ?? []).map((point) => [
        point.region_id ?? 0,
        {
          region_id: point.region_id ?? 0,
          region_name: `Регион #${point.region_id ?? '—'}`,
          colorValue: Math.min(100, point.events_count * 25),
          // Больше событий — крупнее точка: карта читается как «где сейчас активность».
          radiusValue: Math.min(28, 14 + point.events_count * 3),
        },
      ]),
    ).values(),
  ).filter((point) => point.region_id !== 0);

  const visibleTimeline = (timeline.data ?? []).filter(
    (point) => selectedRegion === null || point.region_id === selectedRegion,
  );

  const visible = (projects.data ?? []).filter(
    (project) =>
      (selected === null || project.id === selected) &&
      (selectedRegion === null || project.region_id === selectedRegion),
  );

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
        <div className="form-row">
          {selectedRegion !== null && (
            <button type="button" onClick={() => setSelectedRegion(null)}>
              Все регионы
            </button>
          )}
        </div>
        <ul className="explanation">
          {(visibleTimeline ?? []).map((point) => (
            <li key={`${point.period}-${point.region_id}-${point.industry_id}`}>
              <strong>{point.period}</strong> · регион #{point.region_id ?? '—'} · событий:{' '}
              {point.events_count}{' '}
              {point.project_ids.map((id) => (
                <button
                  type="button"
                  key={id}
                  onClick={() => {
                    // Таймлайн → карта: выбираем и проект, и регион — точка подсвечивается.
                    setSelected(id);
                    if (point.region_id !== null) setSelectedRegion(point.region_id);
                  }}
                  style={{ marginLeft: 6 }}
                >
                  проект #{id}
                </button>
              ))}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>Карта инвестсобытий</h2>
        <MapView
          points={regionPoints}
          selectedRegion={selectedRegion}
          onSelectRegion={(regionId) => setSelectedRegion(regionId)}
          ariaLabel="Карта инвестсобытий по регионам"
        />
        <p className="muted">
          Точки — регионы с инвестсобытиями: размер — активность. Клик по точке фильтрует таймлайн
          и проекты, клик по таймлайну подсвечивает регион.
        </p>
      </section>

      {projects.isPending && <Loading label="Загружаем проекты" />}
      {projects.error && <ErrorState error={projects.error} onRetry={() => projects.refetch()} />}
      {visible.length === 0 && projects.data && (
        <EmptyState
          title={selected === null && selectedRegion === null ? 'Проектов в срезе нет' : 'Проект не попадает в текущий фильтр'}
          hint={
            selected === null && selectedRegion === null
              ? 'Ослабьте фильтр стадии'
              : 'Снимите фильтр стадии или региона — выбранный объект в него не входит'
          }
        />
      )}

      {visible.map((project) => {
        const card = projectCard.data;
        const isCard = selected === project.id && card?.id === project.id;
        return (
          <article className="card" key={project.id}>
            <h2>{project.title}</h2>
            <p className="muted">
              {stageLabel[project.stage] ?? project.stage} · старт {project.planned_start ?? '—'}{' '}
              · бюджет {formatBudget(project.estimated_budget)}
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
                {projectCard.isPending && <Loading label="Загружаем карточку проекта" />}
                {projectCard.error && (
                  <ErrorState error={projectCard.error} onRetry={() => projectCard.refetch()} />
                )}
                {isCard && (
                  <>
                    <h3>Стадии и вехи</h3>
                    <p className="muted">
                      {stageLabel[card.stage] ?? card.stage} · окно контакта:{' '}
                      {card.contact_window ?? '—'}
                    </p>
                    <p>
                      {card.description ?? 'Описание проекта не добавлено'}
                    </p>
                    {card.milestones && card.milestones.length > 0 && (
                      <ul className="explanation">
                        {card.milestones.map((milestone, index) => (
                          <li key={`${milestone.title}-${index}`}>
                            {formatDate(milestone.date)} · <strong>{milestone.title}</strong> ·{' '}
                            {milestone.status === 'done' ? 'выполнена' : milestone.status === 'planned' ? 'запланирована' : milestone.status}
                            {milestone.source_url ? (
                              <>
                                {' '}
                                ·{' '}
                                <a href={milestone.source_url} target="_blank" rel="noreferrer">
                                  источник
                                </a>
                              </>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    )}
                    {card.tenders.length > 0 && (
                      <>
                        <h3>Связанные тендеры</h3>
                        <div className="table-scroll">
                          <table className="compact">
                            <thead>
                              <tr>
                                <th>Закупка</th>
                                <th>Цена</th>
                                <th>Дедлайн</th>
                                <th>Источник</th>
                              </tr>
                            </thead>
                            <tbody>
                              {card.tenders.map((tender) => (
                                <tr key={tender.id}>
                                  <td>{tender.title}</td>
                                  <td>{tender.price ? formatTenderPrice(tender.price) : '—'}</td>
                                  <td>{tender.deadline_date ?? '—'}</td>
                                  <td>
                                    {tender.source_url ? (
                                      <a href={tender.source_url} target="_blank" rel="noreferrer">
                                        первичная запись
                                      </a>
                                    ) : (
                                      '—'
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </>
                )}
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
        );
      })}
    </main>
  );
}
