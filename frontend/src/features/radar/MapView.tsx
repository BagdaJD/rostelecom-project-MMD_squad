import { useEffect, useRef } from 'react';

import { palette } from '@/styles/tokens';
import type { HeatCell } from '@/types/api';

type Props = {
  cells: HeatCell[];
  onSelectRegion?: (regionId: number) => void;
};

/**
 * Картографический слой «Радара присутствия».
 *
 * Источник тайлов задаётся переменной окружения: публичные тайлы не используются в
 * демо без проверки условий использования. Если тайлов нет — рисуем только аггрегаты
 * (кружки по центру региона), карта при этом остаётся читаемой.
 */
export function MapView({ cells, onSelectRegion }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<unknown>(null);

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
        map.addSource('heat', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: cells.map((cell) => ({
              type: 'Feature',
              // Центр региона: реальные полигоны приходят из PostGIS (mv_region_density).
              geometry: { type: 'Point', coordinates: [cell.longitude ?? 61, cell.latitude ?? 57] },
              properties: {
                region_id: cell.region_id,
                region_name: cell.region_name,
                potential: cell.potential_score,
                presence: cell.presence_score,
              },
            })),
          },
        });

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
          if (typeof regionId === 'number') onSelectRegion?.(regionId);
        });
      });
    }

    void render();
    return () => {
      cancelled = true;
      (mapRef.current as { remove?: () => void } | null)?.remove?.();
    };
  }, [cells, onSelectRegion]);

  return (
    <div
      ref={holder}
      style={{ height: 420, borderRadius: 8, border: `1px solid ${palette.border}` }}
      role="img"
      aria-label="Тепловая карта потенциала регионов"
    />
  );
}
