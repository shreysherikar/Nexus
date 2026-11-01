import React from 'react';

export interface BarCategory {
  key: string;
  label: string;
  value: number;
  color: string;
}

export interface BarChartDistributionProps {
  title?: string;
  categories: BarCategory[];
  total?: number;
  className?: string;
}

export const BarChartDistribution: React.FC<BarChartDistributionProps> = ({
  title,
  categories,
  total: propTotal,
  className = '',
}) => {
  const calculatedTotal = categories.reduce((sum, c) => sum + c.value, 0);
  const total = propTotal ?? calculatedTotal;

  return (
    <div className={`p-4 rounded-lg bg-noc-surface border border-noc-border ${className}`}>
      {title && (
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
          <h4 className="text-xs font-semibold text-noc-text-primary uppercase tracking-wider">{title}</h4>
          <span className="text-xs font-mono text-noc-text-muted">Total: {total}</span>
        </div>
      )}

      {total === 0 ? (
        <div className="text-center py-6 text-xs text-noc-text-muted">No records observed</div>
      ) : (
        <div className="space-y-2.5">
          {categories.map((cat) => {
            const pct = total > 0 ? Math.round((cat.value / total) * 100) : 0;
            return (
              <div key={cat.key} className="space-y-1">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-noc-text-secondary">{cat.label}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-noc-text-primary">{cat.value}</span>
                    <span className="text-noc-text-muted text-[11px] w-8 text-right">({pct}%)</span>
                  </div>
                </div>
                <div className="w-full h-2 bg-noc-base rounded overflow-hidden">
                  <div
                    className="h-full rounded transition-all duration-300"
                    style={{ width: `${pct}%`, backgroundColor: cat.color }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
