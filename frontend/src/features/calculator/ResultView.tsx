/** Результат калькулятора: вилка, ползунок цены, графики, оплата, утверждение, экспорт. */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { QualityBadge, Warning } from '@/components/states';

import { calculatorApi, type ExportKind, saveFile } from './api';

import { AnalogsChart, MarginChart, StructureChart } from './charts';
import { WinFactors } from './WinFactors';
import { FACTOR_LABELS, paymentOptions, pct, pointAt, rub, thousands } from './pricing';
import type { DealCatalog, DealEstimate } from './types';

type Props = { result: DealEstimate; catalog: DealCatalog; onApproved?: (price: string) => void };

const EXPORTS: Record<ExportKind, { done: string }> = {
  kp: { done: 'КП для заказчика скачано (Word)' },
  'kp-internal': { done: 'КП с обоснованием цены скачано (Word) — только для внутреннего пользования' },
  csv: { done: 'Расчёт скачан — файл открывается в Excel' },
  crm: { done: 'Файл для импорта в CRM скачан (формат — docs/calculator.md)' },
  analogs: { done: 'Аналоги скачаны — файл открывается в Excel' },
};

/** Текст ошибки API: FastAPI отдаёт {"detail": ...}. */
function errorText(e: Error): string {
  try {
    const detail = JSON.parse(e.message)?.detail;
    if (typeof detail === 'string') return detail;
  } catch {
    // не JSON — показываем как есть
  }
  return e.message || 'Не удалось скачать файл';
}

