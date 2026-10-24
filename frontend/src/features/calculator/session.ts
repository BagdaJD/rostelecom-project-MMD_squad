/**
 * Калькулятор не теряет расчёт при уходе со страницы, «Назад» и обновлении вкладки.
 *
 * Форма и последний результат лежат в sessionStorage — живут, пока открыта вкладка (как и
 * токен входа), другим вкладкам и пользователям не видны. Хранилище может быть недоступно
 * (приватный режим, запрет сайта) — тогда калькулятор просто работает без восстановления.
 */

import type { DealEstimate } from './types';

import type { FormState } from './ParamsForm';

const KEY = 'rtk.calculator.v2';

export type CalcSession = {
  /** Для какого инвестпроекта сохранено (null — расчёт без проекта). */
  projectId: number | null;
  form: FormState;
  result: DealEstimate | null;
};

export function loadSession(projectId: number | null): CalcSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as CalcSession;
    // Открыли другой проект из навигатора — его черновик важнее старого расчёта.
    if (projectId !== null && saved.projectId !== projectId) return null;
    return saved;
  } catch {
    return null;
  }
}

export function saveSession(session: CalcSession): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // нет места или хранилище запрещено — восстановления не будет, расчёт работает
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ничего страшного
  }
}
