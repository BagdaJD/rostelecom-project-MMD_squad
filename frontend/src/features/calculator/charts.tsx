/** Графики калькулятора (ECharts, только нужные модули — бандл не раздувается).
 *
 * Цвета: маржа — фиолетовый бренда, шанс выиграть — оранжевый бренда (пара проверена на
 * различимость при дальтонизме). Подписи и значения — цветом текста, не цветом серии.
 */

import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { SVGRenderer } from 'echarts/renderers';
import { useEffect, useRef, useState } from 'react';

import { pct, rub, thousands } from './pricing';
import type { Comparable, CurvePoint } from './types';

/** Цвета бренда Ростелекома для графиков калькулятора (общие токены src/styles не меняются). */
const palette = {
  brandPrimary: '#7700FF',
  brandAccent: '#FF4F12',
  brandSoft: '#F1E8FF',
  textPrimary: '#101828',
  textMuted: '#5A6472',
} as const;

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  SVGRenderer,
]);

const AXIS = { color: palette.textMuted, fontSize: 12 };

/** Обёртка ECharts без сторонних React-биндингов: init → setOption → resize → dispose. */
function EChart({ option, height }: { option: echarts.EChartsCoreOption; height: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!box.current) return undefined;
    const instance = echarts.init(box.current, undefined, { renderer: 'svg' });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(box.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);
  return <div ref={box} style={{ height, width: '100%' }} />;
}
const GRID_LINE = { lineStyle: { color: '#E6E7EB' } };

function useNarrow(): boolean {
  const query = '(max-width: 640px)';
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = () => setNarrow(mql.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);
  return narrow;
}

type RangeProps = { cost: number; min: number; optimum: number; max: number; selected: number };

export function MarginChart({ curve, ...r }: RangeProps & { curve: CurvePoint[] }) {
  const narrow = useNarrow();
  const hasWin = curve.some((p) => p.win_prob !== null);
  const option = {
    animation: false,
    grid: { left: narrow ? 40 : 48, right: narrow ? 16 : 110, top: 24, bottom: 44 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      valueFormatter: (v: number) => pct(v),
      formatter: (items: { axisValue: number; seriesName: string; value: [number, number] }[]) =>
        [`<b>${rub(items[0]?.value[0])}</b>`, ...items.map((i) => `${i.seriesName}: ${pct(i.value[1])}`)].join(
          '<br/>',
        ),
    },
    xAxis: {
      type: 'value',
      min: curve[0]?.price,
      max: curve[curve.length - 1]?.price,
      name: 'цена в КП, тыс. ₽',
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: AXIS,
      axisLabel: {
        ...AXIS,
        hideOverlap: true,
        showMinLabel: false,
        showMaxLabel: false,
        formatter: (v: number) => Math.round(v / 1000).toLocaleString('ru-RU'),
      },
      splitNumber: narrow ? 3 : 5,
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { ...AXIS, formatter: '{value}%' },
      splitLine: GRID_LINE,
    },
    series: [
      {
        name: 'маржа',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2.5, color: palette.brandPrimary },
        itemStyle: { color: palette.brandPrimary },
        endLabel: narrow ? undefined : { show: true, formatter: 'маржа', color: palette.textPrimary },
        data: curve.map((p) => [p.price, p.margin_pct]),
        markArea: {
          silent: true,
          itemStyle: { color: palette.brandSoft },
          label: { show: true, position: 'insideTop', color: palette.textMuted, formatter: 'вилка' },
          data: [[{ xAxis: r.min }, { xAxis: r.max }]],
        },
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            {
              xAxis: r.optimum,
              lineStyle: { color: palette.textPrimary, type: 'dashed', width: 1.5 },
              label: { formatter: `оптимум ${thousands(r.optimum)}`, color: palette.textPrimary },
            },
            ...(Math.abs(r.selected - r.optimum) > 500
              ? [
                  {
                    xAxis: r.selected,
                    lineStyle: { color: palette.brandPrimary, width: 2 },
                    label: { formatter: `в КП ${thousands(r.selected)}`, color: palette.brandPrimary },
                  },
                ]
              : []),
          ],
        },
      },
      ...(hasWin
        ? [
            {
              name: 'шанс выиграть',
              type: 'line',
              showSymbol: false,
              lineStyle: { width: 2.5, color: palette.brandAccent },
              itemStyle: { color: palette.brandAccent },
              endLabel: narrow
                ? undefined
                : { show: true, formatter: 'шанс выиграть', color: palette.textPrimary },
              data: curve.map((p) => [p.price, p.win_prob]),
            },
          ]
        : []),
    ],
  };
  return (
    <EChart option={option} height={narrow ? 260 : 330} />
  );
}