export function ResultView({ result, catalog, onApproved }: Props) {
  const cost = result.cost!;
  const min = Number(result.estimate.min);
  const opt = Number(result.estimate.optimum);
  const max = Number(result.estimate.max);
  const lo = result.curve[0]?.price ?? min * 0.9;
  const hi = result.curve[result.curve.length - 1]?.price ?? max * 1.1;

  const savedApproved = result.approved_price ? Number(result.approved_price) : null;
  // После возврата на страницу ползунок стоит на утверждённой цене, если она есть.
  const [price, setPrice] = useState(savedApproved ?? opt);
  const [approved, setApproved] = useState<number | null>(savedApproved);
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);
  // Новый расчёт — сбрасываем ползунок и сообщения; утверждение текущего их не трогает.
  useEffect(() => {
    setPrice(savedApproved ?? opt);
    setApproved(savedApproved);
    setNotice(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.estimate_id]);

  const at = useMemo(() => pointAt(result.curve, cost.total, price), [result.curve, cost.total, price]);
  const payments = useMemo(() => paymentOptions(price, catalog.settings), [price, catalog.settings]);
  const kpPrice = approved ?? opt;
  const pos = (p: number) => `${(((p - lo) / (hi - lo)) * 100).toFixed(2)}%`;
  const near = (a: number, b: number) => Math.abs(a - b) / (hi - lo) < 0.07;
  const realCount = result.comparables.filter((c) => c.retro_price_basis === 'contract').length;
  const demoCount = result.comparables.filter((c) => c.retro_price_basis === 'synthetic').length;

  const approve = useMutation({
    mutationFn: () => calculatorApi.approve(result.estimate_id, Math.round(price)),
    onSuccess: (data) => {
      setApproved(Number(data.approved_price));
      onApproved?.(data.approved_price);
      setNotice({ text: `Цена ${rub(data.approved_price)} утверждена — она попадёт в КП` });
    },
    onError: (e: Error) =>
      setNotice({ text: e.message.includes('себестоимост') ? 'Цена ниже себестоимости' : errorText(e), error: true }),
  });
  const download = useMutation({
    mutationFn: async (kind: ExportKind) => {
      const { blob, filename } = await calculatorApi.download(result.estimate_id, kind);
      saveFile(blob, filename);
    },
    onMutate: () => setNotice(null),
    onSuccess: (_data, kind) => setNotice({ text: EXPORTS[kind].done }),
    onError: (e: Error) => setNotice({ text: errorText(e), error: true }),
  });

  const factors = cost.factors.filter((f) => f.factor !== 'complexity_mode');

  return (
    <section className="calc-result" aria-live="polite">
      <div className="chips">
        {factors.map((f) => (
          <span key={f.factor} className="chip" title={`${f.note} (${f.source})`}>
            {FACTOR_LABELS[f.factor] ?? f.factor} ×{f.value.toLocaleString('ru-RU')}
          </span>
        ))}
        <span className="chip">{cost.points} приборов, {cost.systems.length} систем</span>
        <span className="chip ok">
          <QualityBadge quality={result.data_quality} /> {result.comparables.length} аналогов
        </span>
        {realCount > 0 && <span className="chip ok">Реальных контрактов ЕИС: {realCount}</span>}
        {demoCount > 0 && (
          <span className="chip demo">
            {realCount > 0 ? `Демо-сделок: ${demoCount}` : 'Демо: аналоги синтетические'}
          </span>
        )}
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="k">Себестоимость</div>
          <div className="v">{rub(cost.total)}</div>
          <div className="s">оборудование и работы — наша цена</div>
        </div>
        <div className="tile">
          <div className="k">Минимум</div>
          <div className="v">{rub(min)}</div>
          <div className="s">маржа {pct(result.margin?.min)}</div>
        </div>
        <div className="tile hero">
          <div className="k">Оптимум</div>
          <div className="v">{rub(opt)}</div>
          <div className="s">
            маржа {pct(result.margin?.optimum)}
            {result.win_probability !== null && ` · шанс ${Math.round(result.win_probability)}%`}
          </div>
        </div>
        <div className="tile">
          <div className="k">Максимум</div>
          <div className="v">{rub(max)}</div>
          <div className="s">маржа {pct(result.margin?.max)}</div>
        </div>
      </div>

      <div className="card slider-card">
        <div>
          <h2>Цена в КП</h2>
          <p className="muted">Двигайте — маржа и шанс выиграть пересчитываются сразу</p>
          <div className="track-wrap">
            <div className="band" style={{ left: pos(min), width: `calc(${pos(max)} - ${pos(min)})` }} />
            <input
              type="range"
              min={Math.round(lo)}
              max={Math.round(hi)}
              step={1000}
              value={Math.round(price)}
              aria-label="Цена в КП"
              aria-valuetext={rub(price)}
              onChange={(e) => setPrice(Number(e.target.value))}
            />
            {/* Близкие отметки не подписываем поверх друг друга — оставляем «опт». */}
            {!near(min, opt) && <span className="tick" style={{ left: pos(min) }}>мин</span>}
            <span className="tick strong" style={{ left: pos(opt) }}>опт</span>
            {!near(max, opt) && <span className="tick" style={{ left: pos(max) }}>макс</span>}
          </div>
        </div>
        <div className="readout">
          <div>
            <b>{rub(price)}</b>
            <span>цена</span>
          </div>
          <div>
            <b>{pct(at.marginPct)}</b>
            <span>маржа</span>
          </div>
          <div>
            <b>{at.winPct === null ? '—' : `${Math.round(at.winPct)}%`}</b>
            <span>шанс выиграть</span>
          </div>
          <div>
            <b>{at.expectedProfit === null ? '—' : rub(at.expectedProfit)}</b>
            <span>ожидаемая прибыль</span>
          </div>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Маржинальность</h2>
          <p className="muted">
            Выше цена — больше маржа и ниже шанс выиграть. Оптимум — где «прибыль × шанс» максимальны.
          </p>
          <MarginChart curve={result.curve} cost={cost.total} min={min} optimum={opt} max={max} selected={price} />
        </div>
        <div className="card">
          <h2>Из чего складывается цена</h2>
          <p className="muted">При цене {thousands(price)} ₽</p>
          <StructureChart breakdown={cost.breakdown} cost={cost.total} price={price} />
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Сравнение с аналогами</h2>
          <p className="muted">
            Похожие сделки. Сравниваем наценку над себестоимостью, а не цену — так объекты разного размера
            сопоставимы.
          </p>
          <AnalogsChart
            comparables={result.comparables}
            cost={cost.total}
            min={min}
            optimum={opt}
            max={max}
            selected={price}
          />
          <details>
            <summary className="muted">Показать таблицей</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Сделка</th>
                    <th>Сходство</th>
                    <th>Цена</th>
                    <th>Наценка</th>
                    <th>Итог</th>
                    <th>Источник</th>
                  </tr>
                </thead>
                <tbody>
                  {result.comparables.map((c) => (
                    <tr key={c.deal_id}>
                      <td>{c.title}</td>
                      <td>{Math.round(c.similarity * 100)}%</td>
                      <td>{rub(c.contract_value)}</td>
                      <td>{c.price_index ? `×${c.price_index.toFixed(2).replace('.', ',')}` : '—'}</td>
                      <td>{c.outcome === 'won' ? 'выиграли' : c.outcome === 'lost' ? 'проиграли' : '—'}</td>
                      <td>{c.retro_price_basis === 'contract' ? 'контракт ЕИС' : 'демо'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
        <div className="card pay">
          <h2>Схема оплаты</h2>
          <p className="muted">
            При цене {thousands(price)} ₽ · ставка {Math.round(catalog.settings.annual_rate * 100)}% годовых (настройка)
          </p>
          {payments.map((p) => (
            <div key={p.scheme} className={p.scheme === result.payment_scheme ? 'pay-row on' : 'pay-row'}>
              <div>
                {p.label}
                <small>
                  {p.scheme === 'capex'
                    ? 'одним платежом или по этапам'
                    : `итого ${rub(p.total)}${p.service_fee ? `, вкл. обслуживание ${rub(p.service_fee)}/мес` : ''}`}
                </small>
              </div>
              <b>
                {rub(p.monthly)}
                {p.scheme !== 'capex' && '/мес'}
              </b>
            </div>
          ))}
        </div>
      </div>

      <WinFactors model={result.win_model} />

      {result.warnings.length > 0 && (
        <Warning>
          {result.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </Warning>
      )}

      <div className="actions">
        <button type="button" className="accent" onClick={() => approve.mutate()} disabled={approve.isPending}>
          Утвердить цену {thousands(price)}
        </button>
        <span className="note">
          В КП попадёт {rub(kpPrice)}
          {approved ? ' (утверждено)' : ' — оптимум, цена ещё не утверждена'}. Себестоимость и маржа в КП для
          заказчика не выводятся.
        </span>
      </div>
      <div className="actions">
        <div className="export-group" role="group" aria-label="Коммерческое предложение">
          <span className="label">КП:</span>
          <button type="button" onClick={() => download.mutate('kp')} disabled={download.isPending}>
            Для заказчика (Word)
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => download.mutate('kp-internal')}
            disabled={download.isPending}
            title="С приложением «Обоснование цены»: себестоимость, аналоги, факторы — заказчику не отправлять"
          >
            С обоснованием (Word)
          </button>
        </div>
        <div className="export-group" role="group" aria-label="Выгрузки">
          <span className="label">Выгрузки:</span>
          <button
            type="button"
            className="secondary"
            onClick={() => download.mutate('csv')}
            disabled={download.isPending}
            title="Строка расчёта: себестоимость, вилка, маржа, шанс — открывается в Excel"
          >
            Расчёт (Excel)
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => download.mutate('analogs')}
            disabled={download.isPending}
            title="Похожие сделки с наценкой и исходом — открывается в Excel"
          >
            Аналоги (Excel)
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => download.mutate('crm')}
            disabled={download.isPending}
            title="Сделка в формате импорта CRM (CSV, разделитель — запятая)"
          >
            Для CRM
          </button>
        </div>
      </div>
      {download.isPending && <p className="muted">Готовим файл…</p>}
      {notice && (
        <p className={notice.error ? 'notice error' : 'notice'} role="status">
          {notice.text}
        </p>
      )}
    </section>
  );
}
