import React from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  align?: 'left' | 'center' | 'right';
  className?: string;
  isMono?: boolean;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (row: T) => string;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  className?: string;
}

export function DataTable<T>({
  columns,
  data,
  keyExtractor,
  loading = false,
  emptyMessage = 'No operational records available.',
  onRowClick,
  className = '',
}: DataTableProps<T>): React.ReactElement {
  return (
    <div
      className={`w-full overflow-x-auto rounded-lg border border-noc-border bg-noc-surface shadow-sm ${className}`}
    >
      <table className="w-full text-left border-collapse text-xs">
        <thead>
          <tr className="border-b border-noc-border bg-noc-base/70">
            {columns.map((col) => {
              const alignClass =
                col.align === 'right'
                  ? 'text-right'
                  : col.align === 'center'
                  ? 'text-center'
                  : 'text-left';
              return (
                <th
                  key={col.key}
                  className={`px-4 py-3 font-semibold text-noc-text-secondary uppercase tracking-wider ${alignClass} ${
                    col.className || ''
                  }`}
                >
                  {col.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-noc-border/60">
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-noc-text-muted">
                <div className="flex items-center justify-center gap-2">
                  <div className="w-4 h-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                  <span>Loading table records...</span>
                </div>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-10 text-center text-noc-text-muted font-mono"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row) => (
              <tr
                key={keyExtractor(row)}
                onClick={() => onRowClick && onRowClick(row)}
                className={`transition-colors hover:bg-noc-surfaceElevated ${
                  onRowClick ? 'cursor-pointer' : ''
                }`}
              >
                {columns.map((col) => {
                  const alignClass =
                    col.align === 'right'
                      ? 'text-right'
                      : col.align === 'center'
                      ? 'text-center'
                      : 'text-left';
                  const fontClass = col.isMono ? 'font-mono' : '';
                  const content = col.render
                    ? col.render(row)
                    : ((row as Record<string, unknown>)[col.key] as React.ReactNode);

                  return (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-noc-text-primary ${alignClass} ${fontClass} ${
                        col.className || ''
                      }`}
                    >
                      {content}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