export function AnalogsChart({ comparables, ...r }: RangeProps & { comparables: Comparable[] }) {
  const narrow = useNarrow();
  const rows = comparables.filter((c) => c.price_index).slice(0, 10).reverse();
  const label = (c: Comparable) => {
    const short = c.title.replace(/^Диспетчеризация:\s*/, '');
    return narrow ? short.split(',').slice(1).join(',').trim() : short;
  };
  const point = (c: Comparable) => ({
    value: [c.price_index, label(c)],
    comparable: c,
  });
  const idx = (price: number) => price / r.cost;
  const option = {
    animation: false,
    grid: { left: narrow ? 8 : 16, right: 24, top: 52, bottom: 40, containLabel: true },
    legend: { top: 0, left: 0, textStyle: AXIS, itemWidth: 12, itemHeight: 12 },
    tooltip: {
      trigger: 'item',
      formatter: (p: { data: { comparable: Comparable } }) => {
        const c = p.data.comparable;
        return [
          `<b>${c.title}</b>`,
          `Сходство: ${Math.round(c.similarity * 100)}%`,
          `Цена: ${rub(c.contract_value)} · себестоимость ${rub(c.cost_value)}`,
          `Наценка: ×${c.price_index?.toFixed(2).replace('.', ',')}`,
          c.outcome === 'won' ? 'Выиграли' : c.outcome === 'lost' ? 'Проиграли' : '',
          c.retro_price_basis === 'contract' ? 'Реальный контракт ЕИС' : 'Демо-сделка',
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'value',
      scale: true,
      name: 'наценка = цена сделки ÷ её себестоимость',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: AXIS,
      axisLabel: {
        ...AXIS,
        hideOverlap: true,
        formatter: (v: number) => `×${v.toFixed(2).replace('.', ',')}`,
      },
      splitNumber: narrow ? 3 : 5,
      splitLine: GRID_LINE,
    },
    yAxis: {
      type: 'category',
      data: rows.map(label),
      axisLabel: { ...AXIS, color: palette.textPrimary, width: narrow ? 130 : 260, overflow: 'truncate' },
      axisTick: { show: false },
    },
    series: [
      {
        name: 'выиграли',
        type: 'scatter',
        symbolSize: 13,
        itemStyle: { color: palette.brandPrimary },
        data: rows.filter((c) => c.outcome !== 'lost').map(point),
        markArea: {
          silent: true,
          itemStyle: { color: palette.brandSoft },
          data: [[{ xAxis: idx(r.min) }, { xAxis: idx(r.max) }]],
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: palette.textPrimary, type: 'dashed', width: 1.5 },
          label: {
            formatter: `ваша цена ×${idx(r.selected).toFixed(2).replace('.', ',')}`,
            color: palette.textPrimary,
          },
          data: [{ xAxis: idx(r.selected) }],
        },
      },
      {
        name: 'проиграли',
        type: 'scatter',
        symbolSize: 13,
        itemStyle: { color: '#FFFFFF', borderColor: palette.brandPrimary, borderWidth: 2.5 },
        data: rows.filter((c) => c.outcome === 'lost').map(point),
      },
    ],
  };
  return (
    <EChart option={option} height={Math.max(240, 70 + rows.length * 38)} />
  );
}

export function StructureChart({
  breakdown,
  cost,
  price,
}: {
  breakdown: { label: string; amount: number }[];
  cost: number;
  price: number;
}) {
  const rows = [...breakdown, { label: 'Маржа', amount: Math.max(price - cost, 0) }].reverse();
  const option = {
    animation: false,
    grid: { left: 8, right: 96, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: 'item', valueFormatter: (v: number) => rub(v) },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.label.replace(/ \(.*\)$/, '')),
      axisLabel: { ...AXIS, color: palette.textPrimary },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: rows.map((r) => ({
          value: r.amount,
          itemStyle: {
            color: r.label === 'Маржа' ? palette.brandAccent : palette.brandPrimary,
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: {
          show: true,
          position: 'right',
          color: palette.textPrimary,
          formatter: (p: { value: number }) => `${thousands(p.value)} · ${Math.round((p.value / price) * 100)}%`,
        },
      },
    ],
  };
  return (
    <EChart option={option} height={40 + rows.length * 36} />
  );
}
