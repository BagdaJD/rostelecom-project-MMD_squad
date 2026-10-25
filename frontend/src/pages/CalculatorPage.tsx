import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { api, downloadBlob } from '@/api/client';
import { ErrorState, QualityBadge, Warning } from '@/components/states';
import type { DealEstimate } from '@/types/api';

const schema = z.object({
  project_type: z.string().min(2, 'Выберите тип проекта'),
  scale: z.string().min(2, 'Укажите масштаб'),
  works: z.string().optional(),
  equipment: z.string().optional(),
  software: z.string().optional(),
  urgency: z.enum(['normal', 'high', 'critical']),
  has_unique_solution: z.boolean().optional(),
});

type FormValues = z.infer<typeof schema>;

const splitList = (value?: string) =>
  (value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

/**
 * Калькулятор сделок: форма → диапазон, аналоги, факторы, разбивка.
 * Результат всегда с предупреждением об оценке и требует подтверждения сотрудником.
 */
export function CalculatorPage() {
  const [result, setResult] = useState<DealEstimate | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [pending, setPending] = useState(false);
  const [docxError, setDocxError] = useState<string | null>(null);

  const docx = useMutation({
    mutationFn: (estimateId: number) => api.exportProposal(estimateId),
    onSuccess: (blob) => {
      setDocxError(null);
      downloadBlob(blob, 'commercial-proposal.docx');
    },
    onError: (exc: Error) => setDocxError(exc.message),
  });

  const {
    register,
    handleSubmit,
    setError: setFieldError,
    formState: { errors },
  } = useForm<FormValues>({ defaultValues: { urgency: 'normal' } });

  async function onSubmit(values: FormValues) {
    // Схема zod описывает обязательные поля: без явного прогона ошибки не появятся в форме.
    const parsed = schema.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        if (issue.path[0] === 'project_type') setFieldError('project_type', { message: issue.message });
        if (issue.path[0] === 'scale') setFieldError('scale', { message: issue.message });
      }
      return;
    }
    const data = parsed.data;
    setPending(true);
    setError(null);
    // Новая оценка — новая попытка выгрузки: старая ошибка скачивания не должна висеть.
    setDocxError(null);
    try {
      setResult(
        await api.estimateDeal({
          project_type: data.project_type,
          scale: data.scale,
          works: splitList(data.works),
          equipment: splitList(data.equipment),
          software: splitList(data.software),
          urgency: data.urgency,
          has_unique_solution: Boolean(data.has_unique_solution),
        }),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc : new Error('Расчёт не выполнен'));
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="app-body">
      <form className="card" onSubmit={handleSubmit(onSubmit)}>
        <h2>Калькулятор сделок</h2>
        <div className="form-row">
          <label>
            Тип проекта
            <select {...register('project_type')}>
              <option value="">—</option>
              <option value="connectivity">Связь и каналы</option>
              <option value="it_infrastructure">ИТ-инфраструктура</option>
              <option value="video_surveillance">Видеонаблюдение</option>
              <option value="iot_asu_tp">IoT и АСУ ТП</option>
              <option value="information_security">Информационная безопасность</option>
            </select>
            {errors.project_type && <span className="warning">{errors.project_type.message}</span>}
          </label>
          <label>
            Масштаб
            <select {...register('scale')}>
              <option value="">—</option>
              <option value="small">Небольшой</option>
              <option value="medium">Средний</option>
              <option value="large">Крупный</option>
            </select>
            {errors.scale && <span className="warning">{errors.scale.message}</span>}
          </label>
          <label>
            Срочность
            <select {...register('urgency')}>
              <option value="normal">Стандартные сроки</option>
              <option value="high">Сжатые сроки</option>
              <option value="critical">Критично</option>
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>
            Виды работ (через запятую)
            <input placeholder="works_cabling, smr_volos" {...register('works')} />
          </label>
          <label>
            Оборудование
            <input placeholder="oborudovanie_server" {...register('equipment')} />
          </label>
          <label>
            ПО
            <input placeholder="software_security" {...register('software')} />
          </label>
        </div>
        <button type="submit" disabled={pending}>
          {pending ? 'Считаем…' : 'Рассчитать диапазон'}
        </button>
      </form>

      {error && <ErrorState error={error} />}

      {result && (
        <section className="card">
          <h2>Ценовая вилка</h2>
          <div className="grid">
            <div>
              <div className="metric">{Number(result.estimate.min).toLocaleString('ru-RU')} ₽</div>
              <div className="muted">Минимум</div>
            </div>
            <div>
              <div className="metric">{Number(result.estimate.optimum).toLocaleString('ru-RU')} ₽</div>
              <div className="muted">Оптимум</div>
            </div>
            <div>
              <div className="metric">{Number(result.estimate.max).toLocaleString('ru-RU')} ₽</div>
              <div className="muted">Максимум</div>
            </div>
          </div>

          <p>
            <QualityBadge quality={result.data_quality} /> метод: {result.estimator_mode} · модель{' '}
            {result.model_version}
            {result.price_period ? ` · цены периода ${result.price_period}` : ''}
          </p>

          {result.warning && <Warning>{result.warning}</Warning>}

          <h3>Аналоги</h3>
          <ul className="explanation">
            {result.comparables.map((item) => (
              <li key={item.deal_id}>
                {item.title} — {Number(item.contract_value).toLocaleString('ru-RU')} ₽ · сходство{' '}
                {item.similarity} · цена: {item.retro_price_basis}
              </li>
            ))}
            {result.comparables.length === 0 && <li>Аналоги не подобраны</li>}
          </ul>

          <h3>Поправки</h3>
          <ul className="explanation">
            {result.adjustments.map((adj) => (
              <li key={adj.factor}>
                {adj.factor}: {adj.value}
              </li>
            ))}
            {result.adjustments.length === 0 && <li>Поправки не применялись</li>}
          </ul>

          <h3>Разбивка по статьям</h3>
          <ul className="explanation">
            {result.breakdown.map((row) => (
              <li key={row.article}>
                {row.article}: {Number(row.amount).toLocaleString('ru-RU')} ₽
              </li>
            ))}
            {result.breakdown.length === 0 && <li>Разбивка не рассчитана</li>}
          </ul>

          <Warning>
            Оценку утверждает сотрудник: расчёт опирается на найденные аналоги и не заменяет
            стоимостную экспертизу.
          </Warning>

          <button
            type="button"
            disabled={docx.isPending}
            onClick={() => result && docx.mutate(result.estimate_id)}
          >
            {docx.isPending ? 'Готовим документ…' : 'Скачать КП (DOCX)'}
          </button>
          {docxError && (
            <p className="warning" role="alert">
              {docxError}
            </p>
          )}
        </section>
      )}
    </main>
  );
}
