import { useEffect, useRef } from 'react';

import 'maplibre-gl/dist/maplibre-gl.css';

import { palette } from '@/styles/tokens';
import type { HeatCell } from '@/types/api';

type Props = {
  cells: HeatCell[];
  onSelectRegion?: (regionId: number) => void;
};

type MapHandle = {
  remove: () => void;
  on: (type: string, handler: (...args: never[]) => void) => void;
  once: (type: string, handler: () => void) => void;
};

function toFeatureCollection(cells: HeatCell[]) {
  return {
    type: 'FeatureCollection' as const,
    features: cells.map((cell) => ({
      type: 'Feature' as const,
      // Центр региона: реальные полигоны приходят из PostGIS (mv_region_density).
      geometry: { type: 'Point' as const, coordinates: [cell.longitude ?? 61, cell.latitude ?? 57] },
      properties: {
        region_id: cell.region_id,
        region_name: cell.region_name,
        potential: cell.potential_score,
        presence: cell.presence_score,
      },
    })),
  };
}

/**
 * Картографический слой «Радара присутствия».
 *
 * Источник тайлов задаётся переменной окружения: публичные тайлы не используются в
 * демо без проверки условий использования. Если тайлов нет — рисуем только аггрегаты
 * (кружки по центру региона), карта при этом остаётся читаемой.
 *
 * Карта создаётся один раз на монтирование: фильтры обновляют данные источника,
 * а не пересоздают canvas (иначе карта мигает при каждом клике по фильтру).
 */
export function MapView({ cells, onSelectRegion }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<unknown>(null);
  const sourceRef = useRef<{ setData: (data: unknown) => void } | undefined>(undefined);
  // Колбэк и данные читаются из ref, чтобы перерисовку родителя не тянуть в зависимости эффекта.
  const cellsRef = useRef(cells);
  const selectRef = useRef(onSelectRegion);
  cellsRef.current = cells;
  selectRef.current = onSelectRegion;

  useEffect(() => {
    let cancelled = false;

    async function render() {
      const container = holder.current;
      if (!container) return;

      const maplibre = await import('maplibre-gl');
      if (cancelled) return;

      const styleUrl = import.meta.env.VITE_MAP_STYLE_URL;
      const map = new maplibre.Map({
        container,
        style: styleUrl
          ? styleUrl
          : {
              version: 8,
              sources: {},
              layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eef2f7' } }],
            },
        center: [61, 57],
        zoom: 2.4,
      });
      mapRef.current = map;

      map.on('load', () => {
        if (cancelled) return;
        map.addSource('heat', { type: 'geojson', data: toFeatureCollection(cellsRef.current) });
        sourceRef.current = map.getSource('heat') as { setData: (data: unknown) => void } | undefined;

        map.addLayer({
          id: 'heat-circles',
          type: 'circle',
          source: 'heat',
          paint: {
            // Цвет — потенциал, радиус — присутствие: квадрант читается без легенды-угадайки.
            'circle-color': [
              'interpolate',
              ['linear'],
              ['get', 'potential'],
              0,
              '#dbe7f3',
              50,
              palette.brandAccent,
              100,
              palette.brandPrimary,
            ],
            'circle-radius': ['interpolate', ['linear'], ['get', 'presence'], 0, 14, 100, 6],
            'circle-opacity': 0.85,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#ffffff',
          },
        });

        map.on('click', 'heat-circles', (event) => {
          const feature = event.features?.[0];
          const regionId = feature?.properties?.region_id;
          if (typeof regionId === 'number') selectRef.current?.(regionId);
        });
      });
    }

    void render();
    return () => {
      cancelled = true;
      sourceRef.current = undefined;
      (mapRef.current as MapHandle | null)?.remove();
      mapRef.current = null;
    };
  }, []);

  // Фильтры меняются чаще, чем карта: обновляем только данные источника.
  useEffect(() => {
    sourceRef.current?.setData(toFeatureCollection(cells));
  }, [cells]);

  return (
    <div
      ref={holder}
      style={{ height: 420, borderRadius: 8, border: `1px solid ${palette.border}` }}
      role="img"
      aria-label="Тепловая карта потенциала регионов"
    />
  );
}
