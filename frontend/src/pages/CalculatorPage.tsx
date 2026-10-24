import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { ErrorState, Loading, Warning } from '@/components/states';
import { calculatorApi } from '@/features/calculator/api';
import '@/features/calculator/calculator.css';
import { emptyForm, type FormState, ParamsForm } from '@/features/calculator/ParamsForm';
import { ResultView } from '@/features/calculator/ResultView';
import { clearSession, loadSession, saveSession } from '@/features/calculator/session';
import type { DealDraft, DealEstimate, DealEstimateRequest } from '@/features/calculator/types';

/**
 * Калькулятор сделок (модуль 3): себестоимость по справочникам кейса → вилка
 * «минимум / оптимум» по аналогам → график маржинальности → утверждение цены → КП.
 *
 * Открывается из навигатора по ссылке /calculator?project=ID: форма заполняется
 * черновиком из инвестпроекта (тип объекта, площадь, регион, срок, заказчик).
 */
export function CalculatorPage() {
  const [params] = useSearchParams();
  const projectId = Number(params.get('project')) || null;

  const catalog = useQuery({ queryKey: ['calculator-catalog'], queryFn: calculatorApi.catalog, staleTime: 5 * 60_000 });
  const draft = useQuery({
    queryKey: ['calculator-draft', projectId],
    queryFn: () => calculatorApi.draft(projectId as number),
    enabled: projectId !== null,
  });

  // Расчёт переживает уход со страницы и обновление вкладки (см. features/calculator/session).
  const [restored] = useState(() => loadSession(projectId));
  const [form, setForm] = useState<FormState>(() => ({ ...emptyForm, ...restored?.form }));
  const [result, setResult] = useState<DealEstimate | null>(restored?.result ?? null);
  useEffect(() => {
    saveSession({ projectId, form, result });
  }, [projectId, form, result]);

  // Черновик из инвестпроекта заполняет форму один раз — дальше её правит менеджер.
  // Если по этому проекту уже есть сохранённый расчёт, черновик его не затирает.
  useEffect(() => {
    if (draft.data && !restored) setForm(fromDraft(draft.data));
  }, [draft.data, restored]);

  // Регион по умолчанию — Ростов-на-Дону: все данные кейса по Ростовской области.
  useEffect(() => {
    if (!catalog.data || form.region_id !== null || projectId) return;
    const rnd = catalog.data.regions.find((r) => r.code === 'RU-ROS-RND' || r.code === 'RU-ROS');
    if (rnd) setForm((f) => ({ ...f, region_id: rnd.id }));
  }, [catalog.data, form.region_id, projectId]);

  const estimate = useMutation({
    mutationFn: (payload: DealEstimateRequest) => calculatorApi.estimate(payload),
    onSuccess: (data, payload) => {
      setResult(data);
      // «Подобрать по площади»: состав, который подобрал сервер, переносим в форму.
      if (!payload.items?.length && data.cost) {
        const items: Record<string, number> = {};
        for (const line of data.cost.lines) if (line.code) items[line.code] = line.qty;
        setForm((f) => ({ ...f, items }));
      }
    },
  });

  const submit = (suggest: boolean) => estimate.mutate(toRequest(form, suggest));
  const startOver = () => {
    clearSession();
    setResult(null);
    setForm(draft.data ? fromDraft(draft.data) : emptyForm);
    estimate.reset();
  };
  // Утверждённая цена сохраняется и в результате — после возврата на страницу она на месте.
  const onApproved = (price: string) => setResult((r) => (r ? { ...r, approved_price: price } : r));

  if (catalog.isPending) return <main className="app-body"><Loading label="Загружаем каталог оборудования" /></main>;
  if (catalog.error)
    return (
      <main className="app-body">
        <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} />
      </main>
    );

  return (
    <main className="app-body calc">
      <header className="calc-head">
        <div>
          <h1>Калькулятор сделок</h1>
          <p className="muted">
            Диспетчеризация инженерных систем: себестоимость по справочникам кейса, вилка по похожим сделкам,
            КП в Word
          </p>
        </div>
        {result && (
          <button type="button" className="secondary" onClick={startOver}>
            Новый расчёт
          </button>
        )}
      </header>

      {draft.data && <DraftBanner draft={draft.data} />}
      {draft.error && <ErrorState error={draft.error} onRetry={() => draft.refetch()} />}

      <div className="calc-layout">
        <ParamsForm
          catalog={catalog.data}
          form={form}
          onChange={setForm}
          onSuggest={() => submit(true)}
          onSubmit={() => submit(false)}
          pending={estimate.isPending}
          normMonths={result?.cost?.norm_months ?? null}
        />
        <div className="calc-output">
          {estimate.isPending && <Loading label="Считаем себестоимость и подбираем аналоги" />}
          {estimate.error && <ErrorState error={estimate.error} onRetry={() => submit(false)} />}
          {!result && !estimate.isPending && (
            <div className="card empty-hint">
              <strong>Задайте объект и нажмите «Рассчитать цену»</strong>
              <p className="muted">
                Или откройте проект в <Link to="/navigator">инвестиционном навигаторе</Link> и нажмите «Оценить
                сделку» — форма заполнится сама.
              </p>
            </div>
          )}
          {result && !result.cost && (
            <Warning>{result.warning ?? 'Не удалось рассчитать: укажите состав или площадь'}</Warning>
          )}
          {result?.cost && <ResultView result={result} catalog={catalog.data} onApproved={onApproved} />}
        </div>
      </div>
    </main>
  );
}

function DraftBanner({ draft }: { draft: DealDraft }) {
  const e = draft.explain;
  return (
    <div className="card draft">
      <strong>Черновик из инвестпроекта «{e.project_title}»</strong>
      <ul className="explanation">
        <li>
          Тип объекта: {e.object_type_label} ({e.object_type_from})
        </li>
        <li>
          Площадь: {draft.request.area_m2?.toLocaleString('ru-RU')} м² — {e.area_from}
        </li>
        <li>Срок: {e.duration_from}</li>
        {e.company && <li>Заказчик: {e.company.name}{e.company.inn ? `, ИНН ${e.company.inn}` : ''}</li>}
      </ul>
    </div>
  );
}

function fromDraft(draft: DealDraft): FormState {
  const r = draft.request;
  const items: Record<string, number> = {};
  for (const item of r.items ?? []) items[item.code] = item.qty;
  return {
    ...emptyForm,
    object_type: r.object_type ?? emptyForm.object_type,
    area_m2: r.area_m2 ?? null,
    region_id: r.region_id ?? null,
    project_level: r.project_level ?? 'basic',
    duration_months: r.duration_months ?? null,
    payment_scheme: r.payment_scheme ?? 'capex',
    items,
    investment_project_id: r.investment_project_id ?? null,
    company_id: r.company_id ?? null,
  };
}

function toRequest(form: FormState, suggest: boolean): DealEstimateRequest {
  return {
    project_type: 'dispatching',
    object_type: form.object_type,
    area_m2: form.area_m2,
    region_id: form.region_id,
    project_level: form.project_level,
    duration_months: form.duration_months,
    payment_scheme: form.payment_scheme,
    has_unique_solution: form.has_unique_solution,
    financing_scheme: form.budget_customer ? 'budget' : null,
    systems: form.systems.length ? form.systems : null,
    items: suggest ? [] : Object.entries(form.items).map(([code, qty]) => ({ code, qty })),
    custom_items: form.custom.filter((c) => c.name && c.qty > 0),
    investment_project_id: form.investment_project_id,
    company_id: form.company_id,
  };
}
