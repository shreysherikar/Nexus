import React from 'react';

export interface PageHeaderProps {
  title: string;
  description?: string;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: Array<{ label: string; href?: string }>;
  className?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  badge,
  actions,
  breadcrumbs,
  className = '',
}) => {
  return (
    <div className={`mb-6 flex flex-col gap-2 ${className}`}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-noc-text-muted">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.label}>
              {idx > 0 && <span>/</span>}
              <span className={idx === breadcrumbs.length - 1 ? 'text-noc-text-secondary font-medium' : ''}>
                {crumb.label}
              </span>
            </React.Fragment>
          ))}
        </nav>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight text-noc-text-primary font-sans">
              {title}
            </h1>
            {badge}
          </div>
          {description && (
            <p className="text-xs text-noc-text-secondary mt-1">{description}</p>
          )}
        </div>

        {actions && <div className="flex items-center gap-2.5 shrink-0">{actions}</div>}
      </div>
    </div>
  );
};
