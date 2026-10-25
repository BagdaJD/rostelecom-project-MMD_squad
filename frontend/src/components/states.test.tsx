/** RTL-тесты общих состояний: загрузка, ошибка с повтором, пустые данные (ТЗ 11.3). */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DataGap, EmptyState, ErrorState, Loading, Warning } from '@/components/states';

describe('состояния экранов', () => {
  it('Loading показывает роль status и aria-live', () => {
    render(<Loading label="Загружаем белые пятна" />);
    const node = screen.getByRole('status');
    expect(node).toHaveTextContent('Загружаем белые пятна');
    expect(node).toHaveAttribute('aria-live', 'polite');
  });

  it('ErrorState показывает сообщение и повтор вызывает onRetry', async () => {
    const retry = vi.fn();
    render(<ErrorState error={new Error('Сеть недоступна')} onRetry={retry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Сеть недоступна');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('EmptyState описывает пустые данные и подсказку ослабить фильтры', () => {
    render(<EmptyState title="Белых пятен не найдено" hint="Ослабьте фильтры" />);
    expect(screen.getByRole('status')).toHaveTextContent('Белых пятен не найдено');
    expect(screen.getByText('Ослабьте фильтры')).toBeInTheDocument();
  });

  it('DataGap — плашка пропуска, а не ноль; Warning — note', () => {
    render(
      <div>
        <DataGap what="Прибыль" />
        <Warning>Оценка требует проверки</Warning>
      </div>,
    );
    expect(screen.getByText(/нет данных/)).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Оценка требует проверки');
  });
});