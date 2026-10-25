/** Общие компоненты экранов: состояния загрузки, ошибки и пустых данных.
 *
 * Это критерий «Удобство интерфейса»: без них экран считается незаконченным (ТЗ 11.3).
 */

import type { ReactNode } from 'react';

export function Loading({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="card muted" role="status" aria-live="polite">
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="card" role="alert">
      <strong>Не удалось загрузить данные</strong>
      <p className="muted">{error.message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card" role="status">
      <strong>{title}</strong>
      {hint && <p className="muted">{hint}</p>}
    </div>
  );
}

/** Частичные данные показываем плашкой, а не нулём: пропуск ≠ 0 (ТЗ 6.8). */
export function DataGap({ what }: { what: string }) {
  return (
    <span className="data-gap" title={`${what}: нет данных в источнике`}>
      {what}: нет данных
    </span>
  );
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="warning" role="note">
      {children}
    </div>
  );
}

export function QualityBadge({ quality }: { quality: string }) {
  const map: Record<string, string> = {
    sufficient: 'данных достаточно',
    limited: 'данных ограниченно',
    insufficient: 'данных недостаточно',
  };
  return <span className="badge badge--unknown">{map[quality] ?? quality}</span>;
}
