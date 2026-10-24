/** Канонические ссылки на объекты системы.
 *
 * Бэкенд ссылается строкой "investment_project:201" (related_object у уведомлений,
 * initiator_company_id и т.п.). В UI такая ссылка должна вести на тот же объект,
 * что и переход из списка: "инвестиционный проект:201" → /investments/201,
 * "компания:101" → /companies/101. Один парсер — один источник правды.
 */

export type ObjectRef = { kind: string; id: number };

export function parseObjectRef(raw: string | null | undefined): ObjectRef | null {
  if (!raw) return null;
  const match = String(raw).trim().match(/^([a-z_]+):(\d+)$/i);
  if (!match) return null;
  return { kind: match[1]!.toLowerCase(), id: Number(match[2]) };
}

/** Маршрут UI для ссылки; null — у объекта нет собственного экрана (например, закупка). */
export function objectHref(raw: string | null | undefined): string | null {
  const ref = parseObjectRef(raw);
  if (!ref) return null;
  if (ref.kind === 'investment_project' || ref.kind === 'project') return `/investments/${ref.id}`;
  if (ref.kind === 'company') return `/companies/${ref.id}`;
  return null;
}

/** Человекочитаемое имя объекта: "проект #201", "компания #101". */
export function objectLabel(raw: string | null | undefined): string | null {
  const ref = parseObjectRef(raw);
  if (!ref) return null;
  if (ref.kind === 'investment_project' || ref.kind === 'project') return `проект #${ref.id}`;
  if (ref.kind === 'company') return `компания #${ref.id}`;
  if (ref.kind === 'tender') return `закупка #${ref.id}`;
  return `${ref.kind} #${ref.id}`;
}