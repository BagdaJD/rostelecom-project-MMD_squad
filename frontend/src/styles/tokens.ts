/** Дизайн-токены: единственный источник цветов, отступов и типографики.
 *
 * Корпоративная палитра ПАО «Ростелеком» подставляется здесь после получения брендбука
 * (ТЗ 11.1). Пока используются нейтральные значения — замене подлежит только этот файл.
 */

export const palette = {
  brandPrimary: '#0050A0',
  brandAccent: '#00B2E3',
  textPrimary: '#1A1A1A',
  textMuted: '#5A6472',
  surface: '#FFFFFF',
  surfaceAlt: '#F2F5F9',
  border: '#B9C6D6',
  // Семантика: статусы клиентов и качество данных.
  statusActive: '#0E7C3F',
  statusProspect: '#B26A00',
  statusUnknown: '#5A6472',
  qualityGood: '#0E7C3F',
  qualityLimited: '#B26A00',
  qualityLow: '#B3261E',
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const radius = { sm: 4, md: 8, lg: 12 } as const;

export const typography = {
  fontFamily: "'DejaVu Sans', 'Segoe UI', system-ui, sans-serif",
  sizes: { xs: 12, sm: 13, md: 15, lg: 18, xl: 24, xxl: 32 },
  weights: { regular: 400, medium: 500, bold: 700 },
} as const;

/** Брейкпоинты из ТЗ 11.2: планшет и смартфон — целевые устройства, не «по возможности». */
export const breakpoints = { mobile: 390, tablet: 768, desktop: 1440 } as const;

/** Подписи статусов: легенда объясняет правило, а не только цвет (ТЗ 7). */
export const clientStatusLabel: Record<string, string> = {
  active: 'Действующий клиент',
  prospect: 'Потенциальный клиент',
  unknown: 'Не определено',
};
