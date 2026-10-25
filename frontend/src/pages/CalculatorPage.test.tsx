/** RTL-тесты формы калькулятора: валидация, успешный расчёт и сообщение об ошибке (ТЗ 11.3). */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { CalculatorPage } from '@/pages/CalculatorPage';
import { GlobalRegionProvider } from '@/components/GlobalFilter';
import { api } from '@/api/client';
import type { DealEstimate } from '@/types/api';

const estimate: DealEstimate = {
  estimate_id: 1,
  currency: 'RUB',
  estimate: { min: '1000', optimum: '1500', max: '2000' },
  estimator_mode: 'analogs',
  confidence: 'medium',
  data_quality: 'limited',
  comparables: [
    { deal_id: 10, title: 'Аналог', contract_value: '1000000.00', similarity: 0.8, retro_price_basis: 'synthetic' },
  ],
  adjustments: [{ factor: 'urgency', value: 1.05, note: '' }],
  breakdown: [{ article: 'works', amount: '600' }],
  price_period: null,
  model_version: '0.1',
  requires_human_approval: true,
  warning: 'Оценка требует проверки',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GlobalRegionProvider value={3}>
        <CalculatorPage />
      </GlobalRegionProvider>
    </QueryClientProvider>,
  );
}

describe('форма калькулятора', () => {
  it('показывает валидацию обязательных полей без запроса в API', async () => {
    const spy = vi.spyOn(api, 'estimateDeal');
    renderPage();
    await userEvent.click(screen.getByRole('button', { name: 'Рассчитать диапазон' }));
    await screen.findByText('Выберите тип проекта');
    expect(screen.getByText('Укажите масштаб')).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('отправляет форму и показывает вилку, аналоги и предупреждение', async () => {
    const spy = vi.spyOn(api, 'estimateDeal').mockResolvedValue(estimate);
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText('Тип проекта'), 'connectivity');
    await userEvent.selectOptions(screen.getByLabelText('Масштаб'), 'medium');
    await userEvent.click(screen.getByRole('button', { name: 'Рассчитать диапазон' }));

    await screen.findByText('Ценовая вилка');
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ project_type: 'connectivity', scale: 'medium', region_id: 3 }),
    );
    expect(screen.getByText('Оценка требует проверки')).toBeInTheDocument();
  });

  it('показывает ошибку расчёта в роли alert', async () => {
    vi.spyOn(api, 'estimateDeal').mockRejectedValue(new Error('Позиции не загружены'));
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText('Тип проекта'), 'connectivity');
    await userEvent.selectOptions(screen.getByLabelText('Масштаб'), 'medium');
    await userEvent.click(screen.getByRole('button', { name: 'Рассчитать диапазон' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Позиции не загружены');
  });
});