import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';

/**
 * Service Worker Architecture Note:
 * NEXUS operates as a real-time Network Operations Center (NOC) dashboard
 * requiring direct WebSocket event streaming and authentic REST communication.
 * Offline caching via Service Worker is deliberately not employed to prevent stale
 * operational telemetry states. If a service worker is ever required, it MUST be registered
 * strictly on the frontend origin/scope (port 3000) and NEVER on the backend API (port 8000).
 */

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
