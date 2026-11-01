/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        noc: {
          canvas: '#070a10',
          base: '#0c121e',
          surface: '#111927',
          surfaceElevated: '#182337',
          surfaceHighlight: '#1e2c45',
          border: '#1e293b',
          borderHighlight: '#334155',
          borderFocus: '#3b82f6',
          text: {
            primary: '#f1f5f9',
            secondary: '#94a3b8',
            muted: '#64748b',
          },
          status: {
            healthy: '#22c55e',
            healthyBg: '#052e16',
            healthyBorder: '#15803d',
            warning: '#f59e0b',
            warningBg: '#451a03',
            warningBorder: '#b45309',
            critical: '#ef4444',
            criticalBg: '#450a0a',
            criticalBorder: '#b91c1c',
            unknown: '#94a3b8',
            unknownBg: '#1e293b',
            unknownBorder: '#334155',
          },
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
};
