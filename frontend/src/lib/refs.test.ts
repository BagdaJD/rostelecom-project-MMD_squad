/** Ссылки на объекты: один парсер `kind:id` и одинаковые маршруты UI. */

import { describe, expect, it } from 'vitest';

import { objectHref, objectLabel, parseObjectRef } from '@/lib/refs';

describe('ссылки на объекты системы', () => {
  it('разбирает canonical-kind:id из уведомлений и связанных объектов', () => {
    expect(parseObjectRef('investment_project:201')).toEqual({ kind: 'investment_project', id: 201 });
    expect(parseObjectRef('company:101')).toEqual({ kind: 'company', id: 101 });
    expect(parseObjectRef('  tender:301 ')).toEqual({ kind: 'tender', id: 301 });
  });

  it('не принимает мусорные строки и пустоту', () => {
    expect(parseObjectRef('')).toBeNull();
    expect(parseObjectRef(null)).toBeNull();
    expect(parseObjectRef('проект 201')).toBeNull();
    expect(parseObjectRef('project:abc')).toBeNull();
  });

  it('строит маршруты экранов, которых нет в UI — null, а не сломанная ссылка', () => {
    expect(objectHref('investment_project:201')).toBe('/investments/201');
    expect(objectHref('company:101')).toBe('/companies/101');
    expect(objectHref('tender:301')).toBeNull();
  });

  it('человекочитаемая подпись не уезжает в машинное имя kind', () => {
    expect(objectLabel('investment_project:201')).toBe('проект #201');
    expect(objectLabel('company:101')).toBe('компания #101');
    expect(objectLabel('tender:301')).toBe('закупка #301');
  });
});