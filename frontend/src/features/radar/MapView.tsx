/** Картографический слой: точки регионов без пересоздания canvas.
 *
 * Источник тайлов задаётся переменной окружения: публичные тайлы не используются в
 * демо без проверки условий использования. Если тайлов нет — рисуем только агрегаты
 * (кружки по центру региона), карта при этом остаётся читаемой.
 *
 * Карта создаётся один раз на монтирование: фильтры обновляют данные источника,
 * а не пересоздают canvas (иначе карта мигает при каждом клике по фильтру).
 * Абстрагировали «цвет/радиус» в MapPoint: Радар рисует потенциал×присутствие,
 * Навигатор — активность инвестсобытий по региону.
 */
import { useEffect, useRef } from 'react';

import 'maplibre-gl/dist/maplibre-gl.css';

import { palette } from '@/styles/tokens';

export type MapPoint = {
  region_id: number;
  region_name: string;
  longitude?: number | null;
  latitude?: number | null;
  /** 0..100: цвет точки (потенциал или активность). */
  colorValue: number;
  /** 0..100: размер точки (прямой: больше значение — крупнее точка). */
  radiusValue: number | null;
};

type Props = {
  points: MapPoint[];
  selectedRegion?: number | null;
  onSelectRegion?: (regionId: number) => void;
  ariaLabel?: string;
};

type MapHandle = {
  remove: () => void;
  on: (type: string, handler: (...args: never[]) => void) => void;
  once: (type: string, handler: () => void) => void;
};

function toFeatureCollection(points: MapPoint[], selectedRegion: number | null) {
  return {
    type: 'FeatureCollection' as const,
    features: points.flatMap((point) => {
      if (
        point.longitude == null ||
        point.latitude == null ||
        !Number.isFinite(point.longitude) ||
        !Number.isFinite(point.latitude)
      ) {
        return [];
      }
      return [
        {
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [point.longitude, point.latitude] },
          properties: {
            region_id: point.region_id,
            region_name: point.region_name,
            color: point.colorValue,
            radius: point.radiusValue ?? -1,
            selected: selectedRegion === point.region_id ? 1 : 0,
          },
        },
      ];
    }),
  };
}

export function MapView({ points, selectedRegion = null, onSelectRegion, ariaLabel = 'Карта регионов' }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<unknown>(null);
  const sourceRef = useRef<{ setData: (data: unknown) => void } | undefined>(undefined);
  // Колбэк и данные читаются из ref, чтобы перерисовку родителя не тянуть в зависимости эффекта.
  const pointsRef = useRef(points);
  const selectedRef = useRef(selectedRegion);
  const selectRef = useRef(onSelectRegion);
  pointsRef.current = points;
  selectedRef.current = selectedRegion;
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
        map.addSource('heat', { type: 'geojson', data: toFeatureCollection(pointsRef.current, selectedRef.current) });
        sourceRef.current = map.getSource('heat') as { setData: (data: unknown) => void } | undefined;

        map.addLayer({
          id: 'heat-circles',
          type: 'circle',
          source: 'heat',
          paint: {
            'circle-color': [
              'interpolate',
              ['linear'],
              ['get', 'color'],
              0,
              '#dbe7f3',
              50,
              palette.brandAccent,
              100,
              palette.brandPrimary,
            ],
            'circle-radius': [
              'case',
              ['<', ['get', 'radius'], 0],
              8,
              ['interpolate', ['linear'], ['get', 'radius'], 0, 6, 100, 14],
            ],
            'circle-opacity': 0.85,
            'circle-stroke-width': [
              'case',
              ['==', ['get', 'selected'], 1],
              3,
              1,
            ],
            'circle-stroke-color': [
              'case',
              ['==', ['get', 'selected'], 1],
              '#B3261E',
              '#ffffff',
            ],
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
    sourceRef.current?.setData(toFeatureCollection(pointsRef.current, selectedRef.current));
  }, [points, selectedRegion]);

  return (
    <div
      ref={holder}
      style={{ height: 420, borderRadius: 8, border: `1px solid ${palette.border}` }}
      role="img"
      aria-label={ariaLabel}
    />
  );
}