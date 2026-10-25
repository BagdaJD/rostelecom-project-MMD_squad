/** Таблица с сортировкой и пагинацией (ТЗ 11.1).
 *
 * Компонент-обёртка над `<table>`: сортировка по колонкам (клик по заголовку),
 * пагинация, aria-sort и подписи. Состояние локальное — фильтры остаются в URL.
 */
import { useMemo, useState, type ReactNode } from 'react';

export type DataTableColumn<T> = {
  key: string;
  header: string;
  align?: 'left' | 'right';
  /** Значение для сортировки; undefined/сортировка по тексту, если не задан. */
  sortValue?: (row: T) => string | number | null;
  render: (row: T) => ReactNode;
};

type SortState = { key: string; direction: 'asc' | 'desc' } | null;

function compareValues(a: string | number | null, b: string | number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), 'ru', { sensitivity: 'base' });
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  pageSize = 5,
  emptyLabel = 'Нет данных',
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  pageSize?: number;
  emptyLabel?: string;
}) {
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    if (!column?.sortValue) return rows;
    const value = column.sortValue;
    return [...rows].sort((a, b) => {
      const result = compareValues(value(a), value(b));
      return sort.direction === 'asc' ? result : -result;
    });
  }, [rows, sort, columns]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visible = sorted.slice(safePage * pageSize, safePage * pageSize + pageSize);

  function toggleSort(column: DataTableColumn<T>) {
    if (!column.sortValue) return;
    setPage(0);
    setSort((current) => {
      if (current?.key !== column.key) return { key: column.key, direction: 'asc' };
      return current.direction === 'asc'
        ? { key: column.key, direction: 'desc' }
        : null;
    });
  }

  function ariaSort(column: DataTableColumn<T>): 'ascending' | 'descending' | 'none' {
    if (sort?.key !== column.key) return 'none';
    return sort.direction === 'asc' ? 'ascending' : 'descending';
  }

  return (
    <div className="data-table">
      <table>
        <thead>
          <tr>
            {columns.map((column) => {
              const sortable = Boolean(column.sortValue);
              const inner = sortable ? (
                <button
                  type="button"
                  className="sort-button"
                  onClick={() => toggleSort(column)}
                  aria-label={`Сортировать: ${column.header}`}
                >
                  {column.header}
                  <span aria-hidden="true" className="sort-mark">
                    {sort?.key === column.key ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}
                  </span>
                </button>
              ) : (
                column.header
              );
              return (
                <th key={column.key} aria-sort={ariaSort(column)}>
                  {inner}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} style={column.align ? { textAlign: column.align } : undefined}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
          {visible.length === 0 && (
            <tr>
              <td className="muted" colSpan={columns.length}>
                {emptyLabel}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {sorted.length > pageSize && (
        <nav className="pagination" aria-label="Пагинация таблицы">
          <button
            type="button"
            disabled={safePage === 0}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
          >
            ← Назад
          </button>
          <span className="muted">
            {safePage + 1} / {pageCount} · всего {sorted.length}
          </span>
          <button
            type="button"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
          >
            Вперёд →
          </button>
        </nav>
      )}
    </div>
  );
}