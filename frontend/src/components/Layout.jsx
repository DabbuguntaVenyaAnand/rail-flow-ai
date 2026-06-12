import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useNetwork } from '../context/NetworkContext';

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: '◉' },
  { to: '/ops', label: 'Operations', icon: '▣' },
  { to: '/pathfinder', label: 'Pathfinder', icon: '◎' },
  { to: '/analytics', label: 'Analytics', icon: '◈' },
];

const HEALTH_BADGE = {
  healthy: { label: 'Healthy', className: 'health-healthy' },
  degraded: { label: 'Degraded', className: 'health-degraded' },
  critical: { label: 'Critical', className: 'health-critical' },
  unknown: { label: 'Unknown', className: 'health-unknown' },
};

export default function Layout({ children }) {
  const location = useLocation();
  const { networkHealth, trainStatus, delayedNodeIds, impactedNodeIds } = useNetwork();
  const health = HEALTH_BADGE[networkHealth] ?? HEALTH_BADGE.unknown;
  const delayedTrains = trainStatus.filter(t => t.delay_minutes > 10).length;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-brand">
          <span className="brand-icon">🚆</span>
          <div>
            <h1 className="brand-title">Rail-Flow AI</h1>
            <p className="brand-subtitle">Digital Twin Control Tower</p>
          </div>
        </div>

        <nav className="app-nav">
          {NAV_ITEMS.map(({ to, label, icon }) => (
            <Link
              key={to}
              to={to}
              className={`nav-link ${location.pathname === to ? 'nav-link-active' : ''}`}
            >
              <span className="nav-icon">{icon}</span>
              {label}
            </Link>
          ))}
        </nav>

        <div className="header-status">
          <div className={`status-pill ${health.className}`}>{health.label}</div>
          <div className="status-metric">
            <span className="metric-value">{trainStatus.length}</span>
            <span className="metric-label">Trains</span>
          </div>
          <div className="status-metric">
            <span className="metric-value metric-warn">{delayedTrains}</span>
            <span className="metric-label">Delayed</span>
          </div>
          <div className="status-metric">
            <span className="metric-value metric-alert">{delayedNodeIds.length}</span>
            <span className="metric-label">Disruptions</span>
          </div>
          <div className="status-metric">
            <span className="metric-value metric-orange">{impactedNodeIds.length}</span>
            <span className="metric-label">Ripple</span>
          </div>
        </div>
      </header>

      <main className="app-main">{children}</main>
    </div>
  );
}
