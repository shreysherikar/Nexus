export interface NavItem {
  id: string;
  name: string;
  path: string;
  iconName: string;
  description: string;
  badge?: string | number;
  badgeVariant?: 'critical' | 'warning' | 'info' | 'neutral';
}

export const NAVIGATION_ITEMS: NavItem[] = [
  {
    id: 'overview',
    name: 'Overview',
    path: '/overview',
    iconName: 'LayoutDashboard',
    description: 'Executive network status and operational KPIs',
  },
  {
    id: 'network-map',
    name: 'Network Map',
    path: '/network-map',
    iconName: 'MapPin',
    description: 'Geographic and topological node visualization',
  },
  {
    id: 'kpis',
    name: 'KPIs & Telemetry',
    path: '/kpis',
    iconName: 'Activity',
    description: 'Core, backhaul, and radio telemetry timeseries',
  },
  {
    id: 'alarms',
    name: 'Alarms',
    path: '/alarms',
    iconName: 'Bell',
    description: 'Active alarm inventory and rule breaches',
  },
  {
    id: 'incidents',
    name: 'Incidents',
    path: '/incidents',
    iconName: 'AlertOctagon',
    description: 'Correlated incidents, RCA diagnoses, and SLA tracking',
  },
  {
    id: 'analytics',
    name: 'Analytics',
    path: '/analytics',
    iconName: 'BarChart3',
    description: 'MTTR analysis, root cause trends, and SLA reports',
  },
];
