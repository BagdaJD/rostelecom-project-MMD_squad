/** Глобальный фильтр региона в единой шапке (ТЗ 11.1).
 *
 * Выбор хранится в localStorage и подхватывается модулями; в URL остаются
 * локальные фильтры страницы (они переносимы по ссылке).
 */
import { createContext, useContext, type ReactNode } from 'react';

export const GLOBAL_REGION_KEY = 'rtk.globalRegion';

export function readGlobalRegion(): number | null {
  const raw = globalThis.localStorage?.getItem(GLOBAL_REGION_KEY) ?? null;
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function writeGlobalRegion(value: number | null): void {
  if (value === null) globalThis.localStorage?.removeItem(GLOBAL_REGION_KEY);
  else globalThis.localStorage?.setItem(GLOBAL_REGION_KEY, String(value));
}

/** Значение глобального фильтра для страниц: шапка владеет состоянием. */
const GlobalRegionContext = createContext<number | null>(null);

export function GlobalRegionProvider({
  value,
  children,
}: {
  value: number | null;
  children: ReactNode;
}) {
  return <GlobalRegionContext.Provider value={value}>{children}</GlobalRegionContext.Provider>;
}

export function useGlobalRegion(): number | null {
  return useContext(GlobalRegionContext);
}

export function GlobalFilter({
  regions,
  value,
  onChange,
}: {
  regions: { id: number; name: string }[];
  value: number | null;
  onChange: (regionId: number | null) => void;
}) {
  return (
    <label className="global-filter" aria-label="Глобальный фильтр региона">
      <span className="muted">Регион</span>
      <select
        value={value ?? ''}
        onChange={(event) => {
          const next = event.target.value ? Number(event.target.value) : null;
          onChange(next);
        }}
      >
        <option value="">Все регионы</option>
        {regions.map((region) => (
          <option key={region.id} value={region.id}>
            {region.name}
          </option>
        ))}
      </select>
    </label>
  );
}