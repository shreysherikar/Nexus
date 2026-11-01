import React from 'react';

export interface DataPoint {
  timestamp: string;
  value: number;
  label?: string;
}

export interface SimpleLineChartProps {
  data: DataPoint[];
  metricName: string;
  unit?: string;
  threshold?: number | null;
  thresholdLabel?: string;
  color?: string;
  height?: number;
  className?: string;
}

export const SimpleLineChart: React.FC<SimpleLineChartProps> = ({
  data,
  metricName,
  unit = '',
  threshold = null,
  thresholdLabel = 'Threshold',
  color = '#38bdf8', // sky-400
  height = 180,
  className = '',
}) => {
  if (!data || data.length === 0) {
    return (
      <div
        className={`flex flex-col items-center justify-center p-6 bg-noc-base/40 rounded border border-noc-border text-center ${className}`}
        style={{ height }}
      >
        <span className="text-xs text-noc-text-muted">No stored telemetry observations for {metricName}</span>
      </div>
    );
  }

  // Handle single observation honestly without drawing a fake trend line
  if (data.length === 1) {
    const single = data[0];
    return (
      <div
        className={`flex flex-col items-center justify-center p-6 bg-noc-base/40 rounded border border-noc-border text-center ${className}`}
        style={{ height }}
      >
        <div className="text-xs text-noc-text-secondary uppercase tracking-wider font-semibold mb-1">
          Single Discrete Observation
        </div>
        <div className="text-2xl font-mono font-bold text-noc-text-primary">
          {single.value.toFixed(2)}
          <span className="text-sm font-normal text-noc-text-muted ml-1">{unit}</span>
        </div>
        <div className="text-[11px] text-noc-text-muted font-mono mt-1">
          Observed at {new Date(single.timestamp).toISOString().replace('T', ' ').substring(0, 19)} UTC
        </div>
        {threshold !== null && threshold !== undefined && (
          <div className="text-[11px] font-mono mt-2 px-2 py-0.5 rounded bg-noc-surface border border-noc-border text-noc-text-secondary">
            {thresholdLabel}: {threshold.toFixed(2)} {unit}
          </div>
        )}
      </div>
    );
  }

  const values = data.map((d) => d.value);
  let minVal = Math.min(...values);
  let maxVal = Math.max(...values);

  if (threshold !== null && threshold !== undefined) {
    minVal = Math.min(minVal, threshold);
    maxVal = Math.max(maxVal, threshold);
  }

  // Add a small margin if flat
  if (minVal === maxVal) {
    minVal -= 1;
    maxVal += 1;
  }
  const range = maxVal - minVal;

  const padding = { top: 20, right: 30, bottom: 25, left: 45 };
  const width = 600; // SVG viewBox coordinate width
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const points = data.map((d, index) => {
    const x = padding.left + (index / (data.length - 1)) * plotWidth;
    const y = padding.top + plotHeight - ((d.value - minVal) / range) * plotHeight;
    return { x, y, ...d };
  });

  const pathD = points.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`, '');

  let thresholdY: number | null = null;
  if (threshold !== null && threshold !== undefined) {
    thresholdY = padding.top + plotHeight - ((threshold - minVal) / range) * plotHeight;
  }

  const firstDate = new Date(data[0].timestamp).toISOString().substring(11, 19);
  const lastDate = new Date(data[data.length - 1].timestamp).toISOString().substring(11, 19);

  return (
    <div className={`relative bg-noc-base/40 rounded border border-noc-border p-2 ${className}`}>
      <div className="flex items-center justify-between text-[11px] px-2 pb-1 font-mono text-noc-text-muted">
        <span>{metricName} ({unit})</span>
        <span>{data.length} snapshots</span>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto overflow-visible" preserveAspectRatio="none">
        {/* Y Axis Grid lines */}
        <line
          x1={padding.left}
          y1={padding.top}
          x2={width - padding.right}
          y2={padding.top}
          stroke="#334155"
          strokeDasharray="2 2"
          strokeWidth="0.5"
        />
        <line
          x1={padding.left}
          y1={padding.top + plotHeight / 2}
          x2={width - padding.right}
          y2={padding.top + plotHeight / 2}
          stroke="#334155"
          strokeDasharray="2 2"
          strokeWidth="0.5"
        />
        <line
          x1={padding.left}
          y1={padding.top + plotHeight}
          x2={width - padding.right}
          y2={padding.top + plotHeight}
          stroke="#334155"
          strokeWidth="1"
        />

        {/* Y Axis Labels */}
        <text x={padding.left - 6} y={padding.top + 4} textAnchor="end" fill="#94a3b8" fontSize="10" fontFamily="monospace">
          {maxVal.toFixed(1)}
        </text>
        <text x={padding.left - 6} y={padding.top + plotHeight / 2 + 4} textAnchor="end" fill="#94a3b8" fontSize="10" fontFamily="monospace">
          {((maxVal + minVal) / 2).toFixed(1)}
        </text>
        <text x={padding.left - 6} y={padding.top + plotHeight + 4} textAnchor="end" fill="#94a3b8" fontSize="10" fontFamily="monospace">
          {minVal.toFixed(1)}
        </text>

        {/* Threshold Line */}
        {thresholdY !== null && thresholdY >= padding.top && thresholdY <= padding.top + plotHeight && (
          <g>
            <line
              x1={padding.left}
              y1={thresholdY}
              x2={width - padding.right}
              y2={thresholdY}
              stroke="#f59e0b"
              strokeWidth="1.5"
              strokeDasharray="4 3"
            />
            <text
              x={width - padding.right + 4}
              y={thresholdY + 3}
              fill="#f59e0b"
              fontSize="9"
              fontFamily="monospace"
              fontWeight="bold"
            >
              {threshold !== null ? threshold.toFixed(1) : ''}
            </text>
          </g>
        )}

        {/* Trend Polyline */}
        <path d={pathD} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {/* Dots */}
        {points.map((p, idx) => (
          <circle key={idx} cx={p.x} cy={p.y} r={points.length > 30 ? 2 : 3} fill={color} stroke="#0f172a" strokeWidth="1" />
        ))}

        {/* X Axis Range */}
        <text x={padding.left} y={height - 6} textAnchor="start" fill="#64748b" fontSize="9" fontFamily="monospace">
          {firstDate}
        </text>
        <text x={width - padding.right} y={height - 6} textAnchor="end" fill="#64748b" fontSize="9" fontFamily="monospace">
          {lastDate}
        </text>
      </svg>
    </div>
  );
};
