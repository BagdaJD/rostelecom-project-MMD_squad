/** «Что влияет на шанс выиграть»: вклад факторов многофакторной модели в п.п. и её качество. */

import type { WinModelInfo } from './types';

const pp = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1).replace('.', ',')} п.п.`;
const auc = (v: number | null) => (v === null ? '—' : v.toFixed(2).replace('.', ','));

export function WinFactors({ model }: { model: WinModelInfo | null }) {
  if (!model) return null;
  if (model.type !== 'multifactor') {
    return (
      <div className="card">
        <h2>Что влияет на шанс выиграть</h2>
        <p className="muted">
          Модель: {model.model}, {model.n} сделок. Для разбора по факторам нужно больше сделок с известным
          исходом.
        </p>
      </div>
    );
  }
  const shown = model.factors.filter((f) => Math.abs(f.delta_pp) >= 0.5).slice(0, 6);
  const scale = Math.max(10, ...shown.map((f) => Math.abs(f.delta_pp)));
  return (
    <div className="card win-factors">
      <h2>Что влияет на шанс выиграть</h2>
      <p className="muted">
        При оптимальной цене: на сколько шанс выше или ниже, чем у типичного проекта в истории сделок.
      </p>
      {shown.length === 0 && <p className="muted">Проект типичный — факторы почти не сдвигают шанс.</p>}
      <ul>
        {shown.map((f) => (
          <li key={f.factor}>
            <span className="f-label">
              <strong>{f.label}</strong>: {f.value}
              <small> · типично {f.typical}</small>
            </span>
            <span className="f-bar" aria-hidden="true">
              <span
                className={f.delta_pp >= 0 ? 'pos' : 'neg'}
                style={{ width: `${(Math.abs(f.delta_pp) / scale) * 50}%` }}
              />
            </span>
            <span className={f.delta_pp >= 0 ? 'f-val pos' : 'f-val neg'}>{pp(f.delta_pp)}</span>
          </li>
        ))}
      </ul>
      <p className="model-note">
        {model.model} · 7 признаков · обучение на {model.n_train} ранних сделках, проверка на {model.n_test}{' '}
        последних: ROC-AUC {auc(model.auc)} (только наценка — {auc(model.auc_baseline)})
        {model.basis === 'synthetic' && ' · обучено на демо-данных'}
      </p>
    </div>
  );
}
