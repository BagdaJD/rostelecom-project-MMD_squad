/** Проверка подписей статусов и стадий: UI обязан говорить языком кейса (ТЗ 11.1). */

import { describe, expect, it } from 'vitest';

import { clientStatusLabel } from '@/styles/tokens';
import { needLabel, stageLabel } from '@/types/api';

describe('словари интерфейса', () => {
  it('покрывает все статусы клиентов из API', () => {
    for (const status of ['active', 'prospect', 'unknown']) {
      expect(clientStatusLabel[status]).toBeTruthy();
    }
    expect(clientStatusLabel.active).toBe('Действующий клиент');
    expect(clientStatusLabel.prospect).toBe('Потенциальный клиент');
  });

  it('стадии совпадают с формулировками кейса', () => {
    expect(stageLabel.design).toBe('Проектирование');
    expect(stageLabel.modernization).toBe('Модернизация');
    expect(stageLabel.construction).toBe('Стройка');
    expect(stageLabel.launch).toBe('Запуск');
  });

  it('нужна подпись для каждой категории потребностей', () => {
    for (const category of [
      'connectivity',
      'it_infrastructure',
      'information_security',
      'video_surveillance',
      'iot_asu_tp',
      'insufficient_data',
    ]) {
      expect(needLabel[category]).toBeTruthy();
    }
  });
});
